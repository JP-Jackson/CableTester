# CableTester: Project Documentation

> **STYLE RULE, READ THIS BEFORE WRITING ANYTHING: NEVER USE EM DASHES.** Not in code, comments, commits, UI copy, or these docs. Grep your own new text before calling any writing task done. Full context: `CLAUDE.md` and §15 below.

**Created:** Thursday, 8/20/2026
**Last updated:** Thursday, 8/20/2026 (session 2)
**Status:** Built and working end to end against the simulator. **Never yet run against a real cable or a real serial adapter.** Every number in the test suite comes from `tester/simulator.py`, which is a model of a cable, not a cable. The logic is proven; the timing constants are not. See §12 for what that leaves open and §14 for the bench validation plan.

---

## 1. Project Overview

A bench instrument for verifying cables. Primarily DB9 RS-232, the ones used to connect a laptop to an ABB Totalflow XFC flow computer, and since 8/23/2026 ethernet as well.

**The problem it exists to solve:** cables are failing in the field despite passing a basic continuity check. A continuity check proves the copper is joined. It does not prove the cable carries data cleanly at 115200 baud after a few years in a truck. This tool tests signal integrity at speed, not just DC continuity, and gives back a number a technician can act on.

**In scope:** testing a DB9 to DB9 cable in isolation on a bench with a loopback plug on the far end; testing an ethernet patch cable strung between two of the instrument's own interfaces; and watching either kind for intermittent opens while a technician flexes it.

**Out of scope, deliberately:** talking to a live XFC. No Totalflow protocol is implemented and no flow computer is contacted. This is cable verification only. Do not add protocol support without JP raising it first.

Two audiences, one instrument:
- **Field technicians** who need a glanceable verdict: a big percentage, a colour, and one line of plain English. They meet it as a kiosk on a 7 inch touchscreen where nothing scrolls.
- **JP**, who wants the raw numbers: per-rate byte counts, bit error rates, throughput against theory, and the raw pin matrix. Those sit behind the detail screens and the JSON export, so they do not get in the technician's way.

## 2. Tech Stack

| Layer | Tool | Why chosen | Cost |
|-------|------|-----------|------|
| Language | Python 3.9+ | Runs identically on a Windows laptop and a Raspberry Pi, which is the hard requirement | free |
| Serial I/O | `pyserial` >= 3.5 | The only real option. Handles COM ports and `/dev/tty*` the same way, exposes modem control lines as properties | free |
| Web server | Flask >= 2.3 | Requirement was one lightweight framework and no frontend build step. Flask serves the page, the API and the event stream from one process | free |
| Live updates | Server-Sent Events | Updates only ever flow server to browser, so a websocket would be extra machinery for nothing. SSE is a plain HTTP response the browser reconnects on its own | free |
| Frontend | Plain HTML, CSS and JS | No build step, by requirement. A bench box should not need npm to change a label | free |
| Fonts and icons | Google Fonts (Barlow) and Tabler icons, both by CDN | Matches the Polk portal exactly. Both degrade gracefully offline, see §3 and §11 | free |
| Version control | GitHub, `JP-Jackson/CableTester` | | |

**Deliberately not used:** no database (results are per-session and exported as files), no async framework (one port, one test at a time), no charting library (the gauge is 20 lines of hand-written SVG arc maths).

## 3. Architecture Decisions

**A serial port is only ever opened through `serial_tests.open_serial()`.** Two modules run tests over the wire now, `serial_tests.py` and `continuity.py`, but only one of them knows how to open a port: the continuity monitor calls `open_serial()` and closes in its own `finally`. That keeps the "always close the port" guarantee checkable, because the open path is still a single function to audit and every caller of it is a `try`/`finally` away from a leak that a test would catch. Route handlers never open a port.

**A network interface is only ever touched by `tester/ethernet_tests.py`.** Same rule, second protocol. It is the only module that runs `ethtool`, and the only one that changes what an interface advertises. Anything it changes it restores in a `finally`, because leaving a technician's Pi advertising 10 Mb after a cancelled test is the network equivalent of a leaked port.

**The worker thread owns the port, not the request.** A test runs on a background thread and pushes events into per-subscriber queues. The browser subscribes over SSE. If the browser closes mid-test, the stream ends and the test carries on to completion, closing the port in its `finally`. Tying the port's lifetime to an HTTP request would leave adapters locked whenever a tech closed the lid on a laptop.

**One test at a time, refused rather than queued.** There is one port and one cable. A second request gets a 409 with a message naming what is already running. Queueing would let a tech wander off and come back to results from a cable they already unplugged.

**The sweep is gated server-side, not just in the UI.** The button greys out, and `POST /api/sweep` independently rejects a request whose pin check did not pass, or passed on a different port. A greyed button is a hint, not a control.

**Topology is measured, not assumed.** The pin check records the full stimulus and response matrix (which output drives which inputs) and compares that signature against the references in `BUILTIN_PROFILES`. It does not trust a hardcoded pin map. A cable that matches nothing is reported as non-standard with its observed map shown, which is honest rather than wrong.

**Straight-through and null modem are reported as ambiguous, not guessed.** See §12, this is a property of the physics, not a gap in the code.

**Payloads are seeded.** `PAYLOAD_SEED ^ baud` drives a `random.Random`, so 9600 baud always sends the same bytes. Two runs on the same cable are directly comparable, and a failure can be reproduced.

**Writes and reads are interleaved during a transfer.** Writing an entire payload before reading would overrun the driver's receive buffer on the larger payloads (23 KB at 115200), which would look like a cable fault. `_transfer()` alternates in chunks.

**The simulator is a first-class module, not test scaffolding.** `tester/simulator.py` ships in the package and backs both the test suite and the `--simulate` flag. It paces itself at real baud rates when `realtime=True`, so a demo produces sensible elapsed times, throughput figures and live progress rather than everything completing instantly.

**Fonts and icons are vendored, not fetched.** `static/fonts/` carries the latin subset of Barlow and Barlow Condensed plus a four-glyph Tabler subset, 178 KB in total, regenerated by `deploy/vendor-fonts.sh`. The bench box has no route to the internet, so a CDN link is not a dependency, it is a guaranteed miss. No control depends on an icon for its meaning.

**The panel UI is a state machine, the report is a document, and they do not share a stylesheet.** `static/hmi.css` dresses `templates/index.html` for the 1024x600 touchscreen; `static/style.css` now dresses only `templates/report.html`. Trying to make one sheet serve a fixed-size instrument panel and a printable A4 page is how the panel starts scrolling.

**A screen is a pure function of state, rebuilt whole on every change.** `render()` regenerates the active screen's markup and rebinds every handler. There is no partial-update path, which means there is no partial-update path to get wrong: the class of bug where one control updates and its neighbour does not cannot occur. At this size the cost of the redraw is nothing.

**Selection lives in state, not in the DOM.** Which serial port, which two ethernet interfaces, and whether the plug is male or female are all fields on `state`, persisted to `localStorage`. They were briefly read straight off a `<select>` element, which meant they were unreadable from any screen that did not draw that element and reset on every render. On a kit where the connectors are wired in and never change, selection belongs in Setup and belongs in state.

