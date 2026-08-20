# CableTester: Session Pickup Prompt

> **STYLE RULE, READ THIS BEFORE WRITING ANYTHING: NEVER USE EM DASHES.** Not in code, comments, commits, UI copy, or these docs. Grep your own new text before calling any writing task done. Full context: `CLAUDE.md` and DOC §15.

Read this file completely before doing anything. Then read the files listed under "Files to Read First."

**Last session:** 2 (Thursday, 8/20/2026). **Everything through session 2 is committed and pushed to `claude/new-session-yvi9co`.**

---

## Read this first: one thing governs everything else

**This instrument has never been connected to a real cable.** It is built, it is tested, and every one of those 34 tests runs against `tester/simulator.py`, which is a model of a cable written from the same understanding that wrote the code being tested. That proves the logic is self-consistent. It proves nothing about a real FTDI adapter, a real settle time, or a real degraded cable.

So:
- **Do not tell JP the tool "works" without qualifying it.** It works against a simulator.
- **`LINE_SETTLE_S = 120 ms` in `tester/serial_tests.py` is a guess.** It is the most likely thing to be wrong on real hardware. If a known-good cable shows spurious opens, that constant is the first suspect, not the cable.
- **The bench validation plan is DOC §14.** It is the highest-value next work and everything else is behind it.

---

## Project

- **Name:** CableTester
- **Purpose:** A bench instrument for verifying DB9 RS-232 cables used to connect laptops to ABB Totalflow XFC flow computers. Cables were failing in the field despite passing a continuity check, so this tests signal integrity at speed rather than DC continuity.
- **Scope boundary, hard:** bench testing one cable in isolation with a loopback plug. **No Totalflow protocol, ever, unless JP raises it.** No live XFC is contacted.
- **Stack:** Python 3.9+, `pyserial`, Flask, Server-Sent Events, plain HTML/CSS/JS with no build step. Barlow and Tabler icons by CDN.
- **Project folder:** `/home/user/CableTester`. **Docs:** `docs/`.
- **GitHub repo:** `JP-Jackson/CableTester`. Session branch: `claude/new-session-yvi9co`. Nothing has been merged to `main` yet and no PR has been opened. Ask JP before opening one.
- **Design system:** inherited from `JP-Jackson/Polk-Demo` (`portal.css`, `branding/`). If that repo's palette changes, this one should follow.

## Files to Read First

0. **`CLAUDE.md` first, not the docs.** It carries the rules that govern how you work here: the em dash rule, the date and time format, the "UI describes the instrument as it is" rule, the hardware reality check, and the end-of-session handover checklist. Any phrasing of "wrap up" runs that checklist.
1. **`docs/CableTester_DOC.md` §5 (Test Method) and §12 (Open Questions).** §5 is the specification for how a cable is graded and is the thing most likely to be changed carelessly. §12 is what is genuinely unresolved.
2. `tester/serial_tests.py`: the entire serial layer. Nothing else in the codebase opens a port. `LINE_SETTLE_S`, `_grade_pins()`, `_expected_absent()` and `_transfer()` are the parts with real reasoning behind them.
3. `tester/scoring.py`: the credit table and the verdict wording. Small and self-contained.
4. `tester/app.py`: Flask routes, the job runner, the SSE stream, and `fmt_when()`.
5. `tester/simulator.py`: the fake cable. Read this before trusting any test result, so you know what is actually being proven.
6. `branding/brand-guide.md`: the palette and the three deliberate departures from the Polk portal.
7. `static/app.js` and `static/style.css`: the front end. One stylesheet, no build step.

## What Session 2 Shipped

DOC §10 carries the full reasoning. Short version:

- Rebranded the whole UI onto the Polk design system: tokens, both palettes, Barlow and Barlow Condensed, Tabler icons, the two-part header, pill buttons, 0.5px borders. The printable report and favicon match.
- Added a theme toggle, defaulting to dark (JP confirmed) and persisting to `cabletester-theme`.
- Created the documentation set in the Polk pattern: DOC, this PICKUP, `CLAUDE.md`, `branding/brand-guide.md`, `branding/colors.json`, and a rewritten README.
- Adopted JP's standing rules: removed 97 em dashes from code, comments and copy; added the standard display date format in both Python and JS.
- Fixed two real bugs found while verifying, both recorded in DOC §10: the icon-font detection was a false positive (`document.fonts.check()` cannot do this), and the data jumper wire colour was close enough to the fail colour in dark mode to read as a failed pin.

