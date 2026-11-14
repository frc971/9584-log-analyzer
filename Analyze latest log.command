#!/bin/sh
# Double-click (Mac) to run the full report on the newest log in logs/ (and save its numbers).
# Same as typing:  python3 analyze.py
# First time only: right-click this file > Open, then Open, to get past the "unidentified developer"
# warning.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    python3 analyze.py "$@"
else
    python analyze.py "$@"
fi
echo
printf "Press Return to close this window. "
read -r _