## 4. Environment Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python run.py                        # http://localhost:5000
```

Serial port access on Linux needs group membership: `sudo usermod -aG dialout "$USER"`, then log out and back in.

No hardware needed to work on the UI or the logic:

```bash
.venv/bin/python run.py --simulate
```

registers four virtual ports (`SIM-GOOD`, `SIM-MARGINAL`, `SIM-3WIRE`, `SIM-OPEN`) paced at real baud rates.

**CLI flags:** `--host` (default `0.0.0.0`), `--port` (default 5000, the web server's port, not a serial port), `--profiles` (path to the learned-profile JSON, also settable via `CABLETESTER_PROFILES`), `--simulate`, `--debug`.

## 5. Test Method

This section is the specification for how a cable is graded. **A change to the code here needs a change here and in the README's "Interpreting the score" in the same commit.**

### Stage 1: Pin check

Runs on its own, takes about a second, and is the first thing a tech does with a suspect cable.

1. Drop DTR and RTS, wait `LINE_SETTLE_S * 2`, read every input as a baseline.
2. For each output in DTR then RTS: assert it, wait `LINE_SETTLE_S`, read all four inputs. De-assert, wait, read them again.
3. A line counts as **connected** only if it followed the output up **and** back down. One that goes high and stays high is stuck, not connected, and is reported as a short. This is deliberate: an early cut called that a pass, and a shorted-to-supply line would have shipped as good.
4. Send `PIN_CHECK_PATTERN` at 9600 baud and read it back to prove pins 2 and 3.

`LINE_SETTLE_S` is **120 ms**, and it is a guess. USB-serial adapters route modem control lines over USB control transfers, which are far from instant, and the right value varies by chip. **This is the single most likely constant to need changing after the first real bench session.** Too low and a good cable shows spurious opens.

Per-pin verdicts: `pass`, `open` (asserted output, no response on its pair), `short` (an unrelated input responded, or a line never released), `nc` (not connected and expected not to be, see below), `reference` (pin 5, ground, not directly gradable).

### Cable topology detection

The matrix is canonicalised into a signature: `{"DTR": [...], "RTS": [...], "data": bool}`, then matched against learned profiles first, then the built-in references (`straight_through`, `null_modem`, `three_wire`, `handshake_only`, `dead`). No match gives "Non-standard" and the observed map is displayed.

### The 3-wire rule

A 3-wire cable (only 2, 3 and 5 connected) is a **valid cable type, not a fault**. Its handshake lines are graded `nc` rather than `open`, it passes the pin check, and it proceeds to the baud sweep.

This only applies when the observed signature matches a reference that expects those lines absent, or a learned profile. A full-handshake cable missing one line matches nothing and is correctly reported as an open circuit. The `dead` and `handshake_only` references are explicitly excluded from the rule, so a cable with no data path always fails whatever else it matches.

The first implementation got this wrong: it marked every absent handshake line `open`, failed the pin check, and locked the sweep. That made the tool refuse to sweep exactly the cable you would most want to sweep. Caught by testing `SIM-3WIRE` end to end.

### Stage 2: Baud sweep

Locked until the pin check passes. Runs 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200 in ascending order, **twice at each rate**: once `PARITY_NONE`, once `PARITY_EVEN`.

**It never aborts on first failure.** Knowing a cable is clean to 19200 but fails at 57600 is the useful result.

Payload size scales with baud (`baud / 10 * seconds`, clamped to 64 bytes minimum and 64 KB maximum) so every rate takes roughly the same wall-clock time. Default 2 seconds per rate, so a full sweep is about 32 seconds.

Timeouts scale with the expected transmission time: `expected * 2.5 + 1.0` seconds, generous at 1200 and tight at 115200. An idle limit (`byte_time * 200`, minimum 0.5 s) ends a transfer that has stalled after everything was sent.

Per run it records: bytes sent, bytes received, mismatched bytes, missing bytes, timeout events, bit errors (population count of the XOR, plus 8 per missing byte), bit error rate, elapsed time, throughput and efficiency against theoretical.

**Why parity is run at all.** pyserial does not expose framing and parity errors consistently across Windows and Linux, so the tool does not rely on them. Even parity adds a bit per character and tightens the timing; a cable that is clean without parity but errors with it is marginal. Note the honest limit: both ends of a loopback are the same UART, so this is a timing and framing stressor, not an independent parity check. It is scored as evidence, not proof.

### Scoring

Weights: 1200 to 1, 2400 to 1, 4800 to 2, 9600 to 3, 19200 to 4, 38400 to 6, 57600 to 8, 115200 to 10. Sum 35.

Each parity run classifies as `clean` (byte-perfect), `marginal` (errors at or below 1e-3 BER) or `fail`. The pair gives the rate its credit:

| No parity | Even parity | Credit |
|---|---|---|
| clean | clean | 1.00 |
| clean | marginal | 0.80 |
| clean | fail | 0.60 |
| marginal | clean or marginal | 0.40 |
| marginal | fail | 0.30 |
| fail | any | 0.00 |

**A parity mode that was never run is scored on what was measured, not as a failure.** When a sweep setting runs only one parity mode, that rate's credit comes from the single run it has: `clean` earns the rate its full weight, `marginal` earns 0.40, `fail` earns 0.00. The pair table above applies only when both modes actually ran.

This is the correction made on 8/24/2026, and it mattered. `classify_run(None)` returns `fail`, which is correct for a run that errored and wrong for one that was never attempted, and the pair table could not tell them apart. Any setting that did not run even parity therefore scored every rate at 0.60, capped a flawless cable at exactly 60, and tripped the `max_reliable_baud` threshold of 0.80 so the verdict read "Errors at every rate" above a table showing PASS on every row. Found on the kit, on a real cable, on the quick setting. The reasoning for full credit is that the even-parity pass is a timing stressor rather than an independent check of the cable (both ends are the same UART, see above), so its absence makes the test narrower, not the cable worse. How much was measured belongs in `coverage`, which already reports it.

`score = sum(weight * credit) / sum(weight) * 100`. Bands: green 85 to 100, amber 60 to 84, red below 60.

**Rates that never ran are excluded from the denominator** and `coverage` reports how much of the weighted range was measured, so a cancelled sweep is never reported as a clean cable.

**The verdict names a rate the sweep actually ran.** The "errors at every rate" line quoted 1200 baud unconditionally, so a sweep starting at 9600 accused a rate it had never tried.

`max_reliable_baud` is the highest rate with every rate below it also at credit 0.8 or better. It drives the plain-English verdict.

### 5b. Sweep settings, patterns and passes (added 8/23/2026)

The sweep's knobs sit behind four named settings, because "payload per rate"
was the wrong thing to put in front of a technician: nobody at a bench knows
what to set it to. **All four are editable and saved**, not only Custom, so a
shop whose links all run at 9600 can redefine Standard rather than live with a
default that wastes a minute on 115200 every time. Each states its time cost on
the button, which is what stops someone starting a ten minute test and walking
away.

Factory values are in `tester/sweep_settings.py`. Stored per box in
`sweep-settings.json` (gitignored), written atomically because this box gets
its power cut and a truncated settings file would take the instrument down at
the next boot. A hand-edited bad value degrades field by field to the factory
value rather than crashing when someone presses start.

**Test patterns.** The sweep sent pseudorandom bytes and nothing else, which is
a fair average case and averages away the stress that matters.

| Pattern | What it is for |
|---------|----------------|
| `random` | Pseudorandom, reproducible from a fixed seed. Fair average case. |
| `stress` | `0x55`, alternating bits every cell. **Worst case for slew rate and cable capacitance, which is what actually kills a marginal cable at high baud.** |
| `dc` | A run of ones then a run of zeros. Worst case for DC balance; finds AC-coupled or capacitively loaded paths a balanced pattern glides over. |

This is what makes Thorough genuinely harder than Standard rather than merely
longer.

**Passes keep the WORST result, never the latest and never an average.** That
is the whole point of repeating: a fault that shows one time in three is still
a fault, and averaging would hide exactly the intermittent this instrument
exists to find. `_worse()` ranks an outright error worst, then a run that
received nothing, then by corrupted and missing bytes. Comparing bit error rate
alone would rank a short clean run above a long one with a single flipped bit,
which is backwards for this purpose.

### 5c. Continuity monitoring (added 8/23/2026)

The test that goes at the reason the project exists. Cables that fail in the
field pass every continuity check on a bench, which means **they are wired
correctly and fail anyway**. A conductor broken inside its insulation makes
perfect contact lying still and opens for a few hundred milliseconds when
flexed. No static test can see that, because the fault is not present while the
test runs.

So `tester/continuity.py` holds the lines under continuous watch **while a
technician moves the cable**, and timestamps every dropout. On serial it
asserts DTR and RTS and polls CTS, DSR and DCD; on ethernet it watches carrier
between the two ports. The instruction to move the cable is the test; the
software only counts.

**The baseline is the cable at rest, not an ideal.** A 3-wire cable holds its
handshake lines low and that is not a fault. Baselining against what a correct
cable would do would report every 3-wire cable as permanently broken.

**Scoring is deliberately absent, and a clean run is never called a pass.** A
monitor that saw nothing has established only that nothing happened while it
watched, at the resolution it could watch. On serial the real floor is the
adapter, which reports modem line changes on an interrupt endpoint polled every
1 to 10 ms, so nothing in this code can beat it. The verdict says so in as many
words. **That distinction is the difference between a useful instrument and a
dangerous one**, and it is tested.

**One ioctl per sample, not one per line.** pyserial's `.cts`, `.dsr` and `.dcd`
are three separate `TIOCMGET` calls, so reading three lines meant three
syscalls **taken at three different instants**, and a dropout shorter than the
gap between them could land in the seam and be missed entirely. `_sampler()`
returns a closure that issues a single `fcntl.ioctl(fd, TIOCMGET)` and decodes
every bit from the one word, so all three lines are read at the same instant.
Measured on the kit: **119 samples/s to 1,267 samples/s**, and a dropout can no
longer fall between two lines of the same sample. The `getattr` path is kept as
a fallback for a port with no file descriptor, which is what the simulator is.

**The floor is the adapter, and the UI says the number rather than implying
one.** A USB-serial adapter reports modem line changes on an interrupt endpoint
polled every 1 to 10 ms, so `SERIAL_ADAPTER_FLOOR_MS = 10.0` is the honest
limit no amount of polling beats. The screen states what the run achieved:
"sees breaks longer than 10 ms". A monitor that quietly claimed better
resolution than its hardware has would be worse than no monitor.

**The verdict names the conductor and the pin, and says what to do.** "OPEN"
alone sends a technician back to a cable with nowhere to start. `LINE_PIN` maps
each watched line to its DB9 pin, the verdict names both, and the plug diagram
shades it in the shell the technician has in their hand. The advice is "Repair
the ends, or throw the cable away." Wording is GOOD or OPEN throughout, never
pass or fail: a monitor that saw nothing has not passed anything, and the two
words a technician needs are the two states a conductor can be in.

### 5d. The ethernet link-speed ladder (added 8/23/2026)

There is no loopback plug for ethernet and no reflectometry on this hardware,
so the method is a ladder: link the cable between two real PHYs and see which
speeds it will carry. **10 and 100 use only pairs 1-2 and 3-6; 1000BASE-T needs
all four.** Which rungs come up therefore localises the fault to a pair, which
is as much as this kit can honestly say and considerably more than pass or
fail.

| Rung | Advertised | Pairs it exercises |
|------|-----------|--------------------|
| 10 Mb full | `0x002` | 1-2 and 3-6 |
| 100 Mb full | `0x008` | 1-2 and 3-6 |
| 1000 Mb full | `0x020` | all four |

**Speeds are advertised, never forced.** `ethtool -s IF speed 1000 autoneg off`
is silently downgraded to 100, because 1000BASE-T *requires* autonegotiation to
settle which end is master for clock recovery. Restricting the advertisement
mask on **both** ends gets the same diagnostic honestly: offer one speed and
the link either comes up at it or does not come up at all. `ADV_ALL` is
restored in a `finally`.

**Link state is read from sysfs, not from ethtool.** With the link down,
`ethtool` echoes back the last configured value, which reads exactly like a
negotiated result: the first unplugged run appeared to negotiate 10 Mb and 100
Mb with no cable in it. `link_state()` reads `carrier` first and only then
`speed` and `duplex`, and reports `--` when carrier is down. Anything that
reads a speed without gating on carrier is reading a setting, not a
measurement.

**An inconsistent ladder scores zero, not a warning.** A cable that links at
1000 but not at 100 is not a cable with a small problem; it is a result the
model does not explain, and the honest response is to refuse it rather than to
average it into something reassuring. `score_link_ladder()` forces those to
0 and red. Scoring one 100/green with a cautionary verdict beside it, which is
what it did first, is the failure mode this instrument exists to avoid.

**An interface carrying the default route is refused as untestable.**
`carries_default_route()` reads `/proc/net/route` and `/proc/net/ipv6_route`
directly rather than shelling out to `ip`, which is not present on every image,
and distinguishes a missing routing table from an unreadable one so that an
absent file does not mark every interface untestable. Renegotiating the link
the technician is connected over would take the instrument off the network
mid-test.

## 6. API / Endpoint Reference

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | The panel UI |
| `GET` | `/api/history` | Version history, newest first, plus the running version |
| `GET` | `/api/ports` | Enumerate serial ports with description, VID:PID, serial number, hwid |
| `GET` | `/api/eth/interfaces` | Enumerate ethernet interfaces, each with link state and whether it carries the default route |
| `GET` | `/api/sweep-settings` | The four sweep settings and the pattern list |
| `PUT` | `/api/sweep-settings/<id>` | Edit one setting. All four are editable, not just Custom |
| `POST` | `/api/sweep-settings/reset` | Restore the factory values |
| `POST` | `/api/pincheck` | Body `{port}`. Starts a pin check, returns `{job}`. 409 if a test is running |
| `POST` | `/api/sweep` | Body `{port, pincheck, setting}`. Rejects unless that pin check passed on that port |
| `POST` | `/api/eth/ladder` | Body `{a, b}`. Runs the link-speed ladder between two interfaces |
| `POST` | `/api/continuity` | Body `{proto, port}` or `{proto, a, b}`. Starts the monitor; it runs until cancelled |
| `POST` | `/api/cancel/<job_id>` | Sets the job's cancel event |
| `GET` | `/api/job/<job_id>` | Job state and result, for polling if the stream is lost |
| `GET` | `/api/events/<job_id>` | SSE stream. Replays the backlog, then live events, then closes on `job_end` |
| `GET` | `/api/export.json` | Query `pincheck`, `sweep`, `cable_id`. Downloads the full bundle |
| `GET` | `/report` | Same query. The printable summary |

**SSE event types.**

| Source | Events |
|--------|--------|
| Pin check | `stage`, `pin_baseline`, `pin_step`, `pincheck_result` |
| Baud sweep | `sweep_rate` (carrying `grade` on the done event), `sweep_run`, `sweep_progress` |
| Ethernet ladder | `rung_start`, `rung_done` |
| Continuity | `mon_baseline`, `mon_event`, `mon_tick` |
| All | `score`, `job_end` |

`sweep_progress` and `mon_tick` are deliberately **not** replayed to a late
subscriber. Both fire several times a second; a browser joining late needs
current state, not every tick of a run that has already finished. Everything
else is replayed in order, so a reconnecting browser sees the whole test.

`mon_tick` exists so that a continuity run that is working perfectly still
proves it is alive. A monitor whose whole job is to emit nothing until
something goes wrong is indistinguishable, on screen, from a monitor that has
crashed. The tick carries the running sample count and rate, which is also what
lets the UI state the resolution the run actually achieved rather than a
resolution it hoped for.

Rates are graded server-side as they complete, in the `emit` wrapper in
`api_sweep`, so the browser never re-implements `scoring.py`. The same holds
for the ethernet ladder: `score_link_ladder()` runs on the server and the
browser draws what it is told.

**Cancelling a continuity run finishes it, it does not abort it.** Every other
test has a natural end and cancelling one throws away an incomplete answer, so
those jobs end `cancelled`. The monitor has no natural end: it runs until the
technician has finished working the cable, and stopping it *is* how it
completes. Its job ends `done` with a full result, and the events it collected
are the result.

## 7. UI / Screen Structure

`templates/index.html` is an instrument panel for a 1024x600 touchscreen, not a
web page. **Nothing scrolls, by design and by rule.** Every screen fits the
panel or it is the wrong screen.

**The frame,** present on every screen:

- **Status bar.** The wordmark, a read-only readout of what is under test, the
  cable ID field, the protocol toggle, and the status lamp. The readout is
  read-only on purpose: it reports the selection made in Setup rather than
  offering it again, so there is one place a port can be changed and it is not
  a control the technician meets mid-test.
- **Nav rail.** Six buttons, labelled, with an icon that is decoration. The set
  depends on the protocol:

| Protocol | Screens |
|----------|---------|
| Serial | TEST, PINS, SWEEP, CONTINUITY, WIRING, SETUP |
| Ethernet | TEST, PAIRS, SPEED, CONTINUITY, WIRING, SETUP |

- **Version.** Shown on the nav; tapping it opens the version history sheet
  over the panel, with a close button. This is the one screen permitted to
  describe the past. See `tester/history.py` and the carve-out in `CLAUDE.md`.

**The screens:**

- **TEST.** The gauge, the plain-English verdict, the start button, and the
  results. The results being here is the point: the answer appears on the
  screen where the test was started, and each result row is tappable and opens
  the screen carrying the detail behind it.
- **PINS** (serial). The per-pin table, the detected topology and the observed
  map, beside the plug diagram shaded with each pin's verdict.
- **SWEEP** (serial). Start opens the settings picker: four named settings, each
  stating its time cost on the button, because that is what stops someone
  starting a ten minute test and walking away. A row per baud rate fills in
  live, green, amber or red.
- **PAIRS / SPEED** (ethernet). The pair-level verdict and the link-speed
  ladder, a row per rung.
- **CONTINUITY.** Both protocols. The instruction to move the cable, the live
  sample rate, a timeline strip of the run, and the verdict. Wording is GOOD or
  OPEN, never pass or fail, and an open names the conductor and its pin number
  and shades it on the plug.
- **WIRING.** The loopback plug for serial, the pair reference for ethernet,
  as inline SVG so it scales and prints. The DB9 is drawn twice, male and
  female, because the shell reverses the left-to-right pin order and asking a
  technician to mirror that mentally with the plug in their hand is how a plug
  gets built wrong. **Any heading that names a shell follows the toggle**;
  a fixed "male view" over a drawing that changed was a real bug, and it is
  exactly the kind that sends someone to the wrong pin.
- **SETUP.** Serial port, ethernet A and B, Rescan, the sweep settings editor,
  theme, and adapter detail.

**Two modal scrims,** `#pick-scrim` for the sweep settings picker and
`#edit-scrim` for editing one, plus `#sheet` for the version history. A modal
is right here where a new screen is not: picking a setting is a step inside
starting a test, and navigating away from the sweep to choose one would lose
the technician's place.