## Pending Actions

In priority order.

1. **Run the bench validation in DOC §14.** Needs a loopback plug, a USB-serial adapter, a known-good cable and a known-bad one. Everything else waits on this. Tune `LINE_SETTLE_S` and record the working value per adapter type.
2. **Install on the actual Pi:** the systemd unit and kiosk script are written but have never been installed. The unit file parses, that is all.
3. **Decide on merging to `main`** and whether a PR is wanted.
4. **Verify the CDN question in the real deployment.** If the Pi has no internet route and the plainer offline look matters, vendor the fonts, see DOC §12. Nothing else changes if so.
5. **Get a technician who did not build this to read the verdict line** and say whether it means what it should.

## Known Issues / Gotchas

- **`document.fonts.check()` cannot detect a missing font.** Per spec it answers "can this text be rendered", and an unknown family falls back to a system font, so it returns true when nothing loaded. `checkIcons()` looks for the FontFace in `document.fonts` instead. Do not "simplify" it back.
- **Absurd throughput in the simulator** (megabits at 1200 baud) means `realtime=False` on that `FakeCable`, not a maths bug. The `SIM_*` cables set it true; bare `FakeCable()` in tests does not, so tests stay fast.
- **Chromium blocks some localhost ports** as unsafe (5060 is SIP, for instance) and returns `ERR_UNSAFE_PORT`. If a browser-driven check will not load the page, try a different `--port` before debugging the server.
- **`pkill -f "run.py"` in this environment kills the calling shell** and returns exit 144. Start test servers on a fresh port instead of killing the old one.
- **Straight-through and null modem read identically** through a symmetric loopback plug. This is physics, not a bug. The tool reports the ambiguity on purpose. Do not "fix" it in software, see DOC §12.
- **A 3-wire cable must pass the pin check** and reach the sweep. Its handshake lines grade `nc`, not `open`. Four tests pin this down. If they fail, read DOC §5 before changing them.
- **Both ends of the loopback are the same UART,** so the even-parity pass is a timing stressor, not an independent parity check. Do not oversell it in UI copy.

## Standing Rules (check every session, not just Next Steps)

1. **No em dashes anywhere.** Grep mechanically before finishing.
2. **Timestamps shown to a person use `Monday, 8/17/2026 8:25 PM`;** stored ones stay ISO. `fmt_when()` in Python and `fmtWhen()` in JS must stay in step.
3. **Only `tester/serial_tests.py` opens a port,** always closed in a `finally`.
4. **Never claim a serial behaviour is verified unless it was verified on real hardware.**
5. **A change to grading needs the code, DOC §5 and the README's scoring section in the same commit.**
6. **Status colours are never plum and plum is never status.** Do not make the gauge more on-brand.
7. **Every control keeps a text label.** Icons may not load.
8. **The sweep never aborts on the first failure.**
9. **Run the test suite before handing over and report the real result.**

## Environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t .    # 34 tests, no hardware needed
.venv/bin/python run.py --simulate                     # virtual cables, no hardware needed
```

Simulated ports: `SIM-GOOD`, `SIM-MARGINAL` (clean to 19200, fails above), `SIM-3WIRE`, `SIM-OPEN` (pin 8 broken).

**Secrets and environment variables:** none. The only environment variable is `CABLETESTER_PROFILES`, an optional path to the learned-profile JSON file. There is no authentication and no external service.

## Next Steps

1. Bench validation, DOC §14. Nothing else is worth doing first.
2. Install on the Pi, confirm systemd and kiosk work through a power cycle.
3. Feed anything the hardware disproves back into DOC §5 and §12.
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
| Deployment | `deploy/cabletester.service`, `deploy/kiosk.sh` |
