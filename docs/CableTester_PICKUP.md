# CableTester: Session Pickup Prompt

> **STYLE RULE, READ THIS BEFORE WRITING ANYTHING: NEVER USE EM DASHES.** Not in code, comments, commits, UI copy, or these docs. Grep your own new text before calling any writing task done. Full context: `CLAUDE.md` and DOC §15.

Read this file completely before doing anything. Then read the files listed under "Files to Read First."

**Last session:** 3 (Sunday, 8/23/2026). **Everything through session 3 is committed and pushed to `claude/sd-card-raspberry-pi-jmub6p`.**

---

## Read this first: one thing governs everything else

**The bench box is built and running. The instrument has still never been
connected to a real cable.** Every one of those 34 tests runs against
`tester/simulator.py`, which is a model of a cable written from the same
understanding that wrote the code being tested. That proves the logic is
self-consistent. It proves nothing about a real FTDI adapter, a real settle
time, or a real degraded cable.

As of session 3 the Pi 4 kit is provisioned: `setup-pi.sh` ran clean on the
first attempt, the service is up, the panel and its touch work, and the tester
answers on the network at `192.168.1.240:5000`. **What remains unproven is
everything about serial behaviour**, which is the part that matters most.

So:
- **Do not tell JP the tool "works" without qualifying it.** It works against a simulator.
- **`LINE_SETTLE_S = 120 ms` in `tester/serial_tests.py` is a guess.** It is the most likely thing to be wrong on real hardware. If a known-good cable shows spurious opens, that constant is the first suspect, not the cable.
- **On the Pi, check power before you check anything.** A browning-out Pi produces timing errors indistinguishable from a marginal cable. `cabletester-mode status` prints the throttling state for exactly this reason.
- **The bench validation plan is DOC §14.** It is still the highest-value next work and everything else is behind it.

---

## Project

- **Name:** CableTester
- **Purpose:** A bench instrument for verifying DB9 RS-232 cables used to connect laptops to ABB Totalflow XFC flow computers. Cables were failing in the field despite passing a continuity check, so this tests signal integrity at speed rather than DC continuity.
- **Scope boundary, hard:** bench testing one cable in isolation with a loopback plug. **No Totalflow protocol, ever, unless JP raises it.** No live XFC is contacted.
- **Stack:** Python 3.9+, `pyserial`, Flask, Server-Sent Events, plain HTML/CSS/JS with no build step. Fonts and icons are vendored locally, no CDN.
- **Project folder:** `/home/user/CableTester`. **Docs:** `docs/`.
- **GitHub repo:** `JP-Jackson/CableTester`. Session branch: `claude/sd-card-raspberry-pi-jmub6p`. Nothing has been merged to `main` yet and no PR has been opened. Ask JP before opening one.
- **Design system:** inherited from `JP-Jackson/Polk-Demo` (`portal.css`, `branding/`). If that repo's palette changes, this one should follow.

## The physical kit (decided session 3)

JP is assembling a portable tester in a **Harbor Freight Apache 2800** case.

| Part | What |
|------|------|
| Board | **Raspberry Pi 4 Model B**, which JP already owned. RAM not yet confirmed; he was going to run `free -h`. |
| Panel | **Head Sun 7 inch 1024x600 IPS**, HDMI video plus USB touch, five point capacitive. Driver free. |
| Card | **SanDisk Extreme 128 GB, U3/V30/A2.** Chosen over a PNY U1 because A2 rates random IOPS, which is what a Pi does. A sealed SanDisk Extreme PRO stays in the case as the known-good spare. |
| Address | **Static `192.168.1.240/24`, gateway `192.168.1.1`**, set with `nmtui`. WiFi DHCP would not hand this device an IPv4 lease. Static is the right end state anyway; a tech's URL should not move. |
| Clock | **No RTC.** `timedatectl` reports `RTC time: n/a`. See the open decision below. |
| OS | **Raspberry Pi OS 64-bit, plain desktop.** Debian 13 Trixie, kernel 6.18. Not Full, not Lite. |
| Serial | USB-serial adapter. **Never the GPIO header:** 3.3 V logic, not RS-232 levels, and a real cable destroys the Pi. |
| Keyboard | Small wireless keyboard in the case lid. See the open question below. |

**A Raspberry Pi 2 Model B was considered and set aside.** It is 32-bit only and
would struggle with Chromium on 1 GB. It is not the kit.

## Files to Read First