**The gauge** is a 240 degree arc. The track length is the arc length, so bands
and the value are drawn by setting `stroke-dasharray` and `stroke-dashoffset`
on the same path rather than by recomputing trigonometry. Two details that are
easy to undo by accident: the value arc is hidden entirely at zero, because a
zero-length dash with a round cap still paints a dot; and the numeral is blank
rather than a placeholder glyph before the first result, because a large glyph
in a 64px mono face renders as a white block.

Styling is `static/hmi.css`, tokens from `branding/colors.json`, documented in
`branding/brand-guide.md`. `static/style.css` dresses the printable report and
nothing else.

## 8. Deployment Process

Target is a **Raspberry Pi 4 Model B** in a hard case with a 7 inch 1024x600
HDMI touchscreen and a USB-serial adapter: a standalone bench box that is also
reachable over the shop network. The full build, from blank SD card to kit, is
`docs/CableTester_SD_SETUP.md`.

**`deploy/setup-pi.sh` is the supported install.** One run, idempotent, and
re-running it is how a code update is applied. It reads the user and paths from
the account it runs as, so nothing is hardcoded to `/home/pi` any more and no
unit file needs hand-editing. It refuses to run from `/media` or `/mnt`, because
installing the service with its working directory on a USB stick produces a
tester that dies when the stick is removed.

