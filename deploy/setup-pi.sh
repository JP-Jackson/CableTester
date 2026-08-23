#!/usr/bin/env bash
# Turn a fresh Raspberry Pi OS install into the cable tester bench box.
#
#   cd ~/cabletester
#   ./deploy/setup-pi.sh
#
# Safe to re-run. Every step checks before it acts, so running it again after
# updating the code is the supported way to apply changes.
#
# Written for Raspberry Pi OS (64-bit, desktop) on a Pi 4. It does not assume
# a display stack: Trixie runs labwc on Wayland, Bookworm may run either, and
# the pieces that differ are routed through raspi-config, which handles both.

set -euo pipefail

# ------------------------------------------------------------------ context

CT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CT_USER="${SUDO_USER:-$(id -un)}"
CT_HOME="$(getent passwd "$CT_USER" | cut -d: -f6)"

say()  { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m    WARNING: %s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ] && [ -z "${SUDO_USER:-}" ]; then
  echo "setup-pi.sh: run as your normal user, not as root. It will sudo where needed." >&2
  exit 1
fi

# Running this straight off a USB stick would install the service with its
# WorkingDirectory on removable media, and the tester would die the moment the
# stick came out. Catch that here rather than three reboots later.
case "$CT_DIR" in
  /media/*|/mnt/*|/run/media/*)
    echo "setup-pi.sh: this copy lives on removable media ($CT_DIR)." >&2
    echo "Copy it to the Pi's own disk first, then run it from there:" >&2
    echo "    cp -r \"$CT_DIR\" ~/cabletester && cd ~/cabletester && ./deploy/setup-pi.sh" >&2
    exit 1
    ;;
esac

say "Cable Tester bench box setup"
info "user:      $CT_USER"
info "home:      $CT_HOME"
info "install:   $CT_DIR"
info "model:     $(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo 'unknown')"

# ------------------------------------------------------------------ packages

say "Installing packages"
sudo apt-get update -qq

# Chromium is 'chromium-browser' on Raspberry Pi OS and 'chromium' on plain
# Debian. Ask apt which one exists rather than guessing.
CHROMIUM_PKG=""
for pkg in chromium-browser chromium; do
  if apt-cache show "$pkg" >/dev/null 2>&1; then CHROMIUM_PKG="$pkg"; break; fi
done
if [ -z "$CHROMIUM_PKG" ]; then
  warn "no chromium package found in apt. The kiosk will not work until one is installed."
fi

sudo apt-get install -y -qq python3-venv python3-pip curl git unclutter ${CHROMIUM_PKG:-}
info "installed: python3-venv python3-pip curl git unclutter ${CHROMIUM_PKG:-(no chromium)}"

# On-screen keyboard. The UI has three fields a tech has to type into (cable
# ID, payload seconds, and the profile name prompt), and a bare touchscreen
# cannot fill them. Which keyboard works depends on the display stack, so try
# the Wayland-native ones first and fall back to the X11 ones.
say "Installing an on-screen keyboard"
OSK_PKG=""
for pkg in wvkbd squeekboard onboard matchbox-keyboard; do
  if apt-cache show "$pkg" >/dev/null 2>&1; then
    if sudo apt-get install -y -qq "$pkg" 2>/dev/null; then OSK_PKG="$pkg"; break; fi
  fi
done
if [ -n "$OSK_PKG" ]; then
  info "installed: $OSK_PKG"
  warn "Auto-popping a keyboard when a web field is focused is NOT reliable with"
  warn "Chromium on Linux, on either display stack. This is installed so you have"
  warn "one available, but treat the physical keyboard in the case as the"
  warn "dependable way to enter a cable ID until you have tested this on the panel."
else
  warn "no on-screen keyboard package available. Use the physical keyboard."
fi

# ------------------------------------------------------------------ serial

say "Granting serial port access"
if id -nG "$CT_USER" | tr ' ' '\n' | grep -qx dialout; then
  info "$CT_USER is already in the dialout group"
else
  sudo usermod -aG dialout "$CT_USER"
  info "added $CT_USER to dialout. This needs a reboot (or a fresh login) to apply."
fi

# ------------------------------------------------------------------ venv

say "Building the Python environment"
if [ ! -x "$CT_DIR/.venv/bin/python" ]; then
  python3 -m venv "$CT_DIR/.venv"
  info "created $CT_DIR/.venv"
fi
"$CT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$CT_DIR/.venv/bin/pip" install --quiet -r "$CT_DIR/requirements.txt"
info "installed: $(tr '\n' ' ' < "$CT_DIR/requirements.txt")"

# ------------------------------------------------------------------ server

say "Installing the tester service"
sed -e "s|__CT_USER__|$CT_USER|g" \
    -e "s|__CT_HOME__|$CT_HOME|g" \
    -e "s|__CT_DIR__|$CT_DIR|g" \
    "$CT_DIR/deploy/cabletester.service" \
  | sudo tee /etc/systemd/system/cabletester.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now cabletester.service
info "cabletester.service enabled and started"

# ------------------------------------------------------------------ kiosk

say "Installing the kiosk"
install -d "$CT_HOME/.config/systemd/user"
sed -e "s|__CT_DIR__|$CT_DIR|g" \
    "$CT_DIR/deploy/cabletester-kiosk.service" \
  > "$CT_HOME/.config/systemd/user/cabletester-kiosk.service"
systemctl --user daemon-reload 2>/dev/null || true

# A SYMLINK, not a copy. Copying it meant `git pull` updated the repo and left
# a stale script on PATH, so a command added upstream simply did not exist and
# the failure looked like the feature not working. Linking makes a pull enough.
sudo ln -sfn "$CT_DIR/deploy/cabletester-mode" /usr/local/bin/cabletester-mode
info "linked /usr/local/bin/cabletester-mode -> $CT_DIR/deploy/cabletester-mode"

# The autostart entry is what ties the kiosk to the graphical session. It runs
# 'cabletester-mode boot', which consults the saved mode, so choosing the
# desktop survives a power cycle instead of being undone at every login.
install -d "$CT_HOME/.config/autostart"
cat > "$CT_HOME/.config/autostart/cabletester-kiosk.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cable Tester Kiosk
Comment=Locks the panel to the tester UI. Switch with: cabletester-mode desk
Exec=/usr/local/bin/cabletester-mode boot
X-GNOME-Autostart-enabled=true
DESKTOP
info "installed the autostart entry"

# ------------------------------------------------------------- desktop tweaks

say "Configuring the desktop for bench use"

# Boot straight to the desktop with no login prompt. A tech opening the case
# should meet the instrument, not a password field.
if sudo raspi-config nonint do_boot_behaviour B4 2>/dev/null; then
  info "boot: desktop, autologin"
else
  warn "could not set autologin via raspi-config. Set it by hand:"
  warn "  sudo raspi-config > System Options > Boot / Auto Login > Desktop Autologin"
fi

# Screen blanking off. This is routed through raspi-config on purpose: the
# 'xset s off' that every forum post recommends is an X11 tool and does
# nothing at all under labwc on Wayland, silently. A panel that blanks part
# way through a baud sweep is the bug this prevents.
if sudo raspi-config nonint do_blanking 1 2>/dev/null; then
  info "screen blanking: disabled"
else
  warn "could not disable screen blanking via raspi-config. Set it by hand:"
  warn "  sudo raspi-config > Display Options > Screen Blanking > No"
fi

# SSH is how you get in to work on this once it is in the case. The Imager
# should have enabled it already; this is the belt to that braces.
if sudo raspi-config nonint do_ssh 0 2>/dev/null; then
  info "ssh: enabled"
else
  warn "could not enable ssh via raspi-config. Check 'sudo systemctl status ssh'."
fi

# ------------------------------------------------------------------ power

say "Checking power"
# Undervoltage matters more on this box than on most. A browning-out Pi
# produces timing errors on the serial line that are indistinguishable, on
# screen, from a genuinely marginal cable. Catching it here is much cheaper
# than diagnosing it from a confusing sweep result.
if command -v vcgencmd >/dev/null 2>&1; then
  THROTTLED="$(vcgencmd get_throttled 2>/dev/null || echo 'throttled=unknown')"
  info "$THROTTLED"
  if [ "$THROTTLED" != "throttled=0x0" ] && [ "$THROTTLED" != "throttled=unknown" ]; then
    warn "This Pi has recorded undervoltage or throttling."
    warn "Use a 5V 3A USB-C supply, and power the panel from its OWN supply."
    warn "On this instrument an underpowered Pi looks exactly like a marginal cable."
  fi
else
  info "vcgencmd not available, skipping the power check"
fi

# ------------------------------------------------------------------ done

say "Done"
cat <<DONE
    The tester is running now:   http://localhost:5000/
    From another machine:        http://$(hostname).local:5000/

    Reboot to get the kiosk:     sudo reboot

    After that:
      cabletester-mode status    what is running
      cabletester-mode desk      drop the panel to the desktop to work on it
      cabletester-mode kiosk     lock it back to the tester
      cabletester-mode logs      follow the kiosk's output

    The server runs in both modes and stays reachable over the network, so
    SSH in over WiFi any time without disturbing what the panel is showing.

    If the panel comes up at the wrong resolution, see the display section of
    docs/CableTester_SD_SETUP.md before changing anything else.
DONE