0. **`CLAUDE.md` first, not the docs.** It carries the rules that govern how you work here: the em dash rule, the date and time format, the "UI describes the instrument as it is" rule, the hardware reality check, and the end-of-session handover checklist. Any phrasing of "wrap up" runs that checklist.
1. **`docs/CableTester_DOC.md` §5 (Test Method) and §12 (Open Questions).** §5 is the specification for how a cable is graded and is the thing most likely to be changed carelessly. §12 is what is genuinely unresolved.
2. **`docs/CableTester_SD_SETUP.md`** if the work touches the Pi at all. Card to kit, in order.
3. **`docs/CableTester_ENCLOSURE.md`** if the work touches the physical kit. Case, deck, panel connectors, and why each choice was made.
4. `tester/serial_tests.py`: the entire serial layer. Nothing else in the codebase opens a port. `LINE_SETTLE_S`, `_grade_pins()`, `_expected_absent()` and `_transfer()` are the parts with real reasoning behind them.
5. **`tester/ethernet_tests.py`**: the whole ethernet layer, and the only module that touches a network interface. Every comment in it records a hardware finding that cost a probe run to learn.
6. `tester/scoring.py`: the credit table and the verdict wording for serial, and the outcome table for ethernet. Small and self-contained.
7. `tester/app.py`: Flask routes, the job runner, the SSE stream, `fmt_when()`, and the `--eth-test` CLI.
8. `tester/simulator.py` and `tester/eth_simulator.py`: the fake cables. Read these before trusting any test result, so you know what is actually being proven.
9. `deploy/setup-pi.sh` and `deploy/cabletester-mode`: the whole deployment, and the mode design.
10. `branding/brand-guide.md`, `static/app.js`, `static/style.css`: the front end.

## What Session 3 Shipped

DOC §10 carries the full reasoning. Short version:

- **`deploy/setup-pi.sh`**: one run turns a fresh Raspberry Pi OS install into the bench box. Idempotent, so re-running it is how a code update is applied. Reads the user and paths from the account it runs as, so nothing is hardcoded to `/home/pi`. Refuses to run from removable media.
- **`deploy/cabletester-mode`**: switches what the attached panel shows, `kiosk` or `desk`, and the choice survives a reboot. Also reports serial ports and the Pi's power state.
- **`deploy/cabletester-kiosk.service`**: the kiosk as a systemd user unit, started from the desktop autostart entry rather than `systemctl --user enable`.
- **`deploy/kiosk.sh` rewritten** for Wayland and touch, with the `xset` calls removed.
- **Fonts vendored into `static/fonts/`**, 178 KB. This reverses session 2's CDN decision, on the condition session 2 said it was waiting for.
- **`deploy/vendor-fonts.sh`** regenerates them, subsetting Tabler from 452 KB to 1 KB.
- **`docs/CableTester_SD_SETUP.md`**: the card-to-kit build guide.

## Pending Actions

In priority order.

1. **Run the bench validation in DOC §14.** This is now the only thing standing between the kit and a trustworthy instrument. Needs a loopback plug, a USB-serial adapter, a known-good cable and a known-bad one. Tune `LINE_SETTLE_S` and record the working value per adapter type. **Do it on the Pi**, since the Pi's USB stack is what the instrument actually runs on and it is not the same as a laptop's.
2. **Exercise `cabletester-mode desk` / `kiosk`.** The kiosk itself is confirmed to come up on boot unattended. The panel switch is installed and `status` reports correctly, but switching back and forth has not been tried.
3. **Decide the clock question.** A DS3231 RTC, or accept wrong timestamps, or refuse to stamp. DOC §12.
4. **Decide the on-screen keyboard question.** `wvkbd` is installed; whether it appears on field focus is untested. See below.
5. **Pin the USB-serial adapter to a stable device name.** `/dev/ttyUSB0` is assigned in enumeration order, so a re-enumeration or a second adapter renames it and the tester looks at the wrong node. On a sealed kit that presents as the instrument losing its adapter for no reason. A udev rule matching the adapter's serial number or VID:PID, installed by `setup-pi.sh`, fixes it. Do this before the case is closed. The port label in the UI changes with it, see DOC §12.
6. **Teach `setup-pi.sh` to prefer a local `wheels/` directory** when one is present, so the box can be rebuilt with no internet. JP already has `~/wheels` with the correct aarch64 wheels. Small change, real value for an offline bench.
7. **Tailscale**, agreed in principle and deferred. DOC §12.
8. **Decide on merging to `main`** and whether a PR is wanted.
9. **Get a technician who did not build this to read the verdict line** and say whether it means what it should.