What it installs:

- `deploy/cabletester.service`: systemd unit for the server, templated on
  `__CT_USER__`, `__CT_HOME__` and `__CT_DIR__`. `Group=dialout`, restart on
  failure, hardened with `NoNewPrivileges`, `ProtectSystem=full`,
  `ProtectHome=read-only` and a single `ReadWritePaths` for the profile file.
- `deploy/cabletester-kiosk.service`: a systemd **user** unit for Chromium.
  A user unit because it needs the graphical session. Deliberately not
  `systemctl --user enable`d: enabled that way it starts on login without the
  session environment a browser needs. It is started from within the session by
  the autostart entry, which runs `cabletester-mode boot`.
- `deploy/kiosk.sh`: launches Chromium full screen at localhost. Waits for the
  server to answer before opening the window (so a boot race does not land the
  kiosk on an error page) and clears the "did not shut down cleanly" bubble a
  power-cut bench box would otherwise show at every boot.
- `deploy/cabletester-mode`: the panel switch, installed to `/usr/local/bin`.

**Kiosk and network access are not two modes; they run together.** The panel is
locked to the tester on every boot while SSH and `0.0.0.0` binding stay up, so
the box is worked on over WiFi without disturbing what a tech sees. The only
real mode is what the attached panel shows: `cabletester-mode desk` drops to the
desktop, `kiosk` locks it back, and the choice survives a reboot because the
autostart entry consults a saved flag rather than starting the kiosk blindly.
`cabletester-mode status` reports the mode, the serial ports and the Pi's
throttling state.

**Screen blanking is set through `raspi-config nonint do_blanking 1`, not
`xset`.** Raspberry Pi OS Trixie runs labwc on Wayland, where `xset s off` does
nothing and fails silently. That silent failure looks exactly like a panel that
blanks mid-sweep for no reason, so `kiosk.sh` carries a comment forbidding the
xset calls being added back.

**Windows laptops** get `start-tester.bat` instead: it pulls from `main`, creates
the venv on a new PC, installs dependencies, starts the tester and opens the
browser once the server actually answers. Every step that needs the internet is
non-fatal, so a laptop with no connection still runs the copy it has. Static
assets are served with `SEND_FILE_MAX_AGE_DEFAULT = 0`, because this box updates
by git pull and a cached `style.css` after an update looks like a bug in the
tester.

**Installed and working on the kit, 8/23/2026.** `setup-pi.sh` ran clean on a
fresh Trixie image on a Pi 4, first attempt, no edits. Afterwards the service
was `active`, the page returned 200, and `static/fonts/fonts.css` returned 200,
which is the check that proves the vendored fonts are served locally. The
kiosk comes up on boot unattended, confirmed on the kit. The `desk` / `kiosk`
switch is installed and reports correctly but has not been exercised yet.

## 9. Build Status & Phases

| Phase | State |
|-------|-------|
| Repo scaffold, requirements, gitignore | Done |
| Pin check, matrix, per-pin verdicts | Done, simulator only |
| Topology detection and reference signatures | Done, simulator only |
| Baud sweep, both parity modes, live progress | Done, simulator only |
| Scoring, bands, plain-English verdict | Done |
| Flask app, SSE, job runner, cancel | Done |
| Printable report and JSON export | Done, serial only |
| Hardware simulator and test suite (76 tests) | Done |
| Polk branding, light and dark themes | Done (session 2) |
| Documentation set, CLAUDE.md, brand guide | Done (session 2) |
| Bench box: SD card, install script, kiosk, static IP | Done and verified on the Pi (session 3) |
| Fonts and icons vendored for offline operation | Done (session 3) |
| Ethernet link-speed ladder | Done. **Verified on hardware against a good cable only** |
| Learned known-good profiles | Removed (session 3), see §12 |
| Sweep settings: four named settings, patterns, passes | Done (session 3) |
| Continuity monitor, both protocols | Done. Rate measured on the kit, never run on a flexed cable |
| HMI rewrite for the 1024x600 panel | Done (session 3), flow reworked in 1.4.0 |
| Version history screen | Done (session 3) |
| **A bad cable, on either protocol** | **Never tested. This is the gate on calling the instrument trustworthy.** |
| `LINE_SETTLE_S` validated against a real adapter | Not started. See §14 |
| udev rule pinning the serial adapter | Not started, and wanted before the case is closed |
| Help section | Requested, not built |
| Ethernet export and report | Not built |

## 10. Session Log

### Session 1: Thursday, 8/20/2026. Build the instrument

Built the whole tool from the spec: repo scaffold, serial layer, scoring, profiles, Flask app with SSE, the UI, the printable report, deployment files, README, and a 34-test suite backed by a hardware simulator.

Decisions worth keeping:

- **The worker thread owns the port.** Considered tying port lifetime to the request and rejected it: a browser closing mid-test would leave the adapter locked, which is the exact failure mode the "guard against a port being held open" requirement was about.
- **A line must follow its output both up and down to count as connected.** The first cut only checked that it went high, which would have passed a line shorted to supply. Added a `stuck` state feeding a `short` verdict.
- **Straight-through and null modem are electrically indistinguishable through a symmetric loopback plug.** Worked through the pin paths: a null modem crosses 2/3, 7/8 and 4/6, and the plug crosses the same pairs straight back, so both produce an identical matrix. Shipped both signatures and had the tool report the ambiguity rather than guess. This is why the learn-from-known-good function matters more than the shipped signatures.
- **The 3-wire bug, found by testing rather than by reading.** Grading marked every absent handshake line `open`, so a valid 3-wire cable failed the pin check and could not be swept. Fixed by treating lines a matched reference expects to be absent as `nc`, with `dead` and `handshake_only` excluded so a cable with no data path still fails. Four tests now pin this down, including the case that must still fail (full handshake minus one line).
- **Rejected: aborting the sweep at the first failing rate.** The spec was explicit and it is right. The shape of the failure across rates is the diagnosis.
- **The simulator paces itself at real baud rates** (`realtime=True`, on for `--simulate`, off for tests so they stay fast). Without it a demo completed instantly and reported throughput in the megabits, which made the numbers meaningless.

