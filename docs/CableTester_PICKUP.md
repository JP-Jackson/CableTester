# CableTester: Session Pickup

**Snapshot of current state, not a history.** Rewritten whole every handover.
Last written: Monday, 8/24/2026. Running version: **1.5.0**.

## Read these first, in this order

1. `CLAUDE.md` in the repo root. The em dash rule, the date format, the rule
   that the UI never describes the past, and the handover checklist.
2. This file.
3. `docs/CableTester_DOC.md` §12 (open questions) and §15 (twenty-six
   maintenance rules, each of which cost something). §5e and §5f are new and
   are the test method's current state.
4. `docs/CableTester_SD_SETUP.md` §9 if you are touching the Pi, and
   `docs/CableTester_ENCLOSURE.md` if you are touching the case.

## What this is

A bench instrument that grades cables. Serial (DB9 RS-232, via a loopback plug)
and ethernet (a link-speed ladder plus a real data transfer between two
interfaces). It runs on a Raspberry Pi 4 in a Harbor Freight Apache 2800 case
with a 7 inch 1024x600 touchscreen, in kiosk mode, with no network at the bench
by design.

The problem it exists for: cables that are wired correctly and fail anyway.
Every static continuity check passes them.

## THE BLOCKER

**No bad cable has ever been tested, on either protocol.** Everything below is
secondary to that sentence, and it has now survived five sessions.

The instrument runs on hardware and JP used it all evening on 8/24. Every run
used a good cable. An instrument earns its keep by correctly failing bad
cables, and nobody has seen this one do it.

Two things did get exercised against reality this session, and both found real
bugs, which is the argument for doing more of it: JP pulling the DB9 mid-test
exposed the flex test reading GOOD after a reconnect, and running the quick
setting on a real cable exposed the scoring bug that capped a flawless cable at
60. Neither was findable from a simulator.

**`LINE_SETTLE_S = 120 ms` is still a guess made without hardware.**

## Next steps, in priority order

**0. Run a known-bad cable through both protocols.** Cut one conductor of the
blue pair on a spare ethernet lead. Expect 62 and amber, and the verdict naming
"4-5 and 7-8 (blue and brown)". An afternoon at most, and it is the difference
between a demo and an instrument.

**1. Exercise the ethernet load test on the kit. It has never run.** The whole
`AF_PACKET` path in §5e is written from documentation and tested against a
fake. It needs `CAP_NET_RAW`, which the unit grants only after
`./deploy/setup-pi.sh` is re-run, because unit files are copies. Start from a
shell where the traceback is visible:
`sudo .venv/bin/python run.py --eth-load IFACE_A IFACE_B`.
This is the piece that answers the failing-download problem, and it is
completely unproven.

**2. Confirm which test JP's disconnect happened on.** He pulled the DB9
mid-test and the screen showed passed after reconnecting. The **flex test** is
fixed (the fault latches now). If it was the **baud sweep** or the **pin
check** that reported a pass after a reconnect, that is a different bug and it
has not been found. Ask before assuming it is closed.

**3. Do DOC §14, the serial bench validation.** A DB9 loopback plug
(2 to 3, 7 to 8, 4 to 1 to 6), a USB-serial adapter, a known-good cable and a
known-bad one. Tune `LINE_SETTLE_S` and record the value per adapter type.

**4. Measure the boot time.** `cabletester.service` wanted
`network-online.target`, which on a box with no network blocks until
NetworkManager gives up. That is fixed. `cabletester-mode status` now reports
firmware, server and panel times separately. Measure before deciding whether to
go further, which was JP's call. The bigger change (cage, no desktop at all) is
designed but not built, and it costs the fallback: five failed kiosk starts
currently leave the desktop visible, and under cage a failure is a black screen
on a sealed box.

**5. Baseline the kit through its own panel connectors** before it tests a
field cable. Panel-mount RJ45s add two mated pairs and two pigtails in series.
RS-232 will not notice; **gigabit will**, and the ladder's top rung is exactly
where it shows up, so a kit with poor internal cabling fails good cables and
blames them. The load test makes this measurable now.

**6. Pin the USB-serial adapter with a udev rule, before the case is closed.**
`/dev/ttyUSB0` is assigned in enumeration order. One hub glitch and the captive
adapter returns as `ttyUSB1`, which presents as a sealed instrument
spontaneously losing its adapter.

**7. The clock question, JP's decision.** No battery-backed RTC and no network,
so every timestamp is wrong and drifts with each power cycle. A DS3231 on the
otherwise unused GPIO header, accept it and say so on the report, or refuse to
stamp a time it does not trust. **Do not pick one without JP.**

