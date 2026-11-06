#!/bin/sh
# Installs the weekly digest so it runs itself, once per Epic rotation.
#
# The schedule is daily, not "Thursday at 11:00", on purpose. A Chromebook that
# is asleep at 11am would miss the week outright, so the daily run plus one at
# boot covers every case: when a run finds a rotation it has already handled it
# exits immediately, and when it finds an unhandled one it does the digest.
#
#   ./install_cron.sh            install or update the schedule
#   ./install_cron.sh --show     print the installed entry, change nothing
#   ./install_cron.sh --remove   take the schedule out again
#
# Safe to re-run: entries are replaced, never duplicated.
set -u

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUN="$DIR/run_weekly.sh"
MARK="# epic-gfn-watchlist"
HOURMIN="17 12"

MODE=install
for arg in "$@"; do
    case "$arg" in
        --show) MODE=show ;;
        --remove) MODE=remove ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

chmod +x "$RUN" 2>/dev/null || true

entries() {
    printf '%s schedule -- remove with install_cron.sh --remove\n' "$MARK"
    printf '%s * * * cd %s && %s\n' "$HOURMIN" "$DIR" "$RUN"
    printf '@reboot sleep 120 && cd %s && %s\n' "$DIR" "$RUN"
}

# cron, if this machine has it (a ChromeOS Linux container often does not).
if command -v crontab >/dev/null 2>&1; then
    EXISTING=$(crontab -l 2>/dev/null || true)
    case "$EXISTING" in
        *"run_weekly.sh"*) INSTALLED=yes ;;
        *) INSTALLED=no ;;
    esac

    if [ "$MODE" = show ]; then
        if [ "$INSTALLED" = yes ]; then
            echo "installed:"
            printf '%s\n' "$EXISTING" | grep -e "$MARK" -e "run_weekly" | sed 's/^/  /'
        else
            echo "not installed (run ./install_cron.sh)"
        fi
        exit 0
    fi

    KEPT=$(printf '%s\n' "$EXISTING" | grep -v -e "run_weekly" -e "$MARK" | sed '/^[[:space:]]*$/d' || true)

    if [ "$MODE" = remove ]; then
        { [ -n "$KEPT" ] && printf '%s\n' "$KEPT"; } | crontab -
        echo "removed. weekly.log and .last_weekly_run are untouched."
        exit 0
    fi

    { [ -n "$KEPT" ] && printf '%s\n' "$KEPT"; entries; } | crontab -
    echo "installed crontab entry:"
    entries | sed 's/^/  /'
    echo
    echo "  log: $DIR/weekly.log   (tail -n 40 weekly.log to read it)"
    echo "  test it now: $RUN --force"
    exit 0
fi

# systemd user timer, for a container with systemd but no cron.
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    if [ "$MODE" = show ]; then
        systemctl --user list-timers epic-gfn-watchlist.timer --no-pager 2>/dev/null || echo "not installed"
        exit 0
    fi
    if [ "$MODE" = remove ]; then
        systemctl --user disable --now epic-gfn-watchlist.timer 2>/dev/null || true
        rm -f "$UNITS/epic-gfn-watchlist.service" "$UNITS/epic-gfn-watchlist.timer"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "removed the systemd user timer."
        exit 0
    fi
    mkdir -p "$UNITS"
    cat > "$UNITS/epic-gfn-watchlist.service" <<EOF
[Unit]
Description=Weekly Epic + GOG freebies vs GeForce NOW

[Service]
Type=oneshot
ExecStart=$RUN
EOF
    cat > "$UNITS/epic-gfn-watchlist.timer" <<EOF
[Unit]
Description=Daily catch-up for the weekly digest

[Timer]
OnCalendar=daily
OnBootSec=2min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now epic-gfn-watchlist.timer
    loginctl enable-linger "$(id -un)" 2>/dev/null || true
    echo "installed a systemd user timer (daily, catching up after sleep):"
    systemctl --user list-timers epic-gfn-watchlist.timer --no-pager | sed 's/^/  /'
    exit 0
fi

cat <<EOF
No cron and no user-level systemd here, so nothing was installed.

On a ChromeOS Linux container, cron usually needs installing once:

  sudo apt update && sudo apt install -y cron
  sudo service cron start
  ./install_cron.sh

Or skip the scheduler entirely and run it by hand after the Thursday rotation:

  $RUN --force
EOF
exit 1
