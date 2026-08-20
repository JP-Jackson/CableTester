#!/usr/bin/env bash
# Launch Chromium full-screen on the tester UI, for a Pi with an attached
# screen. The server keeps serving the network at the same time, so a phone or
# laptop can watch the same test.
#
# Autostart on Raspberry Pi OS with a desktop session:
#   mkdir -p ~/.config/autostart
#   cat > ~/.config/autostart/cabletester-kiosk.desktop <<'DESKTOP'
#   [Desktop Entry]
#   Type=Application
#   Name=Cable Tester Kiosk
#   Exec=/home/pi/cabletester/deploy/kiosk.sh
#   DESKTOP

set -euo pipefail

URL="${CABLETESTER_URL:-http://localhost:5000/}"
PROFILE_DIR="${CABLETESTER_KIOSK_PROFILE:-$HOME/.cache/cabletester-kiosk}"

# Pick whichever Chromium this image ships.
BROWSER=""
for candidate in chromium-browser chromium google-chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER="$candidate"
    break
  fi
done
if [ -z "$BROWSER" ]; then
  echo "kiosk.sh: no chromium binary found (tried chromium-browser, chromium, google-chrome)" >&2
  exit 1
fi

# Wait for the server to answer before opening the window, so the kiosk does
# not land on an error page during boot.
echo "kiosk.sh: waiting for $URL"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Stop the screen blanking mid-test; harmless if X tools are absent.
xset s off      2>/dev/null || true
xset -dpms      2>/dev/null || true
xset s noblank  2>/dev/null || true

# Clear the "didn't shut down cleanly" bubble left by a power-cut bench box.
PREFS="$PROFILE_DIR/Default/Preferences"
if [ -f "$PREFS" ]; then
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' \
    "$PREFS" 2>/dev/null || true
fi

exec "$BROWSER" \
  --kiosk \
  --user-data-dir="$PROFILE_DIR" \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  "$URL"