### Session 2: Thursday, 8/20/2026. Polk branding and the documentation set

JP asked for the Polk-Demo repo to be used as the guide for both how to document a project and how the software should look.

Shipped:

- **Rebranded onto the Polk design system.** Tokens, both palettes, Barlow and Barlow Condensed, Tabler icons, 0.5px borders, 10px card radius, pill buttons, and the two-part header, all taken from the portal's `portal.css`. The printable report and the favicon match.
- **Documentation set in the Polk pattern:** this DOC, `CableTester_PICKUP.md`, `CLAUDE.md`, `branding/brand-guide.md` and `branding/colors.json`, plus a rewritten README.
- **Adopted JP's standing rules** from the Polk CLAUDE.md: no em dashes anywhere (97 were removed from code, comments and copy), and the standard display date format, implemented as `fmt_when()` in Python and `fmtWhen()` in JS with stored timestamps left as ISO.

Decisions worth keeping:

- **Dark default rather than the portal's light**, put to JP and confirmed. The portal follows the device; this box runs full screen on a shop bench, so it defaults to dark, does not track the device, and still remembers an explicit choice.
- **CDN fonts and icons with strong fallbacks**, put to JP and confirmed over vendoring the files. Keeps the repo free of font binaries and matches the portal exactly. The offline case is handled in code.
- **`document.fonts.check()` cannot detect a missing icon font.** Per spec it answers "can this text be rendered", and an unknown family falls back to a system font, so it returns true even when the stylesheet never loaded. The first implementation used it and reported icons present on a box where the CDN was demonstrably blocked. Detection now looks for the FontFace itself in `document.fonts`.
- **Jumper wire colours are a cool triad, not the brand accent.** The diagram colour-codes pins with green, amber and red for their result. The first cut used plum for the data jumper, which in dark mode is `#e3a9be`, close enough to the fail colour `#eea7a2` to read as a failed pin. Cyan, blue and violet are unmistakable against the status set.
- **Status colours are never plum and plum is never status.** Recorded in the brand guide because it is the rule most likely to get "tidied" by a future session trying to make the screen more on-brand.
- **Rejected: matching the portal's icon-only controls.** Every button here keeps a text label, so a missing icon font costs appearance and never meaning.

Verified this session: 34 tests pass; the full flow drives end to end in a real browser in both themes; the offline icon fallback was confirmed against the genuinely blocked CDN in the build sandbox; contrast ratios were measured, not estimated.

### Session 3: Sunday, 8/23/2026. The bench box: SD card, kiosk and offline operation

JP is assembling a portable kit in a Harbor Freight Apache 2800: a Pi, a 7 inch
touchscreen and a USB-serial adapter. He asked how to prepare an SD card, and
how to have WiFi available when he works on the box but a locked kiosk when
technicians use it.

Hardware settled during the session. He first offered a **Raspberry Pi 2 Model B
v1.1**, then worried it was wrong because it has no WiFi, then found he already
owned a **Pi 4 Model B**. The Pi 4 is the right board and the kit uses it.

Shipped:

- **`deploy/setup-pi.sh`**, the supported install. Idempotent, reads the user and
  paths from the account it runs as, refuses to run from removable media.
- **`deploy/cabletester-mode`** and **`deploy/cabletester-kiosk.service`**, the
  panel switch and the kiosk user unit.
- **`deploy/kiosk.sh` rewritten** for Wayland and touch.
- **`deploy/vendor-fonts.sh`** and **`static/fonts/`**: the fonts and icons now
  ship with the repo.
- **`docs/CableTester_SD_SETUP.md`**, the card-to-kit build guide.

Decisions worth keeping:

- **The WiFi question was the wrong question.** JP was about to buy hardware
  because the Pi 2 lacks WiFi, having also said the bench is fully offline. If
  the bench is offline, WiFi at the bench buys nothing; its only use is getting
  code onto the box, which is a one-time desk job. The real argument against the
  Pi 2 was never WiFi, it was Chromium on 1 GB of ARMv7. Worth remembering as a
  pattern: the stated blocker and the actual blocker were different things.
- **Kiosk and remote access are not two modes.** The instinct is to build a
  "tech mode" and a "dev mode" and switch between them. Unnecessary: the kiosk
  owns the panel, SSH and the `0.0.0.0` bind own the network, and they never
  interact. The only genuine mode is what the panel shows, which is why
  `cabletester-mode` has exactly one axis and the server is deliberately outside
  it. Dropping to the desktop cannot interrupt a sweep.
- **The mode survives a reboot through a flag file, not through systemd.** The
  autostart entry runs `cabletester-mode boot`, which reads the flag and decides.
  Enabling the user unit directly would start it on login without the session
  environment Chromium needs, and would also undo a `desk` choice at every boot.
- **`xset s off` is a trap on current Raspberry Pi OS.** Trixie runs labwc on
  Wayland, where the X11 tool does nothing and fails silently. Silent failure
  here presents as a panel that blanks part way through a sweep for no visible
  reason. Blanking is set through `raspi-config nonint do_blanking 1`, which
  works on both stacks, and `kiosk.sh` carries a comment forbidding the xset
  calls being restored.
- **Undervoltage is surfaced in `cabletester-mode status`, next to the port
  list.** This is the highest-value line in the whole deployment. A Pi browning
  out under load produces serial timing errors that are indistinguishable, on
  screen, from a marginal cable, and this instrument exists to judge marginal
  cables. Anything but `throttled=0x0` invalidates a bad result until the supply
  is fixed. The same reasoning drives the separate supply for the panel.
- **Reversed the session 2 CDN decision, on the condition it was waiting for.**
  Session 2 chose CDN fonts with fallbacks over vendoring, explicitly leaving
  vendoring open if the box turned out to have no internet route. It does. The
  templates now link only to `static/fonts/`. This is a reversal of a decision
  JP confirmed, made because the premise it rested on changed, not because the
  reasoning was wrong at the time.
- **The Tabler webfont is subset, not vendored whole.** The markup references
  exactly four icons: `ti-sun`, `ti-moon`, `ti-refresh` and `ti-plug-connected`.
  The full webfont is 452 KB for roughly 5,900 glyphs; the subset is 1,028 bytes.
  `vendor-fonts.sh` reads each codepoint out of the upstream CSS rather than
  hardcoding it, so an upstream renumbering cannot silently swap one glyph for
  another. Adding an icon to the UI means re-running that script.
- **jsDelivr is blocked from some networks, the npm registry is not.** The
  original `<link>` pointed at jsDelivr, which returned 403 through this
  environment's proxy. `vendor-fonts.sh` pulls the same artifact from the npm
  registry tarball instead. Worth knowing for any future asset fetch here.
- **`checkIcons()` was kept, not removed.** With a local font it should always
  pass, but it is now the safety net for a missing or corrupt file rather than
  for a blocked CDN. Its comment was rewritten to say so. The
  `document.fonts.check()` warning from session 2 is untouched.
- **Told honestly what is not known.** Auto-popping an on-screen keyboard when a
  web field takes focus is not reliable with Chromium on Linux under either
  display stack. One is installed, but the doc says plainly that it is unverified
  and that the physical keyboard in the case lid is the dependable path. The
  robust fix, an on-screen keyboard inside the web app, was flagged and not
  built: it is a change to the instrument, not to its deployment.

Rejected:

- **Buying a Pi 4 or Pi 5.** JP already owns one. Before that was known, the
  recommendation was still to keep using the Pi 2 rather than buy, on the
  grounds that DOC §14 bench validation is the blocking work and no board
  purchase advances it.
- **A filesystem overlay for power-cut protection.** It is the right instinct for
  a kiosk techs will yank the power on, but it would make `profiles.json`
  non-persistent and silently break the learned-profile feature. Parked as a
  real decision for JP rather than applied quietly.
- **Vendoring latin-ext.** The UI is English and cable IDs are ASCII. Latin only,
  at roughly 22 KB per weight.

Verified this session: 34 tests pass. The app was started in simulation and both
templates were fetched over HTTP to confirm every font file returns 200 with the
correct MIME type and that no CDN reference survives in the rendered page. The
em dash grep is clean.

**Then it was run on the Pi, in the same session.** What the hardware taught us:

- **`setup-pi.sh` ran clean on the first attempt**, no edits, on a Pi 4 Rev 1.2
  with 4 GB on a fresh Trixie image. Service `active`, page 200, fonts 200.
