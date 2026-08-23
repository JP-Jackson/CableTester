#!/usr/bin/env bash
# Probe whether the two-port ethernet method works on this hardware.
#
#   ./deploy/eth-probe.sh [IF_A] [IF_B]        (defaults: eth0 eth1)
#
# Run a patch cable from one port to the other. This walks the link speeds,
# forcing BOTH ends at each rung, and reports what actually negotiated.
#
# It answers three questions the ethernet design rests on:
#   1. Does link come up between the two ports over the cable?
#   2. Does forcing a speed actually take on both chips?
#   3. Does the link honestly go DOWN when the cable is unplugged?
#
# Question 3 matters most. A test that passes with no cable in it is worse
# than no test, so run this once with the cable in and once without.
#
# Nothing here is part of the tester. It is a hardware probe, and it will be
# deleted or absorbed once the ethernet design is settled.

set -uo pipefail

A="${1:-eth0}"
B="${2:-eth1}"

say()  { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m    WARNING: %s\033[0m\n' "$*"; }

for IF in "$A" "$B"; do
  if ! ip link show "$IF" >/dev/null 2>&1; then
    echo "eth-probe: no interface named '$IF'. Run 'ip -brief link' to see what exists." >&2
    exit 1
  fi
  # Refuse to knock out the box's own networking. Forcing an interface through
  # three speed changes drops its link each time, and doing that to the route
  # you arrived on ends the session mid-test.
  if ip route show default dev "$IF" 2>/dev/null | grep -q .; then
    echo "eth-probe: '$IF' carries the default route. Refusing to touch it." >&2
    echo "This box would lose its network part way through the test." >&2
    exit 1
  fi
done

say "Interfaces"
for IF in "$A" "$B"; do
  DRV="$(ethtool -i "$IF" 2>/dev/null | awk -F': ' '/^driver/{print $2}')"
  MAC="$(cat "/sys/class/net/$IF/address" 2>/dev/null)"
  info "$IF  driver=${DRV:-unknown}  mac=${MAC:-unknown}"
done

say "Autonegotiated result"
sudo ip link set "$A" up; sudo ip link set "$B" up
for IF in "$A" "$B"; do sudo ethtool -s "$IF" autoneg on 2>/dev/null; done
sleep 5
for IF in "$A" "$B"; do
  info "$IF  $(ethtool "$IF" 2>/dev/null | grep -iE 'speed|duplex|link detected' | tr -d '\t' | paste -sd'  ')"
done

say "Cable test (time domain reflectometry)"
for IF in "$A" "$B"; do
  OUT="$(sudo ethtool --cable-test "$IF" 2>&1)"
  info "$IF: $(echo "$OUT" | head -2 | paste -sd' ')"
done

say "Speed ladder, both ends forced"
printf '    %-8s %-10s %-12s %s\n' "SPEED" "LINK" "NEGOTIATED" "DUPLEX"
for S in 10 100 1000; do
  for IF in "$A" "$B"; do
    sudo ethtool -s "$IF" speed "$S" duplex full autoneg off 2>/dev/null
  done
  sleep 5
  LINK="$(ethtool "$A" 2>/dev/null | awk -F': ' '/Link detected/{print $2}')"
  GOT="$(ethtool  "$A" 2>/dev/null | awk -F': ' '/Speed/{print $2}')"
  DUP="$(ethtool  "$A" 2>/dev/null | awk -F': ' '/Duplex/{print $2}')"
  printf '    %-8s %-10s %-12s %s\n' "${S}Mb" "${LINK:-?}" "${GOT:-?}" "${DUP:-?}"
done

say "Restoring autonegotiation"
for IF in "$A" "$B"; do sudo ethtool -s "$IF" autoneg on 2>/dev/null; done
sleep 3
info "$A  $(ethtool "$A" 2>/dev/null | grep -iE 'speed|link detected' | tr -d '\t' | paste -sd'  ')"

cat <<'DONE'

    Read it like this:

      NEGOTIATED must match SPEED at every rung. If it does not, forcing is
      not taking on this chip and the speed-ladder design needs rethinking.

      DUPLEX must read Full. Half duplex means one end fell back to parallel
      detection instead of accepting the forced setting.

    NOW RUN IT AGAIN WITH THE CABLE UNPLUGGED.

    Every rung must report LINK = no. If any rung still says yes with no cable
    in it, the test can pass on nothing, and nothing built on top of it can be
    trusted.
DONE
