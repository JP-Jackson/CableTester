# HMI mockup for the 7 inch panel

Design source for a proposed redesign of the tester UI, targeting the kit's
**1024x600 HDMI touchscreen**. Five screens, each exactly 1024x600, sized so
nothing ever scrolls.

**Nothing here ships.** The app in `templates/` and `static/` is untouched by
this directory. These are mockups for JP to react to, and the redesign has not
been approved or scoped.

## Why it looks the way it does

- **Left nav rail, not a bottom bar.** 1024 wide is generous, 600 tall is not.
  A bottom bar spends the scarce dimension; the rail spends width there is
  plenty of and returns all 600px of height.
- **Port and cable ID live in the status bar on every screen.** A tech should
  never navigate away to check what is under test.
- **Run and result share the TEST screen.** The gauge fills in after a run,
  so the home screen shows current state at rest. This is what keeps it to
  five tabs rather than six.
- **Touch targets:** 90px nav, 100px primary actions, 44px floor everywhere
  else.

Every colour, radius, border width and type size is lifted from
`static/style.css` and `branding/colors.json`. Nothing is rounded to a grid.
The `static/favicon.svg` mark in the rail is the Polk company mark, taken from
`JP-Jackson/Polk-Demo`.

## Regenerating

The five artboards share a chrome (rail and status bar) that a design canvas
cannot share between files, so it is generated rather than copied. Five
hand-maintained copies would drift within a day.

```bash
cd design/hmi
python3 build.py          # rewrites the five .dc.html files and canvas.json
```

Then re-seed and republish the canvas with the `design` skill. The seeded
`cabletester-hmi.html` is a 2.3 MB build output and is gitignored; only the
`.dc.html` sources, `canvas.json` and `build.py` are tracked.

## Sample content

The screens show a cable that is clean to 19200 with pin 8 open. That is
deliberate: a page of all-green proves nothing about how the amber and red
states read. The learned-profile names and dates are invented.
