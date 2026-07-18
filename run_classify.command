#!/bin/bash
# ThreadSieve - double-click launcher for path 1 (no typing).
# Activates local venv and runs the classify + markdown + unsave.json step.

cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
  echo "[ERROR] .venv not found. Run setup first:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  read -p "Press enter to close..."
  exit 1
fi

source ".venv/bin/activate"
python scripts/import_bookmarks_to_markdown.py
EXITCODE=$?

echo ""
if [ $EXITCODE -ne 0 ]; then
  echo "[FAILED] exit code $EXITCODE"
else
  echo "[DONE] classify finished."
fi
read -p "Press enter to close..."
exit $EXITCODE
