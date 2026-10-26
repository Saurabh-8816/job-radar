#!/usr/bin/env bash
# Job Radar relay on an Oracle Cloud "Always Free" Ubuntu server in India.
#
# Copy this file to the server and run it once:
#   scp -i <ssh-key> tools/oracle_setup.sh ubuntu@<server-ip>:
#   ssh -i <ssh-key> ubuntu@<server-ip> "bash oracle_setup.sh"
#
# It installs Python, OCR (Hindi + English) and a headless browser, connects to your
# GitHub repo with a deploy key (you add it once in the browser when asked), checks
# which sources answer from this Indian IP, and runs the relay every 2 hours via cron.
# Safe to re-run.
set -euo pipefail

REPO_SSH="git@github.com:Saurabh-8816/job-radar.git"
DIR="$HOME/job-radar"
KEY="$HOME/.ssh/jobradar_deploy"

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

step "1/6  System packages (Python, git, OCR with Hindi)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-hin cron >/dev/null
sudo systemctl enable --now cron >/dev/null 2>&1 || true

# The 1 GB "Micro" shape needs swap for OCR + browser; harmless on bigger shapes.
if [ "$(free -m | awk '/^Mem:/{print $2}')" -lt 3000 ] && ! swapon --show | grep -q swapfile; then
  step "    Adding 2 GB swap (small server)"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

step "2/6  GitHub access (deploy key for this repository only)"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C "job-radar-oracle-relay" -f "$KEY" >/dev/null
grep -q "IdentityFile $KEY" "$HOME/.ssh/config" 2>/dev/null || cat >> "$HOME/.ssh/config" <<EOF
Host github.com
  IdentityFile $KEY
  IdentitiesOnly yes
EOF
chmod 600 "$HOME/.ssh/config"
ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null
sort -u -o "$HOME/.ssh/known_hosts" "$HOME/.ssh/known_hosts"

until ssh -o BatchMode=yes -T git@github.com 2>&1 | grep -q "successfully authenticated"; do
  echo
  echo "Add this key on GitHub:  your repo -> Settings -> Deploy keys -> Add deploy key"
  echo "   Title: oracle-relay      Key: (the line below)      [x] Allow write access"
  echo
  cat "$KEY.pub"
  echo
  read -r -p "Press Enter after adding it... " _
done
echo "GitHub access OK."

step "3/6  Code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --rebase --autostash; else git clone -q "$REPO_SSH" "$DIR"; fi
git -C "$DIR" config user.name "job-radar-oracle"
git -C "$DIR" config user.email "job-radar-oracle@users.noreply.github.com"

step "4/6  Python packages + headless browser (a few minutes)"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
sudo "$DIR/.venv/bin/python" -m playwright install-deps chromium >/dev/null
"$DIR/.venv/bin/python" -m playwright install chromium >/dev/null

step "5/6  Which sources answer from this Indian server?"
cd "$DIR"
.venv/bin/python - <<'PY'
from radar.fetch import fetch_many
from radar.relay import select_sources
src = select_sources()
res = fetch_many([s.url for s in src if not s.render], timeout=25, retries=1)
ok = [s for s in src if not s.render and res[s.url].ok]
bad = [s for s in src if not s.render and not res[s.url].ok]
print(f"{len(ok)}/{len(ok) + len(bad)} relay sources answered from this server.")
for s in bad:
    print(f"   x {s.name}: {res[s.url].error}")
PY

step "6/6  Schedule: relay every 2 hours"
LINE="20 */2 * * * cd $DIR && PYTHONUNBUFFERED=1 .venv/bin/python -m radar.main relay --push >> data/relay.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'radar.main relay' ; echo "$LINE" ) | crontab -
crontab -l | grep 'radar.main relay'

echo
echo "Done. First scheduled run at :20 past the next even hour (UTC). Run one now with:"
echo "   cd $DIR && .venv/bin/python -m radar.main relay --push"
echo "Log: $DIR/data/relay.log"