- **The panel needed no display configuration.** The `video=` kernel parameter
  written for section 3 of the setup doc was not required. It stays documented
  for a panel that behaves worse.
- **Touch worked with nothing installed**, once its cable was connected. The
  trap, which cost a round of debugging: **touch runs over its own USB cable and
  HDMI carries video only.** The desktop appeared normally while touch did
  nothing, because only HDMI and the panel's power were plugged in.
  Controller is WCH `1a86:e5e3`, claimed by `hid-multitouch`.
- **`wvkbd` was the on-screen keyboard that installed**, which confirms labwc on
  Wayland and confirms that removing the `xset` calls from `kiosk.sh` was right.
  They would have failed silently.
- **The expensive lesson was networking, and it is now in §11.** The Pi
  associated to WiFi, answered SSH, and showed healthy in the desktop while
  holding **no IPv4 address at all**. NetworkManager reported `connected`
  because IPv6 SLAAC had succeeded. The address was an `fd23::` unique local,
  which is not routable, so there was no internet, `apt` and `pip` both failed,
  and `run.py` binding `0.0.0.0` meant nothing on the network could reach the
  tester either. Diagnosing this ate most of the hardware session. The general
  rule worth carrying: **"SSH works" does not mean "the network works", and on
  this project the difference is load bearing.**
- **Fixed with a static address**, `192.168.1.240/24`, set through `nmtui`. This
  is the better end state regardless: a bench instrument's URL should not move
  because a DHCP lease did. Note that saving the setting is not enough, the
  connection has to be deactivated and reactivated.
- **Confirmed there is no RTC:** `timedatectl` reports `RTC time: n/a` and the
  clock had drifted to June 17th. This is the basis of the open decision in §12.
- **The long `nmcli` command was a usability failure on my part.** JP declined to
  type a four-line command with an embedded UUID at a Pi keyboard, correctly,
  since a typo in it is silent and hard to spot. `nmtui` was the right answer and
  should have been the first suggestion. Prefer menu-driven tools when the
  person is typing on the instrument rather than pasting.

- **The kiosk comes up on boot, unattended.** After a reboot the panel showed
  the tester full screen with no intervention. That closes the deployment end to
  end: image, install, service, autologin, autostart, kiosk.

- **The ethernet speed ladder ran on hardware and scored a real cable.** All
  three rungs linked, 100 and green, correct verdict, autonegotiation restored,
  10.7 seconds. **The first number this project has produced from hardware
  rather than a model**, and it arrived on a protocol that did not exist in the
  codebase this morning while the serial side, which is the reason the project
  exists, has still never met a cable. Worth noticing rather than glossing:
  building the new thing is more fun than validating the old one, and DOC §14
  is still undone.
- **Only a good cable has been through it.** That exercises the happy path.
  An instrument earns its keep by correctly failing bad cables, and no bad
  ethernet cable has been near it, so nobody has seen 62/amber or the blue and
  brown pairs named. Cutting one conductor of the blue pair on a spare lead is
  the whole test.

**Still not verified:** the `cabletester-mode` panel switch in actual use,
whether `wvkbd` ever appears on field focus, and whether `LINE_SETTLE_S`
survives a real adapter. DOC §14 remains the plan for the last one, and with the
box now built it is the only thing between this kit and a trustworthy
instrument.


### Session 4: Monday, 8/24/2026. The flow: ports in Setup, results on Test, continuity that reads

Shipped as **1.4.0**. Nothing new was added. The whole session went on making
what already existed behave the way a technician expects, which came out of JP
testing 1.3.0 on the panel and reporting three things that were wrong.

**"The ethernet test is stuck telling me to select the ports."** The bug was
architectural rather than cosmetic. Which ports the cable was on lived in a
`<select>` element that only the ethernet TEST screen drew, which meant the
selection was unreadable from every other screen and reset to nothing on every
render, and a screen here is rebuilt whole on every state change. So the test
screen asked for a selection, the selection was made, the screen redrew, and
the selection was gone. **Fixed by moving selection out of the DOM and into
`state`**, persisted to `localStorage`, which is where it always belonged.

That fix and JP's own instinct met in the middle: he asked for the port
selections to move into Setup "since we shouldn't be changing them", which is
exactly right for a kit where the connectors are wired into the case and never
change. The status bar now *reports* what is under test rather than offering it
again. One place to set it, and it is not a control the technician meets
mid-test.

**Results moved onto the TEST screen.** Starting a test on one screen and
having to go looking for the answer on another is a flow only its author
navigates without thinking. Each result line is now tappable and opens the
screen carrying the detail behind it, so the detail screens keep their job and
stop being the only route to the answer.

**Continuity: "it only counted 1 dropout" and "the test needs to be extremely
fast."** He was right and the cause was real. pyserial's `.cts`, `.dsr` and
`.dcd` are three separate `TIOCMGET` syscalls, so every "sample" was three
reads taken at three different instants, and a short dropout could land in the
seam between them and be missed. Replacing them with a single ioctl decoded
into all three bits took the rate from **119 to 1,267 samples/s**, measured on
the kit; a live run afterwards held 1,251 to 1,314. The floor now is the
adapter's 1 to 10 ms interrupt endpoint, which is honest and unbeatable, and
the screen states it: "sees breaks longer than 10 ms".

Added a `mon_tick` heartbeat and a timeline strip, because a monitor whose job
is to emit nothing until something goes wrong looks identical, on screen, to a
monitor that has crashed. The tick carries the running sample count, which is
also what lets the screen state the resolution the run achieved rather than one
it hoped for.

**Wording, at JP's direction and worth recording as a principle.** GOOD and
OPEN, never pass or fail. An open names the conductor *and its pin number*, and
shades it on the DB9 diagram in the shell the technician is holding. "Condemn
it" became "Repair the ends, or throw the cable away", which is what a person
at a bench actually does next. A verdict that a technician has to translate is
a verdict that gets ignored.

**One latent bug found while auditing every button:** the PINS heading was
hardcoded to "male view" while the toggle underneath it changed the drawing.
That is precisely the failure that sends someone to the wrong pin with a
soldering iron, and it survived because nobody reads a heading they wrote. Now
rule 18 in §15.

**Verification.** 76 unit tests pass. A 22-check Playwright drive of the panel
at 1024x600 completed with 0 failures and 0 console errors, which covers every
nav target and every button reachable from them.

**What did not happen, and is still the gate.** No bad cable has been through
this instrument on either protocol. The session was spent on flow because flow
was what JP could see was wrong; the thing he cannot see is that the instrument
has still only ever been shown cables that work. §14 is unmoved.


## 11. Troubleshooting Reference

**"COM3 is already open in another program." / "is in use or access was denied."**
Something else holds the port. PCCU is the usual culprit, including a minimised instance or one in the system tray. `_translate_serial_error()` turns the driver's error into this message plus a hint, rather than a stack trace. Windows reports a held port as an access error, which is why "access is denied" maps to busy rather than to permissions.

**"Permission denied opening /dev/ttyUSB0."**
Linux group membership. `sudo usermod -aG dialout $USER`, then log out and back in.

**No ports listed.**
Refresh re-scans. If still empty: the driver is not installed (Windows Device Manager), or the adapter is unplugged. The Pi's built-in UART needs freeing from the serial console first via `raspi-config`.

**Everything reads open, or topology says "No continuity".**
Nine times out of ten the loopback plug is not fitted or the cable is not seated. The `dead` reference's note says exactly this, so the UI tells the tech before they condemn the cable.

**A known-good cable shows spurious opens.**
Suspect `LINE_SETTLE_S` in `tester/serial_tests.py` before suspecting the cable. It is 120 ms, chosen without hardware, and USB-serial adapters vary widely in how fast they apply modem control line changes. Raise it and retest.

**On the Pi: everything looks connected but there is no internet, and apt and pip fail.**
Check IPv4 explicitly. A Pi can associate to WiFi, answer SSH, and show a healthy connection in the desktop while holding **no IPv4 address at all**, having taken only an IPv6 unique local address by SLAAC. `nmcli device status` still reports `connected`, because NetworkManager counts one address family as success, and SSH still works because mDNS resolves the hostname to the IPv6. But `fd00::/8` is not routable, so there is no internet, DNS fails because resolvers are IPv4, and `run.py` binding `0.0.0.0` means nothing on the network can reach the tester either. `ip -4 addr show wlan0` printing nothing is the tell. Fix with a static address via `sudo nmtui`, and remember that saving it is not enough: the connection has to be deactivated and reactivated. To get internet once for an install, an ethernet cable or Android USB tethering bypasses wireless DHCP entirely.

