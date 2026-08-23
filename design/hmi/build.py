"""Generate the five HMI artboards for the 1024x600 panel.

Chrome (rail + status bar) is identical on every screen, so it is generated
rather than copied: an artboard canvas cannot share code between files, and
five hand-maintained copies would drift within a day.

Every value here is lifted from static/style.css and branding/colors.json.
Nothing is rounded to a grid.
"""
import pathlib, re

MARK = re.findall(r'<path d="([^"]+)"/>',
                  pathlib.Path("../../static/favicon.svg").read_text())
assert len(MARK) == 3

# Dark palette, html.dark in static/style.css.
BG, BG2, BG3 = "#282d35", "#343b45", "#414957"
B1, B2 = "rgba(255,255,255,0.12)", "rgba(255,255,255,0.24)"
TX, MU = "#f5f6f7", "#bcc1c8"
MR, ML = "#8a2a4c", "#e3a9be"
GOOD, WARN, BAD = "#85d9a8", "#e8c46f", "#eea7a2"
WDATA, WFLOW, WMODEM = "#67d5e8", "#7fa8f5", "#c4a2f5"

SANS = "'Barlow',system-ui,sans-serif"
DISP = "'Barlow Condensed','Barlow',system-ui,sans-serif"
MONO = "ui-monospace,'DejaVu Sans Mono',monospace"

ICONS = {
 "TEST":  '<path d="M4 17a9 9 0 1 1 16 0"/><path d="M12 17l4.6-5.2"/>',
 "PINS":  '<path d="M3 6h18l-1.6 12H4.6z"/><circle cx="7" cy="10" r="1.3"/><circle cx="11" cy="10" r="1.3"/><circle cx="15" cy="10" r="1.3"/><circle cx="19" cy="10" r="1.3"/><circle cx="9" cy="15" r="1.3"/><circle cx="13" cy="15" r="1.3"/><circle cx="17" cy="15" r="1.3"/>',
 "SWEEP": '<path d="M4 20V13"/><path d="M9 20V9"/><path d="M14 20v-4"/><path d="M19 20V5"/>',
 "WIRING":'<path d="M9 3v6"/><path d="M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0z"/><path d="M12 18v3"/>',
 "SETUP": '<path d="M4 8h9"/><path d="M19 8h1"/><path d="M4 16h4"/><path d="M14 16h6"/><circle cx="16" cy="8" r="2.4"/><circle cx="10" cy="16" r="2.4"/>',
}
NAV = ["TEST", "PINS", "SWEEP", "WIRING", "SETUP"]


def ico(name, color, size=26):
    return ('<svg viewBox="0 0 24 24" width="%d" height="%d" fill="none" stroke="%s" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
            % (size, size, color, ICONS[name]))


def rail(active):
    mark = ('<svg viewBox="0 0 100 100" width="40" height="40">'
            '<rect x="2" y="2" width="96" height="96" rx="22" fill="%s"/><g fill="#fff">%s</g></svg>'
            % (MR, "".join('<path d="%s"/>' % d for d in MARK)))
    out = []
    for n in NAV:
        on = n == active
        fg = TX if on else MU
        out.append(
            '<div style="position:relative;display:flex;flex-direction:column;align-items:center;'
            'justify-content:center;gap:5px;height:90px;border-radius:10px;'
            'background:%s">%s%s<span style="font-family:%s;font-weight:700;font-size:13px;'
            'letter-spacing:.14em;color:%s">%s</span></div>'
            % (MR if on else "transparent",
               ('<div style="position:absolute;left:-10px;top:14px;bottom:14px;width:3px;'
                'background:%s;border-radius:0 2px 2px 0"></div>' % ML) if on else "",
               ico(n, fg), DISP, fg, n))
    return ('<div style="width:132px;height:600px;flex-shrink:0;background:%s;'
            'border-right:0.5px solid %s;display:flex;flex-direction:column">'
            '<div style="height:78px;flex-shrink:0;display:flex;align-items:center;'
            'justify-content:center;border-bottom:0.5px solid %s">%s</div>'
            '<div style="display:flex;flex-direction:column;gap:4px;padding:12px 10px 0">%s</div>'
            '</div>' % (BG2, B2, B1, mark, "".join(out)))


