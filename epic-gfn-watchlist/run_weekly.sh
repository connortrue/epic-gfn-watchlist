#!/bin/sh
# Runs the weekly digest and appends it to weekly.log.
#
# By default it asks weekly.py whether a rotation is actually unhandled, so
# calling this daily is safe: the digest happens once per Epic rotation, on
# whichever day the machine is awake, never twice for the same week.
#
#   ./run_weekly.sh            run if a rotation is waiting, otherwise do nothing
#   ./run_weekly.sh --force    run now regardless
#   ./run_weekly.sh --refresh  extra flags are passed through to weekly.py
set -u

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOG="$DIR/weekly.log"

FORCE=0
EXTRA=""
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) EXTRA="$EXTRA $arg" ;;
    esac
done

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

DUE="--if-due"
[ "$FORCE" -eq 1 ] && DUE=""

{
    echo ""
    echo "===== $(date '+%a %d %b %Y %H:%M:%S %Z') ====="
} >> "$LOG"

cd "$DIR" || exit 1
# shellcheck disable=SC2086 # EXTRA is intentionally word-split
"$PY" weekly.py $DUE $EXTRA >> "$LOG" 2>&1
STATUS=$?
echo "----- exit $STATUS -----" >> "$LOG"

# In a terminal, show the result. Under cron, stay quiet: the log is the record.
if [ -t 1 ]; then
    tail -n 30 "$LOG"
fi
exit "$STATUS"
