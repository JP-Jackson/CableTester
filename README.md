# RS-232 Cable Tester

**Polk Production Technologies, Inc.**

A bench instrument for verifying DB9 RS-232 cables, the ones used to connect a laptop to an ABB Totalflow XFC flow computer. A basic continuity check only proves the copper is joined; this tests whether the cable still carries data cleanly **at speed**, which is what catches the aging cables that pass a buzz-out and then fail in the field.

Python backend, local web UI, live results streamed to the browser. Runs the same on a Windows laptop and on a Raspberry Pi bench box.

- **In scope:** testing a DB9 to DB9 cable in isolation with a loopback plug.
- **Out of scope:** talking to a live XFC. No Totalflow protocol is implemented. This is cable verification only.

> **Status: not yet validated on real hardware.** The tool is complete and its 34 tests pass, but every one of those tests runs against a software simulator. The logic is proven; the timing constants are not. See `docs/CableTester_DOC.md` §14 for the bench validation plan.

---

## Files

| Path | Purpose |
|------|---------|
| `run.py` | Entry point. `python run.py [--host H] [--port P] [--simulate]` |
| `tester/app.py` | Flask app: routes, the job runner, the SSE stream |
| `tester/serial_tests.py` | Pin check and baud sweep. **The only module that opens a serial port** |
| `tester/profiles.py` | Reference signatures and the learned known-good profile store |
| `tester/scoring.py` | Health score, bands, and the plain-English verdict |
| `tester/simulator.py` | Virtual cables for `--simulate` and for the test suite |
| `static/`, `templates/` | The single page, one stylesheet, the printable report, the wiring diagram |
| `branding/` | Brand guide and colour tokens, inherited from the Polk portal |
| `deploy/` | systemd unit and Chromium kiosk script for the Pi |
| `docs/` | Project doc and session pickup. **Read `CLAUDE.md` first** |

---

## Contents

- [Build the loopback plug](#build-the-loopback-plug)
- [Install on Windows](#install-on-windows)
- [Install on a Raspberry Pi](#install-on-a-raspberry-pi)
- [Running a test](#running-a-test)
- [Interpreting the score](#interpreting-the-score)
- [Learning a known-good cable](#learning-a-known-good-cable)
- [Command-line options](#command-line-options)
- [Deploying the Pi as a bench box](#deploying-the-pi-as-a-bench-box)
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

- Pin numbers are moulded into the connector plastic. **Go by those, not by position.** The rows mirror left to right between a male and a female shell.
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

USB-serial adapters usually install their own driver (FTDI, Prolific, CH340). Once installed, the port shows up as `COM3`, `COM4` and so on. The tool enumerates them, so nothing is hardcoded. The dropdown shows each adapter's description and VID:PID so you can tell a genuine FTDI (`0403:6001`) from a generic clone.

---

## Install on a Raspberry Pi

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

| Band | Score | Reading |
|---|---|---|
| Green | 85 to 100 % | Good for full-speed use |
| Amber | 60 to 84 % | Works, but degraded. Fine for slow links, watch it |
| Red | below 60 % | Not fit for high-speed use, replace it |

Under the gauge is the same result in plain English, for example *"Good to 19200 baud. Fails at 38400 and above, not suitable for high-speed use."*

**Why each rate is run twice.** pyserial does not report framing and parity errors consistently across Windows and Linux, so the tool does not rely on them. Instead it runs every rate once with no parity and once with even parity. Even parity adds a bit per character and tightens the timing; a cable that is clean without parity but errors with it is marginal, and takes partial credit rather than a pass. Byte mismatches and timeouts remain the primary metrics.

Note the honest limit: both ends of a loopback are the same UART, so the parity pass is a timing and framing stressor rather than an independent parity check. It is scored as evidence of marginal integrity, not as proof of a parity fault.

**Coverage.** If a sweep is cancelled part-way, the score is calculated only over the rates that actually ran, and the coverage percentage says so. A half-finished sweep is never reported as a clean cable.

---

## Learning a known-good cable

Guessed reference signatures are no substitute for cables you actually trust.

1. Connect a cable you know is good, with the loopback plug fitted.
2. Run the pin check.
3. Click **Learn Known-Good** and give it a name.

The stimulus and response matrix is saved to `profiles.json` beside the code, or wherever `--profiles` points. Every later pin check is compared against your saved profiles **first**, and against the built-in references only if none match. Saved profiles are listed under *Show details*, where they can also be deleted.

### Topology detection

The tool does not trust a hardcoded pin map. It records which output drives which inputs and matches that signature against references:

- **Straight-through:** pin N to pin N.
- **Null modem:** 2/3, 7/8 and 4/6 crossed.
- **3-wire:** only 2, 3 and 5 connected. Data passes, every handshake line reads n/c. This is a valid cable type, not a fault, so it is reported as an observation and the sweep still runs. Hardware flow control will not work over it.
- **Non-standard:** matches nothing known. The observed map is displayed so you can see what the cable actually does.

> **Straight-through and null modem read identically here, and the tool says so.** A null modem crosses 2/3, 7/8 and 4/6; the symmetric loopback plug crosses the same pairs straight back. Both produce the same matrix, so the tester reports "straight-through or null modem" rather than guessing. To tell them apart, look at the cable's markings or ring it out pin to pin.

---

## Command-line options

```
python run.py [--host HOST] [--port PORT] [--profiles PATH] [--simulate] [--debug]
```

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `0.0.0.0` | Interface for the web server. `127.0.0.1` keeps it local-only |
| `--port` | `5000` | TCP port for the web server, not the serial port |
| `--profiles` | `./profiles.json` | Where learned profiles are stored. Also settable via `CABLETESTER_PROFILES` |
| `--simulate` | off | Adds virtual cables (`SIM-GOOD`, `SIM-MARGINAL`, `SIM-3WIRE`, `SIM-OPEN`) paced at real baud rates, so the UI can be demonstrated with no hardware attached |
| `--debug` | off | Flask debug mode |

---

## Deploying the Pi as a bench box

`deploy/` has what is needed to make the Pi a standalone instrument that is *also* reachable over the network.

**Service on boot:**

```bash
sudo cp deploy/cabletester.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cabletester
systemctl status cabletester
```

Edit `User` and `WorkingDirectory` in the unit if you did not clone to `/home/pi/cabletester`. The service runs with group `dialout` so it can open serial ports.

**Full-screen kiosk on the attached display:**

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/cabletester-kiosk.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Cable Tester Kiosk
Exec=/home/pi/cabletester/deploy/kiosk.sh
DESKTOP
```

`kiosk.sh` waits for the server to answer before opening the window, disables screen blanking, and clears the crash bubble a power-cut bench box would otherwise show at every boot. Override the target with `CABLETESTER_URL`.

---

## Troubleshooting

**"COM3 is already open in another program."**
Something else holds the port. PCCU is the usual culprit, including a minimised instance or one left running in the system tray. Close it and try again. The tool reports this as a plain message rather than a stack trace.

**"Permission denied opening /dev/ttyUSB0."**
Add yourself to the `dialout` group and log out and back in: `sudo usermod -aG dialout $USER`.

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
