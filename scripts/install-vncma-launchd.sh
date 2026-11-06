#!/bin/zsh
# Install (or remove) the Mac's monthly VNCMA job: `python -m pipeline market monthly`.
#
#   scripts/install-vncma-launchd.sh            # install: day 3 of each month, 09:00
#   scripts/install-vncma-launchd.sh --remove   # uninstall
#   launchctl kickstart gui/$(id -u)/com.soivi.vncma-monthly   # run it now
#
# It runs on this Mac because vnstock is registered to this device. launchd runs a missed
# job when the Mac wakes up, but not if it was switched off. Output: logs/vncma-monthly.log.
set -euo pipefail

LABEL="com.soivi.vncma-monthly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  [[ -f "$PLIST" ]] && mv "$PLIST" "$PLIST.removed"
  echo "Removed $LABEL (old file kept as $PLIST.removed)"
  exit 0
fi

UV="$(command -v uv || true)"
if [[ -z "$UV" ]]; then
  echo "uv not found on PATH" >&2
  exit 1
fi
mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>python</string>
    <string>-m</string><string>pipeline</string><string>market</string><string>monthly</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Day</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$REPO/logs/vncma-monthly.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/vncma-monthly.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$UV"):/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $LABEL: day 3 of each month at 09:00 (log: $REPO/logs/vncma-monthly.log)"
echo "Run it now with: launchctl kickstart $DOMAIN/$LABEL"