def field(label, value, w):
    return ('<div style="width:%dpx;display:flex;flex-direction:column;gap:2px">'
            '<span style="font-family:%s;font-size:9px;font-weight:600;letter-spacing:.12em;'
            'text-transform:uppercase;color:%s">%s</span>'
            '<span style="font-family:%s;font-size:15px;color:%s">%s</span></div>'
            % (w, SANS, MU, label, MONO, TX, value))


def statusbar(state, dot):
    return ('<div style="height:64px;flex-shrink:0;background:%s;border-bottom:0.5px solid %s;'
            'display:flex;align-items:center;gap:26px;padding:0 22px">%s%s'
            '<div style="flex-grow:1"></div>'
            '<div style="display:flex;align-items:center;gap:9px;background:%s;'
            'border:0.5px solid %s;border-radius:50px;padding:9px 17px">'
            '<span style="width:9px;height:9px;border-radius:50%%;background:%s"></span>'
            '<span style="font-family:%s;font-size:11px;font-weight:600;letter-spacing:.09em;'
            'text-transform:uppercase;color:%s">%s</span></div></div>'
            % (BG2, B2, field("Port", "/dev/ttyUSB0", 148), field("Cable ID", "XFC-07", 108),
               BG3, B2, dot, SANS, TX, state))


def card(inner, pad=18, grow=False, extra=""):
    return ('<div style="background:%s;border:0.5px solid %s;border-radius:10px;padding:%dpx;'
            '%s%s">%s</div>' % (BG2, B2, pad, "flex-grow:1;min-height:0;" if grow else "", extra, inner))


def h2(text, right=""):
    return ('<div style="display:flex;align-items:baseline;justify-content:space-between;'
            'margin-bottom:12px"><span style="font-family:%s;font-weight:700;font-size:15px;'
            'letter-spacing:.13em;text-transform:uppercase;color:%s">%s</span>%s</div>'
            % (DISP, TX, text, right))


def btn(label, kind="ghost", h=96, sub=""):
    fill, fg, border = {
        "primary": (MR, "#fff", MR),
        "ghost":   ("transparent", MU, B2),
        "off":     ("transparent", "rgba(188,193,200,.42)", B1),
    }[kind]
    subline = ('<span style="font-family:%s;font-size:12px;font-weight:400;letter-spacing:.02em;'
               'text-transform:none;color:%s;margin-top:5px">%s</span>'
               % (SANS, "rgba(255,255,255,.72)" if kind == "primary" else MU, sub)) if sub else ""
    return ('<div style="height:%dpx;flex-shrink:0;background:%s;color:%s;border:0.5px solid %s;'
            'border-radius:50px;display:flex;flex-direction:column;align-items:center;'
            'justify-content:center;font-family:%s;font-size:16px;font-weight:600;'
            'letter-spacing:.11em;text-transform:uppercase">%s%s</div>'
            % (h, fill, fg, border, SANS, label, subline))


def page(active, state, dot, body):
    return ('<div style="width:1024px;height:600px;overflow:hidden;display:flex;background:%s;'
            'color:%s;font-family:%s">%s<div style="flex-grow:1;display:flex;flex-direction:column;'
            'min-width:0">%s<div style="flex-grow:1;min-height:0;overflow:hidden;padding:20px 22px;'
            'display:flex;gap:18px">%s</div></div></div>'
            % (BG, TX, SANS, rail(active), statusbar(state, dot), body))