## Open Decisions Waiting On JP

- **Remove learned known-good profiles.** JP proposed it, I agreed, the code is still in place. Reasoning in DOC §12. In short: its only interaction is typing a name, the instrument now has no keyboard, and the label implies a claim about quality that a wiring signature cannot make. `BUILTIN_PROFILES` and `identify()` stay; `ProfileStore` and its API go. Already gone from the `/preview` prototype.


- **On-screen keyboard.** The UI has three fields a tech must type into: cable ID, payload seconds, and the `window.prompt()` when naming a learned profile. `setup-pi.sh` installs a keyboard package, but **auto-popping one when a web field takes focus is not reliable with Chromium on Linux under either display stack, and this is untested.** The physical keyboard in the case lid is the current answer. The robust fix is an on-screen keyboard **inside the web app**, which works regardless of display stack. That is a change to the instrument, was flagged, and was deliberately not built.
- **Power source for the kit.** Not decided. The docs assume mains: a 5V 3A USB-C supply for the Pi and a **separate** supply for the panel. If it becomes battery powered, the undervoltage risk goes up sharply and this matters more than it sounds, see the power rule above.
- **Filesystem overlay for power-cut protection.** Techs will yank the power on a kit in a case, and SD corruption is the classic kiosk killer. An overlay would fix it but would make `profiles.json` non-persistent, silently breaking the learned-profile feature. Parked deliberately rather than applied quietly.

## Known Issues / Gotchas

- **`xset s off` does nothing on current Raspberry Pi OS, silently.** Trixie runs labwc on Wayland. Screen blanking goes through `raspi-config nonint do_blanking 1`. `kiosk.sh` carries a comment forbidding the xset calls being restored; do not restore them.
- **A systemd user unit started over SSH cannot find the display.** Chromium exits instantly and it reads as a crash loop. `cabletester-mode` runs `systemctl --user import-environment` first. Use it rather than `systemctl --user start`.
- **An underpowered Pi looks exactly like a marginal cable.** This is the most misleading failure mode the instrument has. `cabletester-mode status` prints `throttled=`; anything but `0x0` invalidates a bad result.
- **jsDelivr is blocked from this build environment (403), the npm registry is not.** `vendor-fonts.sh` pulls the Tabler tarball from npm. Relevant to any future asset fetch.
- **`document.fonts.check()` cannot detect a missing font.** Per spec it answers "can this text be rendered", and an unknown family falls back to a system font, so it returns true when nothing loaded. `checkIcons()` looks for the FontFace in `document.fonts` instead. Do not "simplify" it back. It is now a safety net for a corrupt local file rather than a blocked CDN, and it was kept on purpose.
- **Absurd throughput in the simulator** (megabits at 1200 baud) means `realtime=False` on that `FakeCable`, not a maths bug. The `SIM_*` cables set it true; bare `FakeCable()` in tests does not, so tests stay fast.
- **Chromium blocks some localhost ports** as unsafe (5060 is SIP, for instance) and returns `ERR_UNSAFE_PORT`. If a browser-driven check will not load the page, try a different `--port` before debugging the server.
- **`pkill -f "run.py"` in this environment kills the calling shell** and returns exit 144. Start test servers on a fresh port, or kill by port with `ss -lptn`.
- **"SSH works" does not mean "the network works".** A Pi can associate to WiFi, answer SSH and look healthy in the desktop while holding no IPv4 address at all, having taken only an IPv6 ULA by SLAAC. NetworkManager reports `connected` because one address family succeeded. But a `fd00::/8` address is not routable, so there is no internet, `apt` and `pip` fail, and `run.py` binding `0.0.0.0` means nothing on the network reaches the tester either. `ip -4 addr show wlan0` printing nothing is the tell. This cost most of a hardware session.
- **A shell variable cannot reach a systemd-started service.** `CABLETESTER_URL=... cabletester-mode restart` silently does nothing, which reads as the override being ignored rather than never arriving. The kiosk URL lives in a state file instead: `cabletester-mode url <URL>`.
- **Chromium asks to create a desktop keyring** on a box that has none, and the dialog lands on top of the instrument. `kiosk.sh` passes `--password-store=basic`. The kiosk stores no passwords, so there is nothing to protect. Do not remove that flag.
- **Gigabit ethernet cannot be forced.** `ethtool -s IF speed 1000 autoneg off` is silently downgraded to 100. 1000BASE-T requires autonegotiation to settle master/slave clock roles, so a forced gigabit link does not exist. Restrict what is advertised instead: `autoneg on advertise 0x020`.
- **`ethtool` Speed and Duplex are only meaningful while the link is up.** With the link down it echoes the last configured value, which reads exactly like a negotiated result. Gate every read on `Link detected: yes` or the tester will report speeds for a cable that is not plugged in.
- **Setting a NetworkManager address is not enough; the connection must be bounced.** Deactivate and reactivate, or the new address silently does not apply.
- **Touch on the panel runs over its own USB cable. HDMI is video only.** The desktop appears normally while touch does nothing. Look at the cable before anything else.
- **Prefer `nmtui` over long `nmcli` commands when the person is at the Pi's keyboard.** A four-line command with an embedded UUID is a typo waiting to happen and the failure is silent.
- **Straight-through and null modem read identically** through a symmetric loopback plug. This is physics, not a bug. The tool reports the ambiguity on purpose. Do not "fix" it in software, see DOC §12.
- **A 3-wire cable must pass the pin check** and reach the sweep. Its handshake lines grade `nc`, not `open`. Four tests pin this down. If they fail, read DOC §5 before changing them.
- **Both ends of the loopback are the same UART,** so the even-parity pass is a timing stressor, not an independent parity check. Do not oversell it in UI copy.