**8. The help section.** Asked for on 8/23/2026, never built. The guided flow
and the wiring tabs have absorbed some of what it was for, so re-ask what it
should still cover before building it.

## Known gotchas

- **A syntax check is not a check.** Three bugs shipped in one session past
  `node --check` and a clean import. Render the page and read the stack. See
  DOC §15 rules 21 and 22.
- **Never verify a click by calling the handler.** `state.x = y; render()`
  exercises none of the event wiring, which is exactly where the dead-nav bug
  lived. Click the element.
- **A failed assertion in a multi-part patch writes nothing.** A script that
  edits a file in several steps and asserts between them leaves the file
  untouched when step two fails, while you believe step one landed. Verify
  after, do not assume.
- **The Pi's clone tracks `main`.** Sessions develop on a branch, fast-forward
  into `main` once tested, and the bench box pulls `main`. Command in
  SD_SETUP §9. The account is `jp@192.168.1.240`.
- **Unit files are copies, not symlinks.** `git pull` does not update them.
  Re-run `./deploy/setup-pi.sh` when anything under `deploy/` changes, which
  includes the `CAP_NET_RAW` grant the load test needs.
- **`cabletester-mode` on the Pi IS a symlink into the repo.** Deliberately: a
  copy meant a newly added command simply did not exist after a pull.
- **A shell variable cannot reach a systemd-started service.** Use
  `cabletester-mode url`, which writes the state file the unit reads.
- **Two interfaces on one host cannot be talked between over IP.** The kernel
  short-circuits through loopback and the cable is never touched. That is why
  the load test is raw layer 2.
- **Never force an ethernet speed.** 1000BASE-T requires autonegotiation.
  Restrict the advertisement mask instead, on both ends.
- **Gate any speed or duplex read on carrier first.** With the link down,
  `ethtool` echoes the configured value and it reads like a measurement.
- **Read modem lines with one ioctl.** Three `getattr` reads are three syscalls
  at three instants and a dropout can fall in the seam between them.
- **The panel is 1024x600 and nothing may scroll.** If a screen does not fit,
  split it or move something to Setup.
- **`pkill -f "run.py"` kills the calling shell** in the dev container and
  returns 144. Start test servers on a fresh port instead.
- **Chromium blocks some localhost ports** as unsafe and returns
  `ERR_UNSAFE_PORT`. Try a different `--port` before debugging the server.
- **Straight-through and null modem read identically** through a symmetric
  loopback, and **T568A and T568B cannot be told apart by anything**, because
  both are pin 1 to pin 1 through. Physics, not a limitation. The screens say
  so. Straight against crossover IS detectable and is reported.
- **`StartLimitIntervalSec` and `StartLimitBurst` go in `[Unit]`,** not
  `[Service]`, since systemd v229.

## Never built, and open

- Help section (requested 8/23, still open).
- Ethernet export and printable report. Serial has both; ethernet has neither,
  and the load test result is not on the report at all.
- Sweep settings for ethernet. The five named settings are serial only, and the
  load test duration is fixed at 10 seconds in the UI.
- The four serial panel mockups and the gauge mockup are published as
  Artifacts, not in the repo. They are a design record, not a deliverable.
- Performance-baseline profiles: store a trusted cable's sweep results so the
  verdict can say "12 points below your reference". **Not requested. Do not
  build without JP.**

## Parked, do not build without JP raising it

Totalflow protocol support of any kind, testing more than one cable at once,
a results database, cloud sync, rates above 115,200 (the XRC's local MMI port
tops out there, so the ladder's ceiling already matches it).

## Commands

```bash
# Tests
.venv/bin/python -m unittest discover -s tests -t .   # 127, no hardware needed

# Run locally against the simulator
.venv/bin/python run.py --simulate

# Ethernet, on real hardware only
sudo .venv/bin/python run.py --eth-test IFACE_A IFACE_B
sudo .venv/bin/python run.py --eth-load IFACE_A IFACE_B

# Update the bench box
ssh -t jp@192.168.1.240 'cd ~/cabletester && git pull \
  && sudo systemctl restart cabletester && cabletester-mode restart'
# add ./deploy/setup-pi.sh when anything under deploy/ changed

# Em dash check, before calling any writing task done
grep -rn "—" --include="*.py" --include="*.js" --include="*.css" --include="*.html" \
  --include="*.svg" --include="*.md" --include="*.sh" --include="*.service" . | grep -v "^./.git"
```

Simulated serial ports: `SIM-GOOD`, `SIM-MARGINAL`, `SIM-3WIRE`, `SIM-OPEN`
(pin 8 broken), `SIM-NOPLUG` (nothing fitted, exercises the continuity refusal).

**Secrets and environment variables:** none. The only one is
`CABLETESTER_PROFILES`. No authentication, no external service.
