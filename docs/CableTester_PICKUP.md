# CableTester: Session Pickup

**Snapshot of current state, not a history.** Rewritten whole every handover.
Last written: Monday, 8/24/2026. Running version: **1.4.0**.

## Read these first, in this order

1. `CLAUDE.md` in the repo root. The em dash rule, the date format, the rule
   that the UI never describes the past, and the handover checklist.
2. This file.
3. `docs/CableTester_DOC.md` §12 (open questions) and §15 (maintenance rules).
   §15 is twenty rules that each cost something.
4. `docs/CableTester_SD_SETUP.md` if you are touching the Pi, and
   `docs/CableTester_ENCLOSURE.md` if you are touching the case.

## What this is

A bench instrument that grades cables. Serial (DB9 RS-232, via a loopback plug)
and ethernet (a link-speed ladder between two real interfaces). It runs on a
Raspberry Pi 4 in a Harbor Freight Apache 2800 case with a 7 inch 1024x600
touchscreen, in kiosk mode, with no network at the bench by design.

The problem it exists for: cables that are wired correctly and fail anyway.
Every static continuity check passes them. That is why there is a baud sweep,
a speed ladder, and a continuity monitor you flex the cable during.

## THE BLOCKER

**No bad cable has ever been tested, on either protocol.** Everything else on
this list is secondary to that sentence.

The instrument has been run on hardware. The ethernet ladder scored a real
cable 100 and green in 10.7 seconds and correctly showed the link down when the
cable was pulled. The continuity monitor's sample rate was measured on the kit
at 1,251 to 1,314 samples/s. **Every one of those runs used a good cable.** An
instrument earns its keep by correctly failing bad cables and nobody has seen
this one do it.

**The serial side has never met a cable at all.** It is the reason the project
exists and it is the least validated part of it. `LINE_SETTLE_S = 120 ms` is a
guess made without hardware.

Do not let a new feature displace this again. It has been displaced twice.

## Next steps, in priority order

**0. Run a known-bad cable through both ladders.** Cut one conductor of the
blue pair on a spare ethernet lead. Expect 62 and amber, and the verdict naming
"4-5 and 7-8 (blue and brown)". An afternoon at most, and it is the difference
between a demo and an instrument.

**1. Do DOC §14, the serial bench validation.** Needs a DB9 loopback plug
(2 to 3, 7 to 8, 4 to 1 to 6), a USB-serial adapter, a known-good cable and a
known-bad one. Tune `LINE_SETTLE_S` and record the value per adapter type.
Record the results as a session log entry and correct §5 and §12 with anything
the hardware disproves.

**2. Exercise continuity on a real flexed cable.** The rate is measured; the
detection is not. Nobody has yet flexed a cable with a broken conductor in
front of it.

**3. Pin the USB-serial adapter with a udev rule, before the case is closed.**
`/dev/ttyUSB0` is assigned in enumeration order. One hub glitch and the captive
adapter comes back as `ttyUSB1` while the tester keeps looking at `ttyUSB0`,
which presents as a sealed instrument spontaneously losing its adapter. The
rule belongs in `deploy/` and should be installed by `setup-pi.sh`.
See DOC §12 for the full three-part note on the port label.

**4. Baseline the kit through its own panel connectors** before it tests a
single field cable. Panel-mount RJ45s add two mated pairs and two pigtails in
series with the cable under test. RS-232 will not notice; **gigabit will**, and
the ladder's top rung is exactly where it shows up, so a kit with poor internal
cabling fails good cables and blames them.

**5. The clock question, JP's decision.** The Pi has no battery-backed RTC and
the bench has no network, so every timestamp it writes is wrong and drifts with
each power cycle. Three options: a DS3231 on the GPIO header (a few dollars,
well supported on Trixie, and the header is otherwise unused), accept it and
say so on the report, or have the tester refuse to stamp a time it does not
trust. **Do not pick one without JP.**

**6. The help section.** Asked for on 8/23/2026, never built. Now the oldest
outstanding request.

**7. On-screen keyboard decision.** `wvkbd` is installed by `setup-pi.sh` and
has never been tested on field focus. This may be moot: the cable ID is the
only field on the panel that requires typing.

**8. Tailscale on the bench box.** Agreed in principle, deferred by JP. Buys
remote support at his desk, nothing at the bench, since Tailscale needs an
internet route and the bench has none.

## Known gotchas

- **The Pi's clone tracks `claude/sd-card-raspberry-pi-jmub6p`.** Deleting that
  branch breaks `git pull` on the bench box. Re-point the clone first.
- **`cabletester-mode` on the Pi is a symlink into the repo, not a copy.** That
  is deliberate: a copy meant `git pull` updated the repo and left a stale
  script on PATH, so a newly added command simply did not exist and the failure
  looked like the feature not working.
- **A shell variable cannot reach a systemd-started service.** Setting
  `CABLETESTER_URL=... cabletester-mode restart` does nothing. Use
  `cabletester-mode url`, which writes the state file the unit reads.
- **Check IPv4 explicitly on the Pi.** It can associate to WiFi, answer SSH and
  report `connected` while holding no IPv4 address at all. `ip -4 addr show
  wlan0` printing nothing is the tell. The kit is on a static `192.168.1.240/24`
  because a NetworkManager profile name with a leading space never leased.
- **Never force an ethernet speed.** 1000BASE-T requires autonegotiation;
  forcing it is silently downgraded to 100 and looks like a bug in your code.
  Restrict the advertisement mask instead, on both ends.
- **Gate any speed or duplex read on carrier first.** With the link down,
  `ethtool` echoes the configured value and it reads exactly like a
  measurement.
- **Read modem lines with one ioctl.** Three `getattr` reads are three syscalls
  at three instants, and a dropout can fall in the seam between them.
- **The panel is 1024x600 and nothing on it may scroll.** If a screen does not
  fit, split it or move something to Setup.
- **`StartLimitIntervalSec` and `StartLimitBurst` go in `[Unit]`,** not
  `[Service]`. They moved in systemd v229 and are silently ignored in the wrong
  section.
- **The kiosk failing to start after a reboot was seen once and never
  root-caused.** Diagnostics were never captured. Suspects are the
  `CapabilityBoundingSet` on the service and the five-starts-in-120s limit. If
  it recurs, capture `systemctl --user status cabletester-kiosk` before
  restarting anything.

## Never built, and open

- Help section (requested).
- Ethernet export and printable report. Serial has both; ethernet has neither.
- Sweep settings for ethernet. The four named settings are serial only.
- Performance-baseline profiles, the thing worth building in place of the
  removed learned wiring profiles: store a trusted cable's sweep results so the
  verdict can say "12 points below your reference, and it loses 57600 where the
  reference holds it". A statement about quality rather than wiring, and what
  "known-good" implies to everyone who reads it. **Not requested. Do not build
  without JP.**
- Merge to `main`: not decided. See the branch gotcha above.

## Parked, do not build without JP raising it

Totalflow protocol support of any kind, testing more than one cable at once,
a results database, cloud sync.

## Commands

```bash
# Tests
.venv/bin/python -m unittest discover -s tests -t .

# Run locally against the simulator
.venv/bin/python run.py --simulate

# Em dash check, before calling any writing task done
grep -rn "—" --include="*.py" --include="*.js" --include="*.css" --include="*.html" \
  --include="*.svg" --include="*.md" --include="*.sh" --include="*.service" . | grep -v "^./.git"

# On the Pi
cd ~/CableTester && git pull && cabletester-mode restart
cabletester-mode status
cabletester-mode logs
```
