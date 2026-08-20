# CableTester: read this first

## STYLE RULE: NEVER USE EM DASHES (—)

Not in code, not in comments, not in commit messages, not in UI text or copy, not in these project docs. This is JP's standing rule across every project. Use a period, comma, colon, semicolon, or parentheses instead.

Before treating any writing task as done, in this repo or in chat, grep your own new text for the em dash character. Don't rely on remembering the rule, check for it mechanically every time:

```bash
grep -rn "—" --include="*.py" --include="*.js" --include="*.css" --include="*.html" \
  --include="*.svg" --include="*.md" --include="*.sh" --include="*.service" . | grep -v "^./.git"
```

## DATE AND TIME FORMAT

JP's preferred format, standard everywhere a timestamp is shown to a person:

**`Monday, 8/17/2026 8:25 PM`**: long weekday, comma, numeric M/D/YYYY, then 12-hour time with AM/PM. Date only, where no time applies: **`Monday, 8/17/2026`**.

Build it by hand rather than with a locale option set, since none produces a long weekday with a numeric date and no comma before the time. This project has the helper written twice, once per language, and both must stay in step:

- Python: `fmt_when()` in `tester/app.py`
- JavaScript: `fmtWhen()` in `static/app.js`

Rules that go with it:
- **Pass `'en-US'` explicitly in JS, never `undefined`.** `undefined` uses the viewer's browser locale, so the same timestamp renders `17/08/2026` for anyone whose machine is not set to US English.
- **Never set a timezone.** Stored stamps are naive local ISO strings written by the same box that displays them.
- **Stored timestamps stay ISO, they are not display strings.** `timestamp`, `exported_at` and `learned_at` in the JSON exports and in `profiles.json` are records: they have to sort and parse. Only `printed_at` on the report, and the learned-profile list in the UI, get the human format.

## THE UI DESCRIBES THE INSTRUMENT AS IT IS, NEVER AS IT WAS

Everything a technician reads on screen or on a printed report is a manual for the tool in front of them, not a changelog.

Banned from visible copy in `templates/` and from any string the UI renders:
- Session numbers, version-to-version comparisons.
- "Previously", "formerly", "used to", "no longer", "anymore", "now that".
- Explaining a behaviour by describing the bug it replaced.

Write "The sweep unlocks once the pin check passes", not "The sweep now unlocks... previously it was locked for 3-wire cables too."

This does NOT cover code comments. Comments explaining why something is shaped the way it is are the point of the comment, and several of them here record decisions that cost real debugging time. Keep them.

Where change history belongs: `docs/CableTester_DOC.md` §10, the session log.

## Project docs

This project keeps its full context in `docs/`, not in this file:
- `docs/CableTester_PICKUP.md`: session handoff, read this first when picking the project back up.
- `docs/CableTester_DOC.md`: full project doc (architecture, test method, scoring, decisions, troubleshooting).
- `branding/brand-guide.md`: the palette, typography and the three places this tool deliberately departs from the Polk portal.

## Hardware reality check

This is a bench instrument. Two rules follow from that and neither is negotiable:

1. **Never claim a serial behaviour was verified unless it was verified on real hardware.** The whole test suite runs against `tester/simulator.py`, which is a model of a cable, not a cable. It proves the logic; it cannot prove a timing constant. Anything about settle times, driver quirks, or adapter behaviour is unverified until someone runs it on a real port, and the docs must say so.
2. **The port must always be closed.** Every path that opens a port closes it in a `finally`, including the cancel and exception paths. A leaked handle means the next test fails with a port-busy error and the tech blames the cable.

## Ending a session: the handover checklist

Run this whenever JP asks to wrap up, update the docs, hand over, end the session, or anything to that effect. **How he phrases it does not matter, and it does not depend on a slash command.** "Update all docs and handover" gets the same work as any other wording.

1. **Back up the DOC first**: copy `docs/CableTester_DOC.md` to `docs/CableTester_DOC_backup_YYYY-MM-DD.md` before editing it. Add `_2`, `_3` and so on for repeat backups the same day.
2. **Append a session log entry to the DOC** (§10), numbered and dated, covering what shipped, what was decided and why, and what was rejected and why. The reasoning is the part worth keeping; a list of file names is not.
3. **Refresh the DOC's affected sections, do not only append.** §3 (decisions), §5 (test method), §6 (API surface) and §7 (UI) go stale silently. Re-read them whenever a session touched the serial layer, the scoring, the API or the palette, and fix them in the same pass.
4. **Rewrite `docs/CableTester_PICKUP.md` wholesale**, do not patch it. It is a snapshot of current state, not a history. It must carry: what is blocking, what is pending, known gotchas, and the next steps in priority order.
5. **A change to the test method needs all three**: the code, the DOC's §5, and the README's "Interpreting the score". If a session changed how a cable is graded and only the code moved, the session is not done.
6. **Record new gotchas as rules**, not as narrative. A thing that cost an hour to diagnose belongs in Known Issues in one sentence that a future session will actually act on.
7. **Run the test suite and say the real result.** `.venv/bin/python -m unittest discover -s tests -t .` If something fails, the handover says so.
8. **Grep the new text for em dashes** before calling any of it done. See the rule at the top of this file.
9. **Commit and push** the doc changes with the rest of the work.

## Working style

**Discuss before building.** For anything beyond a one-line fix, new features, redesigns, anything with a real design decision in it, ask clarifying questions and state a plan first. Don't write code until JP says "build it," "go ahead," or similar. Skip this for small, unambiguous fixes.

**Be critical, not just agreeable.** When JP floats an idea, weigh it honestly and push back if it's scope creep, reverses an existing decision, or conflicts with something already documented. Recommend, don't just execute.

**Default to finishing over adding.** Get the instrument trustworthy on real hardware before adding features to it. When a new idea comes up mid-session, it's fine to discuss and design it, but flag if it's expanding scope rather than closing out what's in flight, and let JP decide.

**Recommend model and subagents before starting, and keep doing it as work shifts.** At the start of each task, before doing the work, say in a sentence or two: (a) whether the session's current model fits the task, and which one to switch to if not (JP switches via /model; Claude can only recommend). Rough guide: Haiku for mechanical sweeps and bulk file edits, Sonnet for routine well-scoped builds and high-volume pattern-following work, Opus or Fable for design judgment, tricky geometry or layout work, protocol and timing work, and debugging. (b) Whether subagents would genuinely help this task, and if so which agent type and model; otherwise say solo is better. Do this unprompted and repeatedly, at natural task boundaries, not just once at session start.

**If the session model is not the recommended one, STOP and ask which JP wants to use before doing the work.** Do not quietly proceed on a model that does not fit. Name the mismatch, say what the recommended model is and why it matters for this specific task, and wait. He may say carry on anyway, which is fine; the point is that it is his call, made knowingly.

The exception is trivial follow-ups inside a task he has already approved: there, note the mismatch in a line and keep going rather than halting again.
