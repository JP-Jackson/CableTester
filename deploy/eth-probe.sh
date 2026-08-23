#!/usr/bin/env bash
# Probe whether the two-port ethernet method works on this hardware.
#
#   ./deploy/eth-probe.sh [IF_A] [IF_B]        (defaults: eth0 eth1)
#
# Run a patch cable from one port to the other, then run it again with the
# cable out. LINK is the signal. See the notes at the bottom of the output.
#
# Nothing here is part of the tester. It is a hardware probe, and it will be
# deleted or absorbed once the ethernet design is settled.

set -uo pipefail

A="${1:-eth0}"
B="${2:-eth1}"

# Autonegotiation advertisement masks. NOT `speed N autoneg off`.
#
# 1000BASE-T *requires* autonegotiation: the standard uses it to settle which
# end is master and which is slave for clock recovery, so there is no such
# thing as a forced gigabit link. Asking for `speed 1000 autoneg off` is
# silently downgraded, and the first version of this script duly reported
# "1000Mb -> 100Mb/s" and looked like a driver bug.
#
# Restricting what is ADVERTISED gets the same diagnostic honestly: offer only
# one speed, and the link either comes up at it or does not come up at all.
#   0x002 10baseT/Full   0x008 100baseT/Full   0x020 1000baseT/Full
RUNGS=("10:0x002" "100:0x008" "1000:0x020")
ALL="0x03f"

say()  { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }

for IF in "$A" "$B"; do
  if ! ip link show "$IF" >/dev/null 2>&1; then
    echo "eth-probe: no interface named '$IF'. Run 'ip -brief link' to see what exists." >&2
    exit 1
  fi
  if ip route show default dev "$IF" 2>/dev/null | grep -q .; then
    echo "eth-probe: '$IF' carries the default route. Refusing to touch it." >&2
    exit 1
  fi
done

# Speed and Duplex are only meaningful while the link is UP. With the link
# down, ethtool echoes back whatever was last configured, which reads as a
# real negotiated result and is not one. This is why the unplugged run of the
# previous version appeared to negotiate 10Mb and 100Mb with no cable in it.
report() {
  local IF="$1" LINK GOT DUP
  LINK="$(ethtool "$IF" 2>/dev/null | awk -F': ' '/Link detected/{print $2}')"
  if [ "$LINK" = "yes" ]; then
    GOT="$(ethtool "$IF" 2>/dev/null | awk -F': ' '/Speed/{print $2}')"
    DUP="$(ethtool "$IF" 2>/dev/null | awk -F': ' '/Duplex/{print $2}')"
  else
    GOT="--"; DUP="--"
  fi
  printf '%s|%s|%s' "${LINK:-?}" "$GOT" "$DUP"
}

# Gigabit autonegotiation is not instant. Poll rather than guessing a sleep.
settle() {
  local i
  for i in $(seq 1 12); do
    [ "$(ethtool "$A" 2>/dev/null | awk -F': ' '/Link detected/{print $2}')" = "yes" ] && return 0
    sleep 1
  done
  return 1
}

say "Interfaces"
for IF in "$A" "$B"; do
  info "$IF  driver=$(ethtool -i "$IF" 2>/dev/null | awk -F': ' '/^driver/{print $2}')  mac=$(cat "/sys/class/net/$IF/address" 2>/dev/null)"
done

sudo ip link set "$A" up; sudo ip link set "$B" up

say "Autonegotiated result (everything advertised)"
for IF in "$A" "$B"; do sudo ethtool -s "$IF" autoneg on advertise "$ALL" 2>/dev/null; done
settle
for IF in "$A" "$B"; do
  IFS='|' read -r L G D <<<"$(report "$IF")"
  info "$(printf '%-6s link=%-4s speed=%-10s duplex=%s' "$IF" "$L" "$G" "$D")"
done

say "Cable test (time domain reflectometry)"
for IF in "$A" "$B"; do
  info "$IF: $(sudo ethtool --cable-test "$IF" 2>&1 | head -1)"
done

say "Speed ladder, one speed advertised at a time"
printf '    %-9s %-7s %-11s %-8s %s\n' "OFFERED" "LINK" "NEGOTIATED" "DUPLEX" "PAIRS NEEDED"
for RUNG in "${RUNGS[@]}"; do
  S="${RUNG%%:*}"; M="${RUNG##*:}"
  for IF in "$A" "$B"; do sudo ethtool -s "$IF" autoneg on advertise "$M" 2>/dev/null; done
  settle
  IFS='|' read -r L G D <<<"$(report "$A")"
  case "$S" in
    1000) P="all four";;
    *)    P="1-2 and 3-6 only";;
  esac
  printf '    %-9s %-7s %-11s %-8s %s\n' "${S}Mb" "$L" "$G" "$D" "$P"
done

say "Restoring autonegotiation"
for IF in "$A" "$B"; do sudo ethtool -s "$IF" autoneg on advertise "$ALL" 2>/dev/null; done
settle
IFS='|' read -r L G D <<<"$(report "$A")"
info "$(printf '%-6s link=%-4s speed=%-10s duplex=%s' "$A" "$L" "$G" "$D")"

cat <<'DONE'

    LINK is the signal. Read nothing else when it says no.

      cable in  : every rung should link.
      cable out : every rung must NOT link.

    A rung that links with the cable out means the test can pass on nothing,
    and nothing built on top of it can be trusted.

    Which rungs link is the diagnosis:
      1000 fails, 100 passes -> pairs 4-5 and 7-8 are not carrying
      100 fails, 10 passes   -> marginal on 1-2 or 3-6
      nothing links          -> 1-2 or 3-6 is broken outright
DONE
