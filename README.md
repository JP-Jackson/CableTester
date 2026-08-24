# Cable Tester

**Polk Production Technologies, Inc.**

A bench instrument for verifying cables. Primarily DB9 RS-232, the ones used to connect a laptop to an ABB Totalflow XFC flow computer, and ethernet as well. A basic continuity check only proves the copper is joined; this tests whether the cable still carries data cleanly **at speed**, which is what catches the aging cables that pass a buzz-out and then fail in the field.

Python backend, local web UI, live results streamed to the browser. Runs the same on a Windows laptop and on a Raspberry Pi bench box, where it comes up as a kiosk on a 7 inch touchscreen.

- **In scope:** a DB9 to DB9 cable in isolation with a loopback plug; an ethernet patch cable strung between two of the instrument's own interfaces; and watching either for intermittent opens while a technician flexes it.
- **Out of scope:** talking to a live XFC. No Totalflow protocol is implemented. This is cable verification only.

> **Status: no bad cable has been tested on either protocol.** The 76 tests pass, but they run against a software simulator: the logic is proven, the timing constants are not. The ethernet ladder has run on real hardware and scored a real cable, and the continuity monitor's sample rate was measured on the kit, but every hardware run so far used a **good** cable. The serial side has never met a cable at all. See `docs/CableTester_DOC.md` §14 for the bench validation plan.

---

## Files

| Path | Purpose |
|------|---------|
| `start-tester.bat` | **Windows: double-click this.** Updates from GitHub, starts the tester, opens the browser |
| `run.py` | Entry point. `python run.py [--host H] [--port P] [--simulate]` |
| `tester/app.py` | Flask app: routes, the job runner, the SSE stream |
| `tester/serial_tests.py` | Pin check and baud sweep. **A serial port is only ever opened through its `open_serial()`** |
| `tester/ethernet_tests.py` | The link-speed ladder. **The only module that touches a network interface** |
| `tester/continuity.py` | The continuity monitor, both protocols |
| `tester/sweep_settings.py` | The four named sweep settings, the patterns, and the time estimates |
| `tester/profiles.py` | Reference signatures for identifying a cable's topology |
| `tester/scoring.py` | Health score, bands, and the plain-English verdict, serial and ethernet |
| `tester/history.py` | Version history, the one source of truth behind the version screen |
| `tester/simulator.py` | Virtual cables for `--simulate` and for the test suite |
| `static/`, `templates/` | The panel UI (`hmi.css`, `hmi.js`), the printable report (`style.css`), the wiring diagrams |
| `static/fonts/` | Barlow, Barlow Condensed and the icon subset, served locally so the bench box needs no internet |
| `branding/` | Brand guide and colour tokens, inherited from the Polk portal |
| `deploy/` | **`setup-pi.sh`** builds the bench box in one run. Also the systemd units, the kiosk and the mode switch |
| `docs/` | Project doc and session pickup. **Read `CLAUDE.md` first** |

---

## Contents

