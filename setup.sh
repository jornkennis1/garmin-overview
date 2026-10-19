#!/usr/bin/env bash
# One-time setup on macOS / Linux. Run from the project folder:  ./setup.sh
# Safe to run again: steps that are already done are skipped or asked about.
set -euo pipefail
cd "$(dirname "$0")"

ask() { read -r -p "$1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[yYjJ] ]]; }
step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }

step "Checking Python"
PY=""
for c in python3.14 python3.13 python3.12 python3 python; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.12 or newer is required (macOS: 'brew install python', or https://www.python.org/downloads/)." >&2
  exit 1
fi
echo "Found $("$PY" --version)"

step "Installing packages into .venv"
[[ -x .venv/bin/python ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo "Packages installed."

step "Personal settings"
if [[ ! -f settings.toml ]]; then
  cp settings.example.toml settings.toml
  echo "Created settings.toml (HRmax, resting HR, tagging keywords, ...). Everything is optional; the defaults work."
else
  echo "settings.toml already exists, leaving it alone."
fi

step "Garmin login"
echo "You'll be asked for your Garmin email and password (unless you filled in .env)."
echo "The password is only sent to Garmin; just the login tokens are kept, in ~/.garminconnect."
echo "If you use two-step verification, Garmin sends you a code to type in."
.venv/bin/python -m garmin_sync.auth

step "First sync"
if ask "Fetch the last 30 days now (a few minutes)?"; then
  since=$(.venv/bin/python -c 'import datetime as d; print(d.date.today() - d.timedelta(days=30))')
  .venv/bin/python -m garmin_sync.sync --since "$since" || true
  echo "Later, run '.venv/bin/python -m garmin_sync.sync' to fetch your full history (can take hours;"
  echo "stop with Ctrl+C any time, the next run resumes)."
fi

step "Claude Desktop (optional)"
if ask "Connect your training data to the Claude Desktop app (read-only)?"; then
  .venv/bin/python claude_desktop_setup.py --install
fi

step "Done"
echo "Open the dashboard:  .venv/bin/python -m streamlit run app/Dashboard.py"