**On the Pi: a known-good cable starts failing the higher baud rates.**
Check the power before anything else. `cabletester-mode status` prints the Pi's throttling state; anything other than `throttled=0x0` means it has browned out or thermally throttled. An underfed Pi produces serial timing errors that are indistinguishable on screen from a marginal cable, which is the single most misleading failure this instrument has. Use a 5V 3A supply for the Pi and a separate supply for the panel, then retest before touching `LINE_SETTLE_S`.

**On the Pi: the panel blanks part way through a sweep.**
Set it with `sudo raspi-config`, Display Options, Screen Blanking, No. Do not use `xset s off`: it is an X11 tool, Raspberry Pi OS Trixie runs labwc on Wayland, and it fails silently there. The silent failure is the trap, because it looks exactly like the setting being ignored.

**On the Pi: the kiosk will not start when launched over SSH.**
A user unit started from an SSH shell has no idea which display to draw on, and Chromium exits immediately in a way that reads as a crash loop. Use `cabletester-mode kiosk`, which runs `systemctl --user import-environment` first, rather than `systemctl --user start` directly.

**Throughput figures look absurd (megabits at 1200 baud).**
That is the simulator with `realtime=False`, not a bug in the maths. Every cable in `SIM_CABLES` sets `realtime=True`; a bare `FakeCable()` in a test does not, and completes instantly.

**Icons render as blank squares or nothing.**
The Tabler CDN is unreachable and `checkIcons()` did not catch it. Check for `no-icons` on the `<html>` element. Every control still has its text label, so this is cosmetic.

**The page is unstyled or the fonts look wrong.**
Google Fonts is unreachable. The fallback stacks (system sans, system mono) take over. Layout is unaffected. If this becomes the normal state on the shop network, vendor the fonts, see §12.

**A test hangs at one baud rate.**
The transfer deadline is `expected * 2.5 + 1.0` seconds and the idle limit is `byte_time * 200`. Both are in `_transfer()`. A genuinely dead cable should hit the idle limit and record a timeout, not hang.

## 12. Open Questions & Deferred Decisions

**No bad cable has ever been through this instrument, on either protocol.** That is the single most important sentence in this document. The ethernet ladder has run on hardware and scored a real cable 100 and green, and the continuity monitor's sample rate was measured on the kit, so the claim "never run against real hardware" is no longer true as it stood. But **every hardware run so far used a good cable**, which exercises only the half of the job that does not matter. An instrument earns its keep by correctly failing bad cables, and nobody has yet seen this one do it. Cutting one conductor of the blue pair on a spare ethernet lead and expecting 62/amber with "4-5 and 7-8 (blue and brown)" named is the whole test, and it is an afternoon's work that keeps being displaced by building the next feature. Worth naming rather than glossing: building the new thing is more fun than validating the old one.

**The serial side has still never met a cable.** It is the reason the project exists and it is the least validated part of it. The test suite proves the logic against a model; it cannot validate a settle time, a driver quirk, or how a specific FTDI clone behaves. Treat every serial timing constant as a guess until §14 is done.

**`LINE_SETTLE_S` is unvalidated.** 120 ms. See §11.

**Straight-through versus null modem cannot be distinguished with this plug.** Not a gap in the code, a property of the wiring: the plug crosses back the same pairs a null modem crosses. The tool reports "straight-through or null modem" and says why. Distinguishing them would need an asymmetric plug (for instance data jumpered 2 to 3 but flow control looped within one connector), which is a different piece of hardware and a decision for JP. Do not "fix" this in software.

**Even parity is a timing stressor, not an independent parity check.** Both ends of the loopback are the same UART. Documented in §5 and scored as evidence rather than proof.

**Fonts and icons are vendored. This is settled, and the CDN is not coming back.** The bench box has no route to the internet, which is the condition this decision was waiting on. `static/fonts/` carries the latin subset of Barlow and Barlow Condensed plus a four-glyph Tabler subset, 178 KB in total, and the templates link only to it. `deploy/vendor-fonts.sh` regenerates the set. See §10, session 3.

**The bench box has no real-time clock, and every timestamp it writes will be wrong.** Found on the kit, 8/23/2026, not yet decided. A Pi 4 has no battery-backed RTC: it restores an approximate time at boot and corrects only when NTP reaches a network. The bench has no network by design. So `learned_at` in `profiles.json`, and `timestamp` and `exported_at` in the exports, and `printed_at` on a report a tech staples to a cable, will all carry a date that is wrong and drifts further with every power cycle. This is not a code bug; §5 and the storage format are correct. It is a gap in the kit. The usual fix is a DS3231 RTC module on the GPIO header, a few dollars and well supported on Trixie. Alternatives are accepting it and saying so on the report, or having the tester refuse to stamp a time it does not trust. **Do not pick one without JP.** Note that the GPIO header is otherwise unused by this project, and that using it for an RTC does not conflict with the standing rule against wiring RS-232 to those pins.

**The port label stops making sense once the adapter is captive in the case.** Raised by JP on 8/23/2026, not yet built. Today the UI shows `/dev/ttyUSB0` and offers a dropdown, which is right for a laptop where a tech plugs in whatever adapter is to hand. In the kit the USB-serial adapter is permanently installed, so there is exactly one and its kernel device path is jargon that means nothing to the person holding the cable. Three parts to this, and the third is the one that will actually bite:

1. **The label.** "Port `/dev/ttyUSB0`" should read as the adapter, not the device node. Something like "Serial adapter: FTDI FT232R" or just a connected indicator. The dropdown becomes a status line, since there is nothing to choose between.
2. **"Port" becomes ambiguous when ethernet is added.** A kit that tests both has a serial adapter and an ethernet interface. Whatever replaces this label has to survive that.
3. **`/dev/ttyUSB0` is not a stable name, and this is the real problem.** The number is assigned in enumeration order. Plug in a second USB-serial device, or have the captive adapter re-enumerate after a hub glitch, and it becomes `ttyUSB1` while the tester keeps looking at `ttyUSB0`. On a sealed kit that presents as the instrument spontaneously losing its adapter. The fix is a udev rule pinning the adapter to a stable symlink by its serial number or VID:PID, for instance `/dev/cabletester`, and having the tester prefer that. That rule belongs in `deploy/` and should be installed by `setup-pi.sh`. **Do this before the case is closed, not after the first mystery failure.**

**Learned known-good profiles: removed on 8/23/2026, JP's call and I agreed.** The feature stores a wiring signature from a pin check so a nonstandard-but-correct cable is recognised by name instead of reported "non-standard" every time. Three reasons it no longer earns its place, the first of which is new information rather than a change of mind:

1. **Its only interaction is typing a name into a `window.prompt()`.** That was fine when the tester ran on a laptop. The instrument now lives on a keyboardless 7 inch panel, which invalidates the premise the feature was built on.
2. **The label overpromises.** "Matches: XFC bench lead" reads as "as good as that cable" and only means "wired the same as that cable". The whole problem this instrument exists for is cables that are wired correctly and perform badly, so a label implying the opposite is worse than none.
3. **The gap is narrow and the cost is broad.** `BUILTIN_PROFILES` already covers straight-through, null modem and 3-wire, which is essentially every RS-232 cable in the field. The learned layer costs an API endpoint, a JSON store, the `CABLETESTER_PROFILES` variable, a list UI, delete buttons and a name prompt.

**This is not "delete `profiles.py`".** That module does two jobs and only one goes. `BUILTIN_PROFILES` and `identify()` stay: topology detection needs no user action and is the thing that produces "straight-through or null modem" and "3-wire". `ProfileStore`, `/api/profiles`, `profiles.json`, the environment variable and the Learn button go.

**What is lost:** a genuinely nonstandard cable reports "Non-standard" every time with its observed map shown. That is honest, not wrong.

**What would be worth building instead, if comparison is ever wanted:** a performance baseline, storing the sweep results of a trusted cable so the verdict can say "12 points below your reference, and it loses 57600 where the reference holds it". That is a statement about quality rather than wiring, needs no typed name, and is what "known-good" implies to everyone who reads it. Not built, not requested.

