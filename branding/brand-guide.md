# RS-232 Cable Tester: Brand Guide

**Product:** RS-232 Cable Tester (bench instrument)
**Company:** Polk Production Technologies, Inc.
**Inherits from:** the Polk website and employee portal brand guide (`Polk-Demo/branding/brand-guide.md`)
**Last updated:** Thursday, 8/20/2026

This tool uses the Polk design system so it reads as company software rather than a one-off utility. The palette, typography and chrome all come from `portal.css`. Everything below either restates that system or documents a deliberate departure from it.

---

## Color Palette

### Primary Brand Color: POLK Plum

Sampled from the POLK Production Technologies oval logo background. Unchanged from the portal.

| Swatch | Name | Hex | Use |
|--------|------|-----|-----|
| ██ | POLK Plum | `#7B2040` | Primary accent: filled buttons, active states, the report's header rule |
| ██ | POLK Plum, lifted | `#9B2D52` | Hover and active state, accent text in light mode |

In dark mode the portal splits these: `--mr` deepens to `#8a2a4c` for filled buttons carrying white text, and `--ml` lifts to `#e3a9be` for accent text and links. This tool does the same.

### Neutrals

Straight from the portal, both modes. See `branding/colors.json` for the machine-readable set.

| CSS Var | Light | Dark | Role |
|---------|-------|------|------|
| `--bg` | `#F8F8F8` | `#282d35` | Page background |
| `--bg2` | `#EFEFEF` | `#343b45` | Surface (panels) |
| `--bg3` | `#E4E4E4` | `#414957` | Elevated surface, hover fills |
| `--b1` | `rgba(0,0,0,0.06)` | `rgba(255,255,255,0.12)` | Faint border |
| `--b2` | `rgba(0,0,0,0.12)` | `rgba(255,255,255,0.24)` | Default border |
| `--tx` | `#1A1A1A` | `#F5F6F7` | Primary text |
| `--mu` | `#666666` | `#BCC1C8` | Muted text |

### Status colors (this project's addition)

The portal has `--good` and `--bad`. A cable tester needs a third state, because "works but is degraded" is the single most useful thing this instrument reports, so `--wn` was added.

| CSS Var | Light | Dark | Meaning |
|---------|-------|------|---------|
| `--good` | `#216f41` | `#85d9a8` | Pass, clean, green health band |
| `--wn` | `#8a5a00` | `#e8c46f` | Open circuit, marginal rate, amber health band |
| `--bad` | `#ac3326` | `#eea7a2` | Short or cross, failed rate, red health band |

**Status is never plum, and plum is never status.** The accent carries brand, the status colors carry the verdict. A technician reading the gauge from arm's length has to know pass from fail on colour alone before reading a word.

### Wire colors (this project's addition)

The loopback diagram draws three jumper groups. They use a cool triad, deliberately **not** the brand accent.

| CSS Var | Light | Dark | Jumper |
|---------|-------|------|--------|
| `--wire-data` | `#0e7490` | `#67d5e8` | 2 to 3, data |
| `--wire-flow` | `#2f5fb0` | `#7fa8f5` | 7 to 8, flow control |
| `--wire-modem` | `#6b4ea8` | `#c4a2f5` | 4 to 1 to 6, modem status |

**Why not plum for the data jumper.** It was, in the first cut. The same diagram colour-codes each pin with its test result, so green, amber and red are already spoken for, and in dark mode the plum accent is `#e3a9be`, near enough to the fail colour `#eea7a2` that the data wire read as a failed pin. Cyan, blue and violet are unmistakable against the status set. Do not reintroduce a warm hue here.

---

## Typography

- **Primary font:** `'Barlow', sans-serif` for body text, labels and UI copy
- **Display font:** `'Barlow Condensed', sans-serif` for headings, the wordmark, buttons and the verdict line
- **Data font:** a monospace stack with tabular figures (`ui-monospace, 'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace`)
- **Source:** Google Fonts, same links as the portal
- **Section headings:** 1rem, weight 700, uppercase, letter-spacing 0.1em
- **Buttons:** 11px, weight 600, uppercase, letter-spacing 0.08em, pill radius
- **Field labels:** 10px, weight 500, uppercase, letter-spacing 0.12em
- **Body:** 12.5px to 15px