- [Build the loopback plug](#build-the-loopback-plug)
- [Install on Windows](#install-on-windows)
- [Install on a Raspberry Pi](#install-on-a-raspberry-pi)
- [Running a test](#running-a-test)
- [Interpreting the score](#interpreting-the-score)
- [Command-line options](#command-line-options)
- [Deploying the Pi as a bench box](#deploying-the-pi-as-a-bench-box)
- [Fonts and offline operation](#fonts-and-offline-operation)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Development](#development)

---

## Build the loopback plug

You need one DB9 shell with four short jumper wires. It fits the **far** end of the cable under test; the near end plugs into your serial adapter.

| Jumper | Pins | Signals |
|---|---|---|
| Data | 2 to 3 | RXD to TXD |
| Flow control | 7 to 8 | RTS to CTS |
| Modem status | 4 to 1 to 6 | DTR to DCD to DSR |
| Reference | 5 | Signal ground, no jumper |

Pin 9 (RI) is left unconnected.

Notes for building it:

- Pin numbers are moulded into the connector plastic. **Go by those, not by position.** The rows mirror left to right between a male and a female shell, which is why the UI draws the plug both ways round rather than asking you to mirror it in your head. If you are soldering the back of a shell, use the other drawing: a male shell's solder side matches the female view, and a female's matches the male.
- Pins 4, 1 and 6 are a three-way join: one wire from 4 to 1, a second from 1 to 6, or twist all three together.
- Use the shortest jumpers that will reach. Long loops inside the shell pick up noise and can make a good cable look marginal at 115200.
- The same diagram is drawn in the UI, colour-coded, and it doubles as the results display: after a pin check each pin is shaded with its verdict.

---

## Install on Windows

Python 3.9 or newer, from [python.org](https://www.python.org/downloads/) or the Microsoft Store. Tick **Add python.exe to PATH** during install.

```bat
git clone https://github.com/JP-Jackson/CableTester cabletester
cd cabletester

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python run.py
```

Then open <http://localhost:5000>.

### Day to day, after the first install

Double-click **`start-tester.bat`** in the project folder. It pulls the latest
version from GitHub, creates the Python environment if this is a new PC,
installs anything missing, starts the tester and opens the browser for you.

Keep the black window open while you are testing. Closing it stops the tester.

It is safe to run with no internet: it says it could not update and runs the
copy already on the PC. To pass a flag through, run it from a command prompt,
for example `start-tester.bat --simulate`.

Pin it to your taskbar or make a desktop shortcut and you never need a command
prompt again.

USB-serial adapters usually install their own driver (FTDI, Prolific, CH340). Once installed, the port shows up as `COM3`, `COM4` and so on. The tool enumerates them, so nothing is hardcoded. The dropdown shows each adapter's description and VID:PID so you can tell a genuine FTDI (`0403:6001`) from a generic clone.

---

## Install on a Raspberry Pi

> **Building the bench box, not just running the code?** Use
> `./deploy/setup-pi.sh`, which does everything below plus the kiosk, the
> systemd units and the display settings. Start from
> **`docs/CableTester_SD_SETUP.md`**, which covers the SD card, the panel and
> the kit. The steps here are the manual path, for a Pi you only want to run the
> tester on by hand.

Raspberry Pi OS ships with Python 3. You need `python3-venv` and access to the serial port.

```bash
sudo apt update
sudo apt install -y python3-venv git

git clone https://github.com/JP-Jackson/CableTester ~/cabletester
cd ~/cabletester

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Serial ports belong to the 'dialout' group. Log out and back in afterwards.
sudo usermod -aG dialout "$USER"

.venv/bin/python run.py
```

Ports appear as `/dev/ttyUSB0` (USB adapters) or `/dev/ttyAMA0` and `/dev/ttyS0` (the Pi's own UART). To use the built-in UART you must first free it from the serial console: `sudo raspi-config`, then *Interface Options*, *Serial Port*, login shell **no**, hardware serial port **yes**.

The server binds to `0.0.0.0`, so the page is also reachable from a phone or laptop at `http://<pi-address>:5000` while the Pi's own screen shows the same test.

> **A warning about the Pi's built-in UART:** it is 3.3 V logic, **not** RS-232 line levels. Use a USB-serial adapter or a proper level shifter. Wiring a real RS-232 cable straight to the GPIO header will damage the Pi.

---

## Running a test

1. Fit the loopback plug to the far end of the cable. Plug the near end into your adapter.
2. Pick the port from the dropdown. **Refresh** re-scans if you plugged in after loading the page.
3. Enter a **Cable ID**. It is stamped on the exports.
4. **Run Pin Check.** A second or two. It asserts DTR, then RTS, reading every input line after each, then sends a short byte pattern to prove the 2/3 data path. Every pin gets a verdict:

   | Verdict | Meaning |
   |---|---|
   | **Pass** | The line responded as expected |
   | **Open** | An asserted output produced no response on its paired input |
   | **Short** | Asserting one output made an unrelated input respond, or a line asserted and never released |
   | **n/c** | Not connected, and expected not to be, for instance the handshake lines on a 3-wire cable |
   | **Ref** | Pin 5, signal ground. Not directly testable; a working data path implies a good return |

5. **Run Baud Sweep.** Greyed out until the pin check passes, because there is no point measuring error rates through a cable with a broken pin. It runs 1200, 2400, 4800, 9600, 19200, 38400, 57600 and 115200 baud in ascending order, twice each (no parity, then even parity), filling in a row per rate as it goes. It never stops at the first failure: knowing a cable is clean to 19200 but fails at 57600 is the useful result.
6. **Export JSON** for the record, or **Printable Summary** for a page to staple to the cable. Both are stamped with the date, port and cable ID, and the printable version has space for a tester name and disposition.

Payload size scales with baud so each rate takes roughly the same wall-clock time. The **Payload per rate** box sets that, 2 seconds by default, so a full sweep takes about 32 seconds. Raise it for a harder soak on a suspect cable.

---

## Interpreting the score

The health gauge weights higher baud rates more heavily, because a cable that only works slowly is only fit for slow work.

| Baud | 1200 | 2400 | 4800 | 9600 | 19200 | 38400 | 57600 | 115200 |
|---|---|---|---|---|---|---|---|---|
| Weight | 1 | 1 | 2 | 3 | 4 | 6 | 8 | 10 |

```
score = (sum of weight x per-rate credit) / (sum of all weights) x 100
```

Each rate earns partial credit, so a cable that works but is getting tired scores below one that is byte-perfect:

| No-parity run | Even-parity run | Credit |
|---|---|---|
| Byte-perfect | Byte-perfect | 1.00 |
| Byte-perfect | Some errors | 0.80 |
| Byte-perfect | Failed | 0.60 |
| Errors under 1e-3 BER | Any | 0.30 to 0.40 |
| Errors over 1e-3 BER | Any | 0.00 |

**If a sweep setting runs only one parity mode, that rate is scored on the run it has**: byte-perfect earns full credit, errors under 1e-3 BER earn 0.40, anything worse earns 0.00. The table above applies only when both modes actually ran. A mode that was never attempted is not a mode that failed, and `coverage` on the result is where a narrower sweep is reported.

| Band | Score | Reading |
|---|---|---|
| Green | 85 to 100 % | Good for full-speed use |
| Amber | 60 to 84 % | Works, but degraded. Fine for slow links, watch it |
| Red | below 60 % | Not fit for high-speed use, replace it |

Under the gauge is the same result in plain English, for example *"Good to 19200 baud. Fails at 38400 and above, not suitable for high-speed use."*

**Why each rate is run twice**, on the settings that do so. pyserial does not report framing and parity errors consistently across Windows and Linux, so the tool does not rely on them. Instead it runs every rate once with no parity and once with even parity. Even parity adds a bit per character and tightens the timing; a cable that is clean without parity but errors with it is marginal, and takes partial credit rather than a pass. Byte mismatches and timeouts remain the primary metrics.

Note the honest limit: both ends of a loopback are the same UART, so the parity pass is a timing and framing stressor rather than an independent parity check. It is scored as evidence of marginal integrity, not as proof of a parity fault.

**Coverage.** If a sweep is cancelled part-way, the score is calculated only over the rates that actually ran, and the coverage percentage says so. A half-finished sweep is never reported as a clean cable.

**Passes keep the worst result, never the latest and never an average.** If a
setting runs each rate more than once, that is the whole point of repeating: a
fault that shows one time in three is still a fault, and averaging would hide
exactly the intermittent this instrument exists to find.

### Ethernet

An ethernet cable is graded by which link speeds it will carry, because 10 and
100 use only pairs 1-2 and 3-6 while 1000BASE-T needs all four. Which rungs
come up therefore localises the fault to a pair.

| Highest speed linked | Score | Reading |
|---|---|---|
| 1000 Mb | 100 | All four pairs good |
| 100 Mb | 62 | Pairs 1-2 and 3-6 good; **4-5 and 7-8 (blue and brown) suspect** |
| 10 Mb | 22 | Links only at the slowest rate. Replace it |
| No link | 0 | Dead |

**An inconsistent ladder scores 0 and red,** not a warning. A cable that links
at 1000 but not at 100 is not a cable with a small problem; it is a result the
model does not explain, and the honest answer is to refuse it rather than
average it into something reassuring.

---

## Topology detection

The tool does not trust a hardcoded pin map. It records which output drives which inputs and matches that signature against references:

- **Straight-through:** pin N to pin N.
- **Null modem:** 2/3, 7/8 and 4/6 crossed.
- **3-wire:** only 2, 3 and 5 connected. Data passes, every handshake line reads n/c. This is a valid cable type, not a fault, so it is reported as an observation and the sweep still runs. Hardware flow control will not work over it.
- **Non-standard:** matches nothing known. The observed map is displayed so you can see what the cable actually does.

> **Straight-through and null modem read identically here, and the tool says so.** A null modem crosses 2/3, 7/8 and 4/6; the symmetric loopback plug crosses the same pairs straight back. Both produce the same matrix, so the tester reports "straight-through or null modem" rather than guessing. To tell them apart, look at the cable's markings or ring it out pin to pin.

---

## Command-line options

```
python run.py [--host HOST] [--port PORT] [--simulate] [--debug] [--eth-test A B]
```

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `0.0.0.0` | Interface for the web server. `127.0.0.1` keeps it local-only |
| `--port` | `5000` | TCP port for the web server, not the serial port |
| `--simulate` | off | Adds virtual cables (`SIM-GOOD`, `SIM-MARGINAL`, `SIM-3WIRE`, `SIM-OPEN`) paced at real baud rates, so the UI can be demonstrated with no hardware attached |
| `--debug` | off | Flask debug mode |
| `--eth-test A B` | off | Runs the ethernet speed ladder between two interfaces and exits. String the cable under test between them, for example `--eth-test eth0 eth1`. Needs `CAP_NET_ADMIN`, which the systemd unit grants and a shell does not |

---

## Sweep settings

The sweep's knobs sit behind four named settings, because nobody at a bench
knows what to set "payload per rate" to. Pick one when you start a sweep; edit
any of them under **Setup**.

| Setting | What it does |
|---------|--------------|
| **Quick** | Three rates, half a second each. Catches an obviously bad cable. |
| **Standard** | All eight rates, both parities. The everyday check. |
| **Thorough** | All eight, three passes, stress pattern. For a cable going into service. |
| **Custom** | Yours to set. |

**Every setting states how long it will take before you start it.** All four
are editable, not just Custom: if your links all run at 9600, redefine Standard
so it stops spending a minute on 115200.

**Test pattern is the one worth understanding.** Random data is a fair average
case and averages away the stress that matters. `0x55` flips every bit cell,
which is the worst case for slew rate and cable capacitance and is what
actually finds a marginal cable at high baud. That is why Thorough is harder
than Standard rather than merely longer.

**Passes keep the worst result**, never an average. A fault that shows one time
in three is still a fault.

---

## Continuity: finding an intermittent

This is the test for the cable that passes everything here and still fails in
the field. Such a cable is wired correctly: a conductor broken inside its
insulation makes perfect contact lying still, and opens for a fraction of a
second when the cable is flexed. No static test can see it, because the fault
is not there while the test runs.

1. Go to **Continuity** and press **Start watching**.
2. **Work the cable with your hands.** Flex it at both connectors, at the
   strain reliefs, and along its length. The screen tells you to.
3. Press **Stop and record**.

Every dropout is counted and timestamped. One is enough to condemn the cable.

> **No dropouts does not mean the cable is sound.** It means nothing happened
> while the tester was watching, at the resolution it could watch. Breaks
> shorter than about 10 ms are invisible, because a USB-serial adapter only
> reports line changes every 1 to 10 ms, and a fault only shows if you moved
> the cable where it is damaged.

---

## Deploying the Pi as a bench box

`deploy/` turns a Raspberry Pi into a standalone instrument that is *also*
reachable over the network. For the full build, from a blank SD card to a kit in
a case, see **`docs/CableTester_SD_SETUP.md`**. The short version:

```bash
cd ~/cabletester
./deploy/setup-pi.sh
sudo reboot
```

One run, roughly five minutes, and **safe to re-run**: re-running it is the
supported way to apply a code update. It builds the venv, adds you to `dialout`,
installs and starts the server, installs the kiosk and the mode switch, sets
desktop autologin, disables screen blanking, and reports whether the Pi has
recorded undervoltage.

The script reads the user and paths from the account it runs as, so nothing has
to be cloned to a particular directory and no unit file needs hand-editing.

### Kiosk and network access run at the same time

They are not two modes. On every boot the panel is locked to a full-screen
Chromium showing the tester, with no desktop, no taskbar and no login prompt.
Meanwhile the server binds `0.0.0.0` and SSH stays up, so a laptop or a phone on
the same network reaches `http://<pi>:5000` and watches the same live test
without disturbing the panel.

The only thing that is really a mode is what the **attached panel** shows:

| Command | Effect |
|---------|--------|
| `cabletester-mode status` | What is running, plus the serial ports and the power state |
| `cabletester-mode desk` | Drop the panel to the normal desktop, to work on it |
| `cabletester-mode kiosk` | Lock it back to the tester |
| `cabletester-mode restart` | Reload the kiosk after a UI change |
| `cabletester-mode logs` | Follow the kiosk's output |

The choice survives a reboot. Dropping to the desktop never stops the server and
never interrupts a sweep in progress.

`status` reports the Pi's power state on purpose. A Pi browning out under load
produces serial timing errors that look, on screen, exactly like a marginal
cable. Anything other than `throttled=0x0` means check the supply before
believing a bad result.

---

## Fonts and offline operation

The tester needs no route to the internet. Barlow, Barlow Condensed and the four
icon glyphs the UI uses are served from `static/fonts/`, 178 KB in total, so the
page looks identical on a bench with no network as it does on a desk with one.

There is no CDN `<link>` in the templates. Do not add one back.

To change a font weight or add an icon, edit the lists at the top of
`deploy/vendor-fonts.sh`, run it on a machine that does have a network, and
commit the result:

```bash
./deploy/vendor-fonts.sh
```

It pulls the latin subset of each weight from Google Fonts, pulls the Tabler
webfont from the npm registry, and subsets it down to only the icons the markup
actually references. The full Tabler webfont is 452 KB for about 5,900 icons;
the four this UI uses come to 1 KB.

---

## Troubleshooting

**A known-good cable starts failing the higher baud rates on the Pi.**
Check the power first, not the cable. `cabletester-mode status` reports the Pi's
throttling state; anything other than `throttled=0x0` means it has browned out
or thermally throttled, and an underfed Pi produces timing errors that are
indistinguishable on screen from a marginal cable. Use a 5V 3A supply for the
Pi and a separate supply for the panel. Only once power is clean is
`LINE_SETTLE_S` in `tester/serial_tests.py` worth suspecting.

**The panel blanks part way through a sweep.**
`sudo raspi-config`, *Display Options*, *Screen Blanking*, **No**. Do not reach
for `xset s off`: it is an X11 tool, current Raspberry Pi OS runs Wayland, and
it fails silently there, which looks exactly like the setting not working.

**The kiosk will not start when launched over SSH.**
It needs the graphical session's environment, which an SSH shell does not have.
Use `cabletester-mode kiosk`, which imports it first, rather than
`systemctl --user start` directly.

**"COM3 is already open in another program."**
Something else holds the port. PCCU is the usual culprit, including a minimised instance or one left running in the system tray. Close it and try again. The tool reports this as a plain message rather than a stack trace.

**"Permission denied opening /dev/ttyUSB0."**
Add yourself to the `dialout` group and log out and back in: `sudo usermod -aG dialout $USER`.

**An update does not seem to have taken effect.**
The tester tells browsers not to cache its files, so a restart is normally
enough. If a screen still looks stale, press Ctrl+F5 to force a reload. If the
update itself did not download, `start-tester.bat` prints why: usually no
internet, or an edited file in the folder blocking the pull.

**No ports listed.**
Press **Refresh**. If it is still empty, the adapter's driver is not installed (Windows: check Device Manager) or the adapter is not plugged in. The Pi's built-in UART needs freeing from the serial console first, see the install notes above.

**Everything reads open, or the topology says "No continuity".**
Nine times out of ten the loopback plug is not fitted, or the cable is not seated. Check that before condemning the cable.

**A cable you trust shows spurious opens.**
Suspect the settle time before the cable. `LINE_SETTLE_S` in `tester/serial_tests.py` is 120 ms, and USB-serial adapters vary a lot in how quickly they apply modem control line changes. Raise it and retest.

**Pin check passes but the sweep fails everywhere.**
That pattern, DC continuity fine and data corrupt, is exactly the failure this tool exists to catch. Try a shorter cable or a different adapter first to rule those out, then replace the cable.

**Both ends look crossed but the tool says "straight-through or null modem".**
Expected. See the note under [topology detection](#topology-detection).

**Icons are missing or the fonts look plain.**
Barlow and the Tabler icons load from a CDN and this box has no route to it. Layout and every control label are unaffected, so this is cosmetic. If it becomes the normal state, the fonts can be vendored locally, see `docs/CableTester_DOC.md` §12.

---

## How it works

The Python process does all serial I/O. Tests run on a worker thread and push events to the browser over Server-Sent Events, which are one-directional updates, so no websocket is needed. Because the worker owns the port, closing the browser mid-test cannot leave an adapter locked: the run finishes and the port is closed in a `finally` block either way. Only one test runs at a time; a second request is refused rather than queued, since there is one port and one cable.

Payloads are pseudorandom but **seeded**, so the same rate always sends the same bytes and two runs are directly comparable. Read timeouts scale with the expected transmission time, generous at 1200 baud and tight at 115200.

Full architecture, test method and decision history: `docs/CableTester_DOC.md`.

---

## Development

Read `CLAUDE.md` first. It carries the project's standing rules, including the em dash rule and the handover checklist.

Run the test suite. 34 tests, no hardware required, since every serial interaction runs against the simulator:

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Try the UI without a cable:

```bash
.venv/bin/python run.py --simulate
```

Then pick `SIM-MARGINAL` for a cable that is clean to 19200 and falls apart above it, or `SIM-OPEN` for one with a broken pin 8.

**Before finishing any session,** run the handover checklist in `CLAUDE.md`. It is not optional and it does not depend on a slash command.