Done. `ProfileStore`, `/api/profiles`, `profiles.json`, the `CABLETESTER_PROFILES` variable, the `--profiles` flag and the `learned` parameter on `identify()` and `run_pin_check()` are all gone, along with their tests and the README section. `BUILTIN_PROFILES` and `identify()` remain: topology detection needs no user action and is what produces "straight-through or null modem" and "3-wire".

**Ethernet: the method is settled and verified, the mechanism is not what I first specified.** Probed on the kit 8/23/2026 with `deploy/eth-probe.sh`.

**Verified:** a patch cable from the Pi's `eth0` (bcmgenet) to a USB adapter on `eth1` (Realtek, r8152) negotiates 1000Mb/s full duplex. Two real PHYs across the cable under test, which beats a loopback plug on every axis: no fixture to build or lose, real bidirectional traffic, and it sidesteps a patch cable having a plug at both ends while the tester has jacks. **And the link honestly goes down when the cable is pulled**, which was the confound that mattered most: a test that passes on no cable is worse than no test.

**`ethtool --cable-test` is unsupported on both chips.** No reflectometry, no distance-to-fault, on either the Pi's PHY or the Realtek. Pair-level diagnosis has to come from which speeds link, which works because 10 and 100 use only pairs 1-2 and 3-6 while gigabit needs all four.

**Gigabit cannot be forced, and this changed the design.** `ethtool -s IF speed 1000 duplex full autoneg off` is silently downgraded to 100. That is not a driver fault: 1000BASE-T *requires* autonegotiation, because the standard uses it to settle which end is master and which is slave for clock recovery. There is no such thing as a forced gigabit link. The first probe duly reported "1000Mb offered, 100Mb/s negotiated" and looked like a bug. **The mechanism is to restrict what is advertised** (`autoneg on advertise 0x020` for 1000baseT/Full alone), which gets the same diagnostic honestly: offer one speed and the link either comes up at it or does not come up at all.

**Speed and Duplex are only meaningful while the link is up.** With the link down, `ethtool` echoes back the last configured value, which reads exactly like a negotiated result. The first unplugged run appeared to negotiate 10Mb and 100Mb with no cable in it. Any code reading these fields must gate on `Link detected: yes` first.

**The kit's own connectors become part of every ethernet measurement.** Raised while designing the enclosure, 8/23/2026, not yet addressed. Panel-mount RJ45s put two extra mated pairs and two internal pigtails in series with the cable under test. RS-232 at 115200 will not notice. **Gigabit will**, and the ladder's top rung is exactly where it shows up, so a kit with poor internal cabling would fail good cables at 1000 Mb and blame them. Two rules follow, both in `CableTester_ENCLOSURE.md` section 3: internal pigtails as short as will reach and not the cheapest leads, and **baseline the kit against a known-good short cable before it tests a single field cable**. If the kit cannot pass gigabit through its own connectors, no result it produces means anything.

**No authentication.** The server binds `0.0.0.0` with no login, by requirement, so a phone on the shop network can watch a test. Fine for a bench tool on a trusted network. If it ever moves somewhere less trusted, that decision needs revisiting rather than assuming.

**Results are not persisted server-side.** Jobs live in memory, capped at 40, and are lost on restart. Exports are the record. Nobody has asked for a history view; do not build one without JP raising it.

**Tailscale on the bench box: agreed in principle, deferred by JP on 8/23/2026.** JP already runs Tailscale on his PC. Putting it on the Pi would let him reach the kit for support from anywhere without depending on a local address, which is strictly better than remembering a static IP. It does **not** help at the bench itself, since Tailscale needs an internet route and the bench has none by design, so this buys remote support at his desk or a hotel and nothing at the point of use. Revisit after the box is built and validated.

**Parked, do not build without JP raising it:** a Totalflow protocol mode of any kind, testing more than one cable at once, a results database, cloud sync of learned profiles.

## 13. Brand / Design Reference

Full detail in `branding/brand-guide.md`, tokens in `branding/colors.json`. The short version:

- Palette and typography come from the Polk employee portal. POLK Plum `#7B2040`, lifted `#9B2D52`, Barlow and Barlow Condensed.
- Three additions this project needed: a warn colour (`--wn`), a monospace data stack with tabular figures, and three wire colours for the diagram.
- Three deliberate departures from the portal: dark default, the sticky bar carries controls rather than links, and icons degrade to unicode offline.
- **Status colours are never plum, and plum is never status.**

Re-check contrast if a token changes:

```python
def lum(h):
    h = h.lstrip('#'); c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
```

## 14. Planned: Bench Validation

Not started. This is the next real piece of work and everything else waits behind it. Ethernet has had a hardware session and serial has not, which makes the gap between the two the clearest signal of where the risk is.

What is needed: a DB9 loopback plug wired 2 to 3, 7 to 8, 4 to 1 to 6, a USB-serial adapter (ideally one genuine FTDI and one generic, to compare), a known-good cable, and a cable known to be bad.

What to check, in order:

1. Ports enumerate with sensible descriptions and VID:PID on both Windows and the Pi.
2. A known-good cable passes the pin check. If it shows spurious opens, tune `LINE_SETTLE_S` and record the value that works per adapter type.
3. The known-good matrix matches a shipped reference in `BUILTIN_PROFILES`, and the reported topology reads correctly to someone who did not build the tool.
4. A full sweep on the known-good cable is clean to 115200, and elapsed times per rate are close to the payload seconds setting.
5. The known-bad cable's failure appears at a plausible rate, and the score and verdict read sensibly to a technician who did not build the tool.
6. Pull the cable mid-sweep. Confirm timeouts are recorded, the sweep continues, and the port is released.
7. Open the port in PCCU, then start a test. Confirm the busy message appears rather than a stack trace.
8. Close the browser mid-sweep. Confirm the test completes server-side and the port is released.

Record the results in a session log entry and update §5 and §12 with anything the hardware disproves.

## 15. Maintenance Rules

Rules a future session should not have to rediscover. Each one cost something.

1. **Never use an em dash.** Anywhere. Grep before calling any writing task done.
2. **Timestamps shown to a person use the standard format;** stored timestamps stay ISO. Both helpers must stay in step. See `CLAUDE.md`.
3. **A serial port is only opened through `serial_tests.open_serial()`,** and every path that opens one closes it in a `finally`. Same for a network interface and `ethernet_tests.py`, which restores `ADV_ALL` in a `finally`. Do not open a port or change an interface from a route handler.
4. **Never claim a serial behaviour is verified unless it was verified on real hardware.** The simulator proves logic, not timing.
5. **A change to how a cable is graded needs the code, DOC §5, and the README's scoring section in the same commit.**
6. **Do not use `document.fonts.check()` to detect a missing font.** It answers "can this render", which fallback makes true. Look for the FontFace.
7. **Status colours are never plum and plum is never status.** Do not make the gauge more on-brand.
8. **Jumper wire colours stay a cool triad.** No warm hue: the diagram already uses green, amber and red for pin results.
9. **Every control keeps a text label.** Icons are decorative and may not load.
10. **Do not add Totalflow protocol support.** Out of scope by requirement, not by oversight.
11. **The sweep never aborts on the first failing rate,** and cancelled sweeps report coverage rather than a clean score.
12. **A 3-wire cable is a valid cable,** not a fault. Four tests pin this down; if they start failing, read §5 before "fixing" them.

13. **Nothing on the panel scrolls.** If a screen does not fit 1024x600, it is the wrong screen: split it or move something to Setup. Do not solve it with `overflow: auto`.
14. **Read modem lines with one ioctl, not one per line.** Three `getattr` reads are three syscalls at three instants and a dropout can fall between them. See §5c.
15. **Never force an ethernet speed; restrict what is advertised.** Forcing gigabit is silently downgraded to 100, because 1000BASE-T requires autonegotiation. See §5d.
16. **Gate any speed or duplex reading on carrier first.** With the link down, `ethtool` echoes the configured value and it reads exactly like a measurement.
17. **A continuity run that saw nothing is not a pass,** and the UI must keep saying so along with the resolution it actually achieved.
18. **Any heading that names a plug shell follows the shell toggle.** A fixed label over a drawing that changes sends a technician to the wrong pin.
19. **Version history is the only place in the UI allowed to talk about the past.** Everywhere else, the copy describes the instrument as it is. See `CLAUDE.md`.
20. **The Pi's clone tracks `claude/sd-card-raspberry-pi-jmub6p`.** Deleting that branch breaks `git pull` on the bench box. Re-point the clone before deleting it.
