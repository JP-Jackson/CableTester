#!/usr/bin/env bash
# Launch Chromium full screen on the tester UI, for a Pi with an attached
# panel. The server keeps serving the network at the same time, so a phone or
# laptop can watch the same test.
#
# Normally started by cabletester-kiosk.service, not run by hand. To control
# it, use 'cabletester-mode kiosk' and 'cabletester-mode desk'.
#
# Screen blanking is NOT handled here. Raspberry Pi OS Trixie runs labwc on
# Wayland, where the X11 'xset s off' does nothing at all and fails silently,
# which looks exactly like a screen that blanks mid-sweep for no reason.
# setup-pi.sh calls 'raspi-config nonint do_blanking 1' instead, which works
# on both stacks. Do not add xset calls back here.

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
# not land on an error page during boot. The server and the kiosk start at
# roughly the same moment and the server has a venv and Flask to load first.
echo "kiosk.sh: waiting for $URL"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Clear the "didn't shut down cleanly" bubble left by a power-cut bench box.
# A kit in a case gets its power yanked; without this the tech meets a dialog
# before they meet the instrument.
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
  --touch-events=enabled \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  "$URL"
