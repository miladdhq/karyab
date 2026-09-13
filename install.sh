#!/usr/bin/env bash
# One-shot setup for a fresh machine. Safe to re-run.
#
#   git clone <repo> ~/karyab && cd ~/karyab && ./install.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# The system SOCKS proxy common on Iranian machines breaks pip, Playwright and
# karlancer.com alike. Drop it for this script only.
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/5  Python"
if ! command -v python3 >/dev/null; then
  echo "python3 is not installed. On Ubuntu: sudo apt install python3 python3-venv" >&2
  exit 1
fi
python3 - <<'PY' || { echo "karyab needs Python 3.12 or newer." >&2; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY
echo "  $(python3 --version)"

say "2/5  Virtual environment and packages"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check -e . \
  httpx pytest playwright "fastapi" "uvicorn[standard]" anthropic
echo "  installed"

say "3/5  A browser for the login"
if command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null; then
  echo "  Google Chrome found — karyab will use it."
else
  echo "  Chrome not found; downloading Playwright's Chromium (~150 MB)…"
  .venv/bin/python -m playwright install chromium
  # Tell karyab to use the downloaded browser instead of the chrome channel.
  sed -i 's|^BROWSER_CHANNEL = "chrome"|BROWSER_CHANNEL = None|' karyab/browser/session.py
fi

say "4/5  Tests"
.venv/bin/python -m pytest -q 2>&1 | tail -1

say "5/5  Background service"
./karyab-service install

cat <<'EOF'

Done. Three first-time steps remain, in order:

  .venv/bin/karyab profile <your profile URL>   # e.g. https://www.karlancer.com/profile/12345
  .venv/bin/karyab init                          # builds your config from your own history
  .venv/bin/karyab login                         # a browser opens; log in to Karlancer once

Then open http://127.0.0.1:8765 — it stays running and restarts itself.
See RUNBOOK.md for everything else.
EOF