## Standing Rules (check every session, not just Next Steps)

1. **No em dashes anywhere.** Grep mechanically before finishing.
2. **Timestamps shown to a person use `Monday, 8/17/2026 8:25 PM`;** stored ones stay ISO. `fmt_when()` in Python and `fmtWhen()` in JS must stay in step.
3. **Only `tester/serial_tests.py` opens a port,** always closed in a `finally`.
3b. **Only `tester/ethernet_tests.py` touches a network interface,** and autonegotiation is always restored in a `finally`, both ends, on the exception path too. An interface left advertising 10BASE-T alone has quietly broken the box.
4. **Never claim a serial behaviour is verified unless it was verified on real hardware.**
5. **A change to grading needs the code, DOC §5 and the README's scoring section in the same commit.**
6. **Status colours are never plum and plum is never status.** Do not make the gauge more on-brand.
7. **Every control keeps a text label.** Icons may not load.
8. **The sweep never aborts on the first failure.**
9. **No CDN links in the templates.** Fonts are vendored. Add an icon by editing `deploy/vendor-fonts.sh` and re-running it.
10. **Run the test suite before handing over and report the real result.**

## Environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t .    # 34 tests, no hardware needed
.venv/bin/python run.py --simulate                     # virtual cables, no hardware needed
```

Simulated ports: `SIM-GOOD`, `SIM-MARGINAL` (clean to 19200, fails above), `SIM-3WIRE`, `SIM-OPEN` (pin 8 broken).

On the Pi:

```bash
./deploy/setup-pi.sh          # build or update the bench box, safe to re-run
cabletester-mode status       # mode, kiosk, server, ports, power
cabletester-mode desk         # panel to desktop, server keeps running
cabletester-mode kiosk        # panel back to the tester
```

**Secrets and environment variables:** none. The only environment variable is `CABLETESTER_PROFILES`, an optional path to the learned-profile JSON file. There is no authentication and no external service.

## Next Steps

1. Install on the Pi and fix whatever session 3 got wrong. Nothing else is worth doing first.
2. Bench validation, DOC §14, on the Pi.
3. Feed anything the hardware disproves back into DOC §5, §12 and `CableTester_SD_SETUP.md` §11.
4. Then, and only then, consider features. Everything currently parked is listed in DOC §12; none of it should be built without JP raising it.

## Quick Reference

| Thing | Where |
|-------|-------|
| Serial layer, all of it | `tester/serial_tests.py` |
| Settle time constant | `LINE_SETTLE_S`, `tester/serial_tests.py` |
| Grading and the credit table | `tester/scoring.py`, DOC §5 |
| Reference signatures | `BUILTIN_PROFILES`, `tester/profiles.py` |
| Learned profiles on disk | `profiles.json` (gitignored), or `--profiles` |
| Routes and SSE | `tester/app.py` |
| Fake cables | `tester/simulator.py` |
| Palette and tokens | `branding/colors.json`, `static/style.css` |
| Fonts and icons | `static/fonts/`, regenerated by `deploy/vendor-fonts.sh` |
| Bench box install | `deploy/setup-pi.sh`, `docs/CableTester_SD_SETUP.md` |
| Panel mode switch | `deploy/cabletester-mode` |
