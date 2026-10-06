#!/usr/bin/env bash
# Install / update the car-km service on a Raspberry Pi (Raspberry Pi OS / Debian).
# Run from the car-km directory:  ./install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

echo "→ python venv + deps"
sudo apt-get install -y -q python3-venv >/dev/null
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
mkdir -p "$DIR/data/firmware"

echo "→ systemd unit"
sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$RUN_USER|g" "$DIR/car-km.service" | sudo tee /etc/systemd/system/car-km.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now car-km.service
sleep 1
sudo systemctl --no-pager --lines=5 status car-km.service || true

echo "→ nightly backup (03:15) to data/backups/"
mkdir -p "$DIR/data/backups"
CRON_LINE="15 3 * * * sqlite3 $DIR/data/carkm.db \".backup '$DIR/data/backups/carkm-\$(date +\\%F).db'\" && find $DIR/data/backups -name 'carkm-*.db' -mtime +60 -delete"
( crontab -l 2>/dev/null | grep -v 'carkm.db' ; echo "$CRON_LINE" ) | crontab -
sudo apt-get install -y -q sqlite3 >/dev/null

TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
TS_NAME="$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
echo
echo "Done. Open from any phone with Tailscale:"
[ -n "$TS_NAME" ] && echo "   http://$TS_NAME:8080"
[ -n "$TS_IP" ]   && echo "   http://$TS_IP:8080"
echo "On the LAN:    http://$(hostname -I | awk '{print $1}'):8080"
echo
echo "Device token (for the ESP32 build): $(cat "$DIR/data/device_token" 2>/dev/null || echo '(created on first start — check Settings in the app)')"