**Why a monospace stack exists here and not in the portal.** This screen is mostly columns of numbers: byte counts, error counts, bit error rates, throughput. Proportional digits do not line up, and a tech comparing 1,152 against 11,520 down a column needs them to. Barlow stays the voice of the tool; the mono face is for data only, and every table cell carrying a figure uses `font-variant-numeric: tabular-nums`.

---

## Departures from the portal

Three, all deliberate, all with a reason that is specific to a bench instrument.

**1. Dark is the default, not light.** The portal follows the device's light and dark setting and defaults to light. This tool defaults to dark and does not track the device. It runs full screen on a Raspberry Pi in a shop, often in a poorly lit building, and a kiosk that boots to a white screen is the wrong instrument. The toggle still works both ways and an explicit choice still persists, under the key `cabletester-theme`.

**2. The sticky bar carries controls, not links.** The portal's header is an identity strip that scrolls away over a sticky links bar. This is a single page with nowhere to navigate to, so the sticky bar carries the port selector and the cable ID instead: the two things a tech changes between cables, which have to stay reachable however far down the results run. The strip's welcome block becomes a live status readout, same shape, same right alignment.

**3. Icons degrade to unicode.** Tabler icons load from a CDN, exactly as the portal does. Unlike the portal, this box may sit on a shop network with no route to the internet. `checkIcons()` in `static/app.js` marks the document when the icon font is absent and `style.css` swaps in plain unicode glyphs. **No control in this UI relies on an icon to convey its meaning**: every button has a text label beside the icon. Keep it that way.

---

## Logo and naming

**Full name:** Polk Production Technologies, Inc. (the comma and the `Inc.` are both exact)
**Product name in the UI:** RS-232 Cable Tester

- **Header wordmark:** `Polk Production Technologies, Inc.` in `--tx`, followed by `RS-232 Cable Tester` in `--ml`. Same treatment as the portal's `Employee Portal` suffix.
- **Footer:** `© [Year] Polk Production Technologies, Inc.`
- **Report header:** the wordmark, then the report title, with a 3px plum rule under the block.
- **Favicon:** `static/favicon.svg`, a plum tile matching the company favicon with a DB9 shell mark rather than the PPT letterform, so the browser tab is distinguishable from the portal at a glance.

### Do not

- Use the old red maroon `#B22234`. It does not match the logo.
- Use the Knowledge Base value `#5a1d34`. This project uses `#7B2040`, like the website.
- Use plum for a pass or fail state, or a status colour for chrome.
- Recolour the health gauge to brand colours. Green, amber and red are load-bearing.

---

## Contrast Ratios (WCAG AA)

Measured against the ground each token is actually used on. All pass AA; most pass AAA.

| Foreground | Background | Ratio | Pass |
|------------|------------|-------|------|
| White `#FFF` | POLK Plum `#7B2040` | 9.89:1 | AAA |
| White `#FFF` | Plum dark `#8a2a4c` | 8.35:1 | AAA |
| `#1A1A1A` | Light page `#F8F8F8` | 16.39:1 | AAA |
| `#666666` | Light page `#F8F8F8` | 5.41:1 | AA |
| `#216f41` good | Light surface `#EFEFEF` | 5.35:1 | AA |
| `#8a5a00` warn | Light surface `#EFEFEF` | 5.15:1 | AA |
| `#ac3326` bad | Light surface `#EFEFEF` | 5.61:1 | AA |
| `#F5F6F7` | Dark page `#282d35` | 12.79:1 | AAA |
| `#BCC1C8` | Dark page `#282d35` | 7.65:1 | AAA |
| `#85d9a8` good | Dark surface `#343b45` | 6.72:1 | AAA |
| `#e8c46f` warn | Dark surface `#343b45` | 6.76:1 | AAA |
| `#eea7a2` bad | Dark surface `#343b45` | 5.75:1 | AA |

Re-check with the snippet in `docs/CableTester_DOC.md` §13 if any token changes.