HEAD = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;700;800&family=Barlow:wght@300;400;500;600&display=swap">
  <style>
    body { margin: 0; background: #282d35; }
    a { color: #e3a9be; } a:hover { color: #f5f6f7; }
  </style>
</helmet>
"""
TAIL = "\n</x-dc>\n</body>\n</html>\n"


def write(name, inner):
    pathlib.Path(name).write_text(HEAD + inner + TAIL)
    print("wrote", name)

# ---------------------------------------------------------------- TEST

def gauge(score, color):
    # 240 degree arc, r=110, centred (150,132). Arc length = 110 * 240deg in
    # radians = 460.77, so the value arc is a dash offset rather than trig.
    full = 460.77
    d = "M 54.7 187 A 110 110 0 1 1 245.3 187"
    return ('<svg viewBox="0 0 300 212" width="300" height="212">'
            '<path d="%s" fill="none" stroke="%s" stroke-width="17" stroke-linecap="round"/>'
            '<path d="%s" fill="none" stroke="%s" stroke-width="17" stroke-linecap="round" '
            'stroke-dasharray="%.1f %.1f"/>'
            '<text x="150" y="158" text-anchor="middle" font-family="%s" font-weight="800" '
            'font-size="96" fill="%s">%d</text></svg>'
            % (d, BG3, d, color, full * score / 100.0, full, DISP, color, score))


def screen_test():
    left = card(
        '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
        'height:100%%;gap:4px">%s'
        '<span style="font-family:%s;font-weight:700;font-size:13px;letter-spacing:.16em;'
        'text-transform:uppercase;color:%s">Health Score</span></div>' % (gauge(78, WARN), DISP, MU),
        grow=True, extra="width:348px;flex-grow:0;flex-shrink:0;")

    verdict = card(
        '<div style="font-family:%s;font-weight:700;font-size:30px;line-height:1.12;'
        'letter-spacing:.01em;color:%s">Usable, with<br>reservations</div>'
        '<div style="font-family:%s;font-size:15px;line-height:1.45;color:%s;margin-top:10px">'
        'Every pin passed. Clean to 19200 baud, errors above it. '
        'Fine for a 9600 link, not for 115200.</div>' % (DISP, WARN, SANS, MU))

    right = ('<div style="flex-grow:1;display:flex;flex-direction:column;gap:14px;min-width:0">'
             '%s<div style="flex-grow:1"></div>%s%s%s</div>'
             % (verdict,
                btn("Run Pin Check", "primary", 100, "Checks all nine pins. Two seconds."),
                btn("Run Baud Sweep", "ghost", 100, "Eight rates, both parities. About a minute."),
                btn("Cancel", "off", 62)))
    return page("TEST", "Ready", GOOD, left + right)


# ---------------------------------------------------------------- PINS

PINS = [(1, "DCD", "pass"), (2, "RXD", "pass"), (3, "TXD", "pass"), (4, "DTR", "pass"),
        (5, "GND", "ref"),  (6, "DSR", "pass"), (7, "RTS", "pass"), (8, "CTS", "open"),
        (9, "RI",  "nc")]
VERDICT = {"pass": ("Pass", GOOD), "open": ("Open", WARN), "short": ("Short", BAD),
           "ref": ("Ref", MU), "nc": ("Not used", MU)}


def db9():
    # Male shell, front view: top row 1..5 left to right, bottom row 6..9 inset.
    top = [(60 + i * 46, 62) for i in range(5)]
    bot = [(83 + i * 46, 108) for i in range(4)]
    pos = dict(zip([1, 2, 3, 4, 5], top))
    pos.update(dict(zip([6, 7, 8, 9], bot)))
    parts = ['<path d="M28 30 L272 30 L252 140 L48 140 Z" fill="none" stroke="%s" '
             'stroke-width="2.5" stroke-linejoin="round"/>' % B2]
    for n, sig, v in PINS:
        x, y = pos[n]
        col = VERDICT[v][1]
        parts.append('<circle cx="%d" cy="%d" r="13" fill="%s" fill-opacity="%s" stroke="%s" '
                     'stroke-width="2.5"/>' % (x, y, col, ".22" if v in ("ref", "nc") else ".30", col))
        parts.append('<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="13" '
                     'font-weight="600" fill="%s">%d</text>' % (x, y + 5, MONO, col, n))
    return '<svg viewBox="0 0 300 168" width="300" height="168">%s</svg>' % "".join(parts)


def screen_pins():
    left = card(
        h2("Plug, male view") +
        '<div style="display:flex;align-items:center;justify-content:center;margin-top:6px">%s</div>'
        '<div style="display:flex;gap:8px;margin-top:14px">%s%s</div>' % (
            db9(),
            '<div style="flex-grow:1;height:52px;border-radius:50px;border:0.5px solid %s;'
            'background:%s;display:flex;align-items:center;justify-content:center;font-family:%s;'
            'font-size:13px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#fff">'
            'Male</div>' % (MR, MR, SANS),
            '<div style="flex-grow:1;height:52px;border-radius:50px;border:0.5px solid %s;'
            'display:flex;align-items:center;justify-content:center;font-family:%s;font-size:13px;'
            'font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:%s">Female</div>'
            % (B2, SANS, MU)),
        extra="width:372px;flex-shrink:0;")

    rows = []
    for n, sig, v in PINS:
        label, col = VERDICT[v]
        rows.append(
            '<div style="height:44px;display:flex;align-items:center;gap:14px;'
            'border-bottom:0.5px solid %s">'
            '<span style="width:22px;font-family:%s;font-size:15px;color:%s">%d</span>'
            '<span style="width:56px;font-family:%s;font-size:15px;font-weight:500;color:%s">%s</span>'
            '<div style="flex-grow:1"></div>'
            '<span style="font-family:%s;font-size:12px;font-weight:700;letter-spacing:.09em;'
            'text-transform:uppercase;color:%s">%s</span>'
            '<span style="width:10px;height:10px;border-radius:50%%;background:%s"></span></div>'
            % (B1, MONO, MU, n, SANS, TX, sig, SANS, col, label, col))
    right = card(h2("Pin results", '<span style="font-family:%s;font-size:12px;font-weight:700;'
                    'letter-spacing:.09em;text-transform:uppercase;color:%s">1 open</span>'
                    % (SANS, WARN)) + "".join(rows), grow=True)
    return page("PINS", "Pin check done", WARN, left + right)

# ---------------------------------------------------------------- SWEEP

RATES = [(1200, "pass", "pass", "0", "1.17 kB/s"), (2400, "pass", "pass", "0", "2.34 kB/s"),
         (4800, "pass", "pass", "0", "4.69 kB/s"), (9600, "pass", "pass", "0", "9.37 kB/s"),
         (19200, "pass", "pass", "0", "18.7 kB/s"), (38400, "pass", "fail", "34", "31.2 kB/s"),
         (57600, "fail", "fail", "291", "12.4 kB/s"), (115200, "fail", "fail", "1,204", "3.1 kB/s")]


def chip(state):
    col, txt = (GOOD, "Pass") if state == "pass" else (BAD, "Fail")
    return ('<span style="display:inline-flex;align-items:center;justify-content:center;'
            'min-width:64px;height:30px;padding:0 13px;border-radius:50px;border:0.5px solid %s;'
            'font-family:%s;font-size:11px;font-weight:700;letter-spacing:.1em;'
            'text-transform:uppercase;color:%s">%s</span>' % (col, SANS, col, txt))


def screen_sweep():
    head = ('<div style="display:flex;align-items:center;height:32px;border-bottom:0.5px solid %s;'
            'font-family:%s;font-size:10px;font-weight:600;letter-spacing:.12em;'
            'text-transform:uppercase;color:%s">'
            '<span style="width:118px">Rate</span><span style="width:150px">No parity</span>'
            '<span style="width:150px">Even parity</span><span style="width:110px">Errors</span>'
            '<span style="width:130px">Throughput</span><span style="flex-grow:1">Quality</span>'
            '</div>' % (B2, SANS, MU))
    rows = []
    for rate, np_, ep, err, thr in RATES:
        ok = np_ == "pass"
        col = GOOD if ok and ep == "pass" else (WARN if ok else BAD)
        frac = 100 if ok and ep == "pass" else (52 if ok else 12)
        rows.append(
            '<div style="height:48px;display:flex;align-items:center;border-bottom:0.5px solid %s">'
            '<span style="width:118px;font-family:%s;font-size:17px;font-weight:600;color:%s">%s</span>'
            '<span style="width:150px">%s</span><span style="width:150px">%s</span>'
            '<span style="width:110px;font-family:%s;font-size:15px;color:%s">%s</span>'
            '<span style="width:130px;font-family:%s;font-size:15px;color:%s">%s</span>'
            '<span style="flex-grow:1;height:8px;border-radius:4px;background:%s;position:relative;'
            'margin-right:4px"><span style="position:absolute;left:0;top:0;bottom:0;width:%d%%;'
            'border-radius:4px;background:%s"></span></span></div>'
            % (B1, MONO, TX, "{:,}".format(rate), chip(np_), chip(ep),
               MONO, BAD if err != "0" else MU, err, MONO, MU, thr, BG3, frac, col))
    foot = ('<div style="display:flex;align-items:center;gap:16px;margin-top:14px">'
            '<span style="font-family:%s;font-weight:700;font-size:17px;letter-spacing:.02em;'
            'color:%s">Clean to 19200. Degrades above it.</span>'
            '<div style="flex-grow:1"></div>%s</div>'
            % (DISP, WARN, btn("Run again", "ghost", 52)))
    return page("SWEEP", "Sweep complete", WARN,
                card(h2("Baud sweep", '<span style="font-family:%s;font-size:12px;font-weight:700;'
                        'letter-spacing:.09em;text-transform:uppercase;color:%s">5 of 8 clean</span>'
                        % (SANS, MU)) + head + "".join(rows) + foot, grow=True))


# ---------------------------------------------------------------- WIRING

JUMPERS = [("2 to 3", "Data", WDATA), ("7 to 8", "Flow control", WFLOW),
           ("4 to 1 to 6", "Modem status", WMODEM)]


def plug(view):
    if view == "male":
        top, bot = [1, 2, 3, 4, 5], [6, 7, 8, 9]
    else:
        top, bot = [5, 4, 3, 2, 1], [9, 8, 7, 6]
    colour = {2: WDATA, 3: WDATA, 7: WFLOW, 8: WFLOW, 4: WMODEM, 1: WMODEM, 6: WMODEM}
    parts = ['<path d="M22 24 L242 24 L224 122 L40 122 Z" fill="none" stroke="%s" '
             'stroke-width="2.5" stroke-linejoin="round"/>' % B2]
    coords = {}
    for i, n in enumerate(top):
        coords[n] = (50 + i * 41, 52)
    for i, n in enumerate(bot):
        coords[n] = (70 + i * 41, 94)
    # Jumper links, drawn under the pins.
    for a, b, c in ((2, 3, WDATA), (7, 8, WFLOW), (4, 1, WMODEM), (1, 6, WMODEM)):
        (x1, y1), (x2, y2) = coords[a], coords[b]
        parts.append('<path d="M%d %d Q %d %d %d %d" fill="none" stroke="%s" stroke-width="2.5" '
                     'stroke-linecap="round"/>'
                     % (x1, y1, (x1 + x2) // 2, (y1 + y2) // 2 - 22, x2, y2, c))
    for n, (x, y) in coords.items():
        c = colour.get(n, MU)
        parts.append('<circle cx="%d" cy="%d" r="12" fill="%s" fill-opacity=".26" stroke="%s" '
                     'stroke-width="2.2"/>' % (x, y, c, c))
        parts.append('<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="12" '
                     'font-weight="600" fill="%s">%d</text>' % (x, y + 4, MONO, c, n))
    return '<svg viewBox="0 0 264 146" width="264" height="146">%s</svg>' % "".join(parts)


def screen_wiring():
    def shell(title, note, view):
        return card(h2(title) +
                    '<div style="display:flex;justify-content:center">%s</div>'
                    '<div style="font-family:%s;font-size:13px;line-height:1.45;color:%s;'
                    'margin-top:10px">%s</div>' % (plug(view), SANS, MU, note),
                    extra="flex-grow:1;min-width:0;")
    legend = "".join(
        '<div style="display:flex;align-items:center;gap:11px;flex-grow:1">'
        '<span style="width:26px;height:4px;border-radius:2px;background:%s"></span>'
        '<span style="font-family:%s;font-size:15px;color:%s">%s</span>'
        '<span style="font-family:%s;font-size:15px;color:%s">%s</span></div>'
        % (c, MONO, TX, pins, SANS, MU, name) for pins, name, c in JUMPERS)
    body = ('<div style="flex-grow:1;display:flex;flex-direction:column;gap:16px;min-width:0">'
            '<div style="display:flex;gap:16px;min-height:0">%s%s</div>%s</div>'
            % (shell("Male shell", "Pin numbers are moulded into the plastic. Go by those, not by position.", "male"),
               shell("Female shell", "The rows mirror left to right. Use this view when soldering a male shell.", "female"),
               card('<div style="display:flex;align-items:center;gap:24px">'
                    '<span style="font-family:%s;font-weight:700;font-size:14px;letter-spacing:.13em;'
                    'text-transform:uppercase;color:%s;width:96px">Jumpers</span>%s'
                    '<span style="font-family:%s;font-size:13px;color:%s">Pin 9 left open</span>'
                    '</div>' % (DISP, TX, legend, SANS, MU), pad=16)))
    return page("WIRING", "Reference", MU, body)

# ---------------------------------------------------------------- SETUP

PROFILES = [("Belden 9610, 6 ft", "Monday, 8/17/2026 3:12 PM"),
            ("Shop spare, grey", "Thursday, 8/20/2026 9:41 AM"),
            ("XFC bench lead", "Saturday, 8/22/2026 2:05 PM")]


def screen_setup():
    rows = "".join(
        '<div style="height:64px;display:flex;align-items:center;gap:14px;'
        'border-bottom:0.5px solid %s">'
        '<div style="display:flex;flex-direction:column;gap:3px;min-width:0;flex-grow:1">'
        '<span style="font-family:%s;font-size:16px;font-weight:500;color:%s">%s</span>'
        '<span style="font-family:%s;font-size:12px;color:%s">Learned %s</span></div>'
        '<div style="width:44px;height:44px;border-radius:50%%;border:0.5px solid %s;'
        'display:flex;align-items:center;justify-content:center">'
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="%s" stroke-width="1.7" '
        'stroke-linecap="round"><path d="M5 7h14"/><path d="M10 11v6"/><path d="M14 11v6"/>'
        '<path d="M6 7l1 12h10l1-12"/><path d="M9 7V4h6v3"/></svg></div></div>'
        % (B1, SANS, TX, name, SANS, MU, when, B2, MU) for name, when in PROFILES)

    left = card(
        h2("Known-good profiles",
           '<span style="font-family:%s;font-size:12px;font-weight:700;letter-spacing:.09em;'
           'text-transform:uppercase;color:%s">3 saved</span>' % (SANS, MU))
        + rows
        + '<div style="margin-top:16px">%s</div>' % btn("Learn this cable", "ghost", 62),
        grow=True)

    def stepper(label, value, unit):
        sq = ('<div style="width:52px;height:52px;border-radius:50%%;border:0.5px solid %s;'
              'display:flex;align-items:center;justify-content:center;font-family:%s;font-size:26px;'
              'font-weight:300;color:%s">%s</div>')
        return ('<div style="display:flex;flex-direction:column;gap:9px">'
                '<span style="font-family:%s;font-size:10px;font-weight:600;letter-spacing:.12em;'
                'text-transform:uppercase;color:%s">%s</span>'
                '<div style="display:flex;align-items:center;gap:14px">%s'
                '<span style="font-family:%s;font-size:26px;color:%s;min-width:74px;'
                'text-align:center">%s<span style="font-size:15px;color:%s"> %s</span></span>%s</div>'
                '</div>' % (SANS, MU, label, sq % (B2, SANS, TX, "&#8722;"),
                            MONO, TX, value, MU, unit, sq % (B2, SANS, TX, "+")))

    right = card(
        h2("Options")
        + stepper("Payload per rate", "2.0", "s")
        + '<div style="height:1px;background:%s;margin:20px 0"></div>' % B1
        + '<div style="display:flex;flex-direction:column;gap:9px">'
          '<span style="font-family:%s;font-size:10px;font-weight:600;letter-spacing:.12em;'
          'text-transform:uppercase;color:%s">Display</span>'
          '<div style="display:flex;gap:8px">'
          '<div style="flex-grow:1;height:52px;border-radius:50px;background:%s;border:0.5px solid %s;'
          'display:flex;align-items:center;justify-content:center;font-family:%s;font-size:13px;'
          'font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#fff">Dark</div>'
          '<div style="flex-grow:1;height:52px;border-radius:50px;border:0.5px solid %s;'
          'display:flex;align-items:center;justify-content:center;font-family:%s;font-size:13px;'
          'font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:%s">Light</div>'
          '</div></div>' % (SANS, MU, MR, MR, SANS, B2, SANS, MU)
        + '<div style="flex-grow:1"></div>'
        + '<div style="display:flex;gap:10px;margin-top:20px">'
          '<div style="flex-grow:1">%s</div><div style="flex-grow:1">%s</div></div>'
          % (btn("Export JSON", "ghost", 62), btn("Print report", "primary", 62)),
        grow=True, extra="width:392px;flex-grow:0;flex-shrink:0;display:flex;flex-direction:column;")
    return page("SETUP", "Ready", GOOD, left + right)


write("Main.dc.html", screen_test())
write("Pins.dc.html", screen_pins())
write("Sweep.dc.html", screen_sweep())
write("Wiring.dc.html", screen_wiring())
write("Setup.dc.html", screen_setup())

import json
gap_x, row = 1024 + 90, 600 + 150
pathlib.Path("canvas.json").write_text(json.dumps({
    "artboards": [
        {"file": "Main.dc.html",   "x": 0,          "y": 0,   "w": 1024, "h": 600},
        {"file": "Pins.dc.html",   "x": gap_x,      "y": 0,   "w": 1024, "h": 600},
        {"file": "Sweep.dc.html",  "x": gap_x * 2,  "y": 0,   "w": 1024, "h": 600},
        {"file": "Wiring.dc.html", "x": 0,          "y": row, "w": 1024, "h": 600},
        {"file": "Setup.dc.html",  "x": gap_x,      "y": row, "w": 1024, "h": 600},
    ],
    "annotations": [
        {"id": "brief", "x": gap_x * 2, "y": row, "w": 420,
         "text": "Every screen is exactly 1024x600 and nothing scrolls.\n\n"
                 "Left rail keeps navigation out of the 600px of height, which is the "
                 "scarce dimension. Status bar carries port and cable ID on every screen, "
                 "so the tech never navigates to find what is under test.\n\n"
                 "Touch targets: 90px nav, 100px primary actions, 44px minimum everywhere.\n\n"
                 "Content is sample. Cable shown is clean to 19200 with pin 8 open."},
    ],
    "launch": {"view": "canvas"},
}, indent=2))
print("wrote canvas.json")
