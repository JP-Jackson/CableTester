/* CableTester HMI.
   ---------------------------------------------------------------------
   Drives the instrument's own screen on the kit's 1024x600 panel.

   Two rules shape all of it.

   NOTHING SCROLLS. Content that will not fit gets its own screen rather
   than more height. Screens are built here rather than written into the
   template because the nav and its contents change with the protocol, and
   two hand-maintained sets would drift within a week.

   MEANING NEVER DEPENDS ON COLOUR ALONE. Every verdict carries a word as
   well as a hue, because a technician may be colour blind, the panel may be
   viewed at an angle, and the printed report is read in a truck.
   --------------------------------------------------------------------- */

const $ = (id) => document.getElementById(id);
const DASH = "-";   // never an em dash, see CLAUDE.md

const PARITY_ORDER = { none: 0, even: 1 };
const RESULT_LABEL = { nc: "not used", reference: "ref", pass: "pass",
                       open: "open", short: "short", cross: "cross" };
const RESULT_TONE = { pass: "g", reference: "m", nc: "m", open: "w",
                      short: "r", cross: "r" };

const state = {
  proto: "SERIAL",
  screen: "TEST",
  // Which port the cable under test is on. In state, not in the DOM: a screen
  // is rebuilt whole on every change, so a <select> lost its value on each
  // render and could not be read at all from a screen that did not draw it.
  // That was the "pick both ports" bug. Persisted, because in the kit these
  // are fixed by the wiring and should survive a power cycle.
  port: null,
  ethA: null,
  ethB: null,
  dark: true,
  shell: "male",
  ports: [],
  ifaces: [],
  ethCanTest: true,
  pinJob: null,       // set only when the pin check PASSED; gates the sweep
  lastPinJob: null,   // set either way; gates export
  sweepJob: null,
  running: null,
  stream: null,
  pinResult: null,
  sweepRates: {},
  score: null,
  ethRungs: [],
  ethScore: null,
};

/* ------------------------------------------------------------- plumbing */

async function api(url, options) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch (_) { /* empty body */ }
  if (!response.ok) {
    const error = new Error(body.error || `${response.status} ${response.statusText}`);
    error.hint = body.hint || "";
    throw error;
  }
  return body;
}

function fmt(n, digits) {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH;
  return Number(n).toFixed(digits === undefined ? 1 : digits);
}

function fmtBps(bps) {
  if (!bps && bps !== 0) return DASH;
  if (bps >= 1000) return `${fmt(bps / 1000, 2)} kB/s`;
  return `${fmt(bps, 0)} B/s`;
}

/* Kept in step with fmt_when() in tester/app.py. Both must produce
   "Monday, 8/17/2026 8:25 PM". 'en-US' is passed explicitly and never left
   undefined: undefined uses the viewer's browser locale, so the same stamp
   renders 17/08/2026 for anyone whose machine is not set to US English. */
function fmtWhen(iso) {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const weekday = d.toLocaleDateString("en-US", { weekday: "long" });
  const hour = d.getHours() % 12 || 12;
  const mins = String(d.getMinutes()).padStart(2, "0");
  const ampm = d.getHours() < 12 ? "AM" : "PM";
  return `${weekday}, ${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()} ${hour}:${mins} ${ampm}`;
}

function setLamp(cls) { $("lamp").className = "lamp" + (cls ? " " + cls : ""); }
function setState(text) { $("state").textContent = text; }

function showAlert(message, hint, kind) {
  const host = $("screens");
  clearAlert();
  const el = document.createElement("div");
  el.className = "alert" + (kind === "info" ? " info" : "");
  el.id = "alert";
  el.innerHTML = `<div style="flex-grow:1;min-width:0"><b></b><span></span></div>
                  <button aria-label="Dismiss">&times;</button>`;
  el.querySelector("b").textContent = message;
  el.querySelector("span").textContent = hint || "";
  el.querySelector("button").onclick = clearAlert;
  host.appendChild(el);
}
function clearAlert() { const a = $("alert"); if (a) a.remove(); }

function closeStream() {
  if (state.stream) { state.stream.close(); state.stream = null; }
}

function follow(jobId, kind, handlers) {
  closeStream();
  const source = new EventSource(`/api/events/${jobId}`);
  state.stream = source;
  for (const [name, handler] of Object.entries(handlers)) {
    if (name === "finished") continue;
    source.addEventListener(name, (event) => handler(JSON.parse(event.data)));
  }
  source.addEventListener("job_end", (event) => {
    const data = JSON.parse(event.data);
    closeStream();
    setRunning(null);
    if (data.state === "error") {
      showAlert(data.error.message, data.error.hint);
      setLamp("bad"); setState("Error");
    } else if (data.state === "cancelled") {
      showAlert("Test cancelled.", "", "info");
      setState("Cancelled");
    } else {
      setState("Done");
    }
    if (handlers.finished) handlers.finished(data);
  });
  source.onerror = () => {
    // The stream ends when the job ends; only surface a real mid-run drop.
    if (state.running === kind && source.readyState === EventSource.CLOSED) {
      closeStream(); setRunning(null);
      showAlert("Lost the event stream.",
                "The test may still be running. Reload the page.");
    }
  };
}

function setRunning(kind) {
  state.running = kind;
  setLamp(kind ? "busy" : (state.score || state.ethScore ? "ok" : null));
  render();
}

async function cancelRunning() {
  if (!state.running || !state.currentJob) return;
  try { await api(`/api/cancel/${state.currentJob}`, { method: "POST" }); }
  catch (err) { showAlert(err.message, err.hint); }
}

/* ------------------------------------------------------------ chrome */

const ICON = {
  TEST:'<path d="M4 17a9 9 0 1 1 16 0"/><path d="M12 17l4.6-5.2"/>',
  PINS:'<path d="M3 6h18l-1.6 12H4.6z"/><circle cx="7" cy="10" r="1.3"/><circle cx="11" cy="10" r="1.3"/><circle cx="15" cy="10" r="1.3"/><circle cx="19" cy="10" r="1.3"/><circle cx="9" cy="15" r="1.3"/><circle cx="13" cy="15" r="1.3"/><circle cx="17" cy="15" r="1.3"/>',
  SWEEP:'<path d="M4 20V13"/><path d="M9 20V9"/><path d="M14 20v-4"/><path d="M19 20V5"/>',
  PAIRS:'<path d="M3 7h18"/><path d="M3 11h18"/><path d="M3 16h18"/><path d="M3 20h18"/><circle cx="7" cy="7" r="1.1"/><circle cx="7" cy="11" r="1.1"/><circle cx="7" cy="16" r="1.1"/><circle cx="7" cy="20" r="1.1"/>',
  WIRING:'<path d="M9 3v6"/><path d="M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0z"/><path d="M12 18v3"/>',
  SETUP:'<path d="M4 8h9"/><path d="M19 8h1"/><path d="M4 16h4"/><path d="M14 16h6"/><circle cx="16" cy="8" r="2.4"/><circle cx="10" cy="16" r="2.4"/>'
};
ICON.SPEED = ICON.SWEEP;
ICON.CONTINUITY = '<path d="M2 12c3-6 5 6 8 0s5 6 8 0 4-3 4-3"/>';

const NAV = {
  SERIAL:   ["TEST", "PINS", "SWEEP", "CONTINUITY", "WIRING", "SETUP"],
  ETHERNET: ["TEST", "PAIRS", "SPEED", "CONTINUITY", "WIRING", "SETUP"],
};

/* Gauge: a 240 degree arc. The dash length is the arc length, so the value
   is set by dash offset rather than by recomputing trigonometry. */
const ARC_PATH = "M 54.7 187 A 110 110 0 1 1 245.3 187";
const ARC_LEN = 460.77;
const BAND_VAR = { green: "--good", amber: "--wn", red: "--bad" };

function gauge(score, band) {
  const has = score !== null && score !== undefined;
  const colour = has ? `var(${BAND_VAR[band] || "--mu"})` : "var(--bg3)";
  const dash = has ? (ARC_LEN * score) / 100 : 0;
  return `<svg viewBox="0 0 300 206" style="width:100%;max-width:296px">
    <path d="${ARC_PATH}" fill="none" stroke="var(--bg3)" stroke-width="17" stroke-linecap="round"/>
    <path d="${ARC_PATH}" fill="none" stroke="${colour}" stroke-width="17" stroke-linecap="round"
          stroke-dasharray="${dash} ${ARC_LEN}"/>
    <text x="150" y="156" text-anchor="middle" font-family="var(--disp)" font-weight="800"
          font-size="92" fill="${has ? colour : 'var(--mu)'}">${has ? Math.round(score) : DASH}</text>
  </svg>`;
}

function card(inner, style) {
  return `<div class="card" style="${style || ""}">${inner}</div>`;
}
function h2(text, right) {
  return `<h2>${text}${right ? `<em>${right}</em>` : ""}</h2>`;
}
function btn(id, label, opts) {
  const o = opts || {};
  const cls = ["btn", o.kind || "", o.big ? "big" : "", o.disabled ? "off" : ""].join(" ");
  const sub = o.sub ? `<small>${o.sub}</small>` : "";
  return `<button class="${cls}" id="${id}" style="${o.style || ""}">${label}${sub}</button>`;
}
function empty(text) { return `<div class="empty">${text}</div>`; }

/* ---------------------------------------------------------- DB9 diagram */

/* `view` mirrors the rows. A male shell seen from the front runs 1..5 left to
   right along the top; a female runs 5..1, because you are looking at the
   other face of the same connector. Getting this wrong sends a technician to
   the wrong pin, so the shell is always labelled on screen and never implied. */
function shellToggle() {
  const b = (v, label) =>
    `<button class="btn ${state.shell === v ? "primary" : ""}" data-shell="${v}"
      style="flex-grow:1;height:46px">${label}</button>`;
  return `<div class="row">${b("male", "Male shell")}${b("female", "Female shell")}</div>`;
}

function db9(pins, view, highlight) {
  const byPin = {};
  (pins || []).forEach((p) => { byPin[p.pin] = p; });
  const hot = new Set(highlight || []);
  const female = view === "female";
  const top = female ? [5, 4, 3, 2, 1] : [1, 2, 3, 4, 5];
  const bottom = female ? [9, 8, 7, 6] : [6, 7, 8, 9];
  const pos = {};
  top.forEach((n, i) => { pos[n] = [60 + i * 46, 58]; });
  bottom.forEach((n, i) => { pos[n] = [83 + i * 46, 104]; });
  let out = `<path d="M28 26 L272 26 L252 136 L48 136 Z" fill="none"
             stroke="var(--b2)" stroke-width="2.5" stroke-linejoin="round"/>`;
  for (const n of Object.keys(pos)) {
    const [x, y] = pos[n];
    const res = byPin[n] ? byPin[n].result : null;
    const tone = hot.has(Number(n)) ? "r" : (res ? RESULT_TONE[res] || "m" : null);
    const c = tone ? `var(${{ g: "--good", w: "--wn", r: "--bad", m: "--mu" }[tone]})`
                   : "var(--mu)";
    const solid = hot.has(Number(n)) || (res && tone !== "m");
    out += `<circle class="pin" cx="${x}" cy="${y}" r="13" fill="${c}"
             fill-opacity="${solid ? '.34' : '.14'}" stroke="${c}"
             stroke-width="${hot.has(Number(n)) ? 3.2 : 2.4}"/>
            <text x="${x}" y="${y + 5}" text-anchor="middle" font-family="var(--mono)"
             font-size="13" font-weight="600" fill="${c}">${n}</text>`;
  }
  return `<svg viewBox="0 0 300 160" style="width:100%;max-width:300px">${out}</svg>`;
}

/* ------------------------------------------------------ serial screens */

function verdictInline() {
  const v = verdictParts();
  return `<div style="text-align:center;padding:0 4px">
    <div class="verdict" style="font-size:22px;${v.tone}">${v.text}</div>
    <div class="verdict-sub" style="font-size:13px">${v.sub}</div></div>`;
}

function verdictParts() {
  const s = state.score;
  const pin = state.pinResult;
  let text, sub, tone = "";
  if (s) {
    text = s.verdict;
    tone = `color:var(${BAND_VAR[s.band]})`;
    sub = `Scored across ${s.per_rate.length} rate(s), ${s.coverage}% of the ` +
          `weighted range. Higher rates count for more.`;
  } else if (pin && !pin.passed) {
    text = "Pin check failed. The cable has a wiring fault.";
    tone = "color:var(--bad)";
    sub = pin.summary;
  } else if (pin) {
    text = "Pin check passed. Run the sweep for a health score.";
    sub = pin.summary;
  } else {
    text = "Ready.";
    sub = "Fit the loopback plug to the far end of the cable, then run the pin check.";
  }
  return { text, sub, tone };
}


/* The result rows are the change JP asked for: the test screen is where you
   run a test, so it is where the answer belongs. Each row is the headline
   only, and tapping it goes to the screen that has the detail. Nobody should
   have to go looking for the result of the thing they just started. */
function resultRow(label, value, tone, target) {
  const colour = tone ? `var(${{ g: "--good", w: "--wn", r: "--bad", m: "--mu" }[tone]})` : "var(--mu)";
  return `<button class="trow" data-goto="${target}" style="width:100%;background:transparent;
      border:0;border-bottom:0.5px solid var(--b1);cursor:pointer;text-align:left;height:46px">
    <span style="width:104px;font-family:var(--disp);font-weight:700;font-size:12px;
      letter-spacing:.13em;text-transform:uppercase;color:var(--mu)">${label}</span>
    <span class="grow" style="font-size:14.5px;color:${colour};overflow:hidden;
      text-overflow:ellipsis;white-space:nowrap">${value}</span>
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="var(--mu)"
      stroke-width="2" stroke-linecap="round"><path d="M9 5l7 7-7 7"/></svg>
  </button>`;
}

function serialResultRows() {
  const r = state.pinResult, sc = state.score, mon = state.monResult;
  const bad = r ? r.pins.filter((x) => !["pass", "reference", "nc"].includes(x.result)).length : 0;
  return resultRow("Pins", r ? (bad ? `${bad} fault(s) found` : "all nine good")
                             : "not run", r ? (bad ? "w" : "g") : "m", "PINS") +
    resultRow("Sweep", sc ? sc.verdict : "not run",
              sc ? { green: "g", amber: "w", red: "r" }[sc.band] : "m", "SWEEP") +
    resultRow("Continuity", mon ? `${mon.dropouts} dropout(s) in ${mon.elapsed_s}s`
                                : "not run", mon ? (mon.passed ? "g" : "r") : "m", "CONTINUITY");
}

function ethResultRows() {
  const sc = state.ethScore, mon = state.monResult;
  const linked = state.ethRungs.filter((x) => x.link).length;
  return resultRow("Pairs", sc ? (sc.suspect_pairs || "all four carrying") : "not run",
                   sc ? (sc.suspect_pairs ? "w" : "g") : "m", "PAIRS") +
    resultRow("Speeds", state.ethRungs.length ? `${linked} of ${state.ethRungs.length} linked`
                                              : "not run",
              sc ? { green: "g", amber: "w", red: "r" }[sc.band] : "m", "SPEED") +
    resultRow("Continuity", mon ? `${mon.dropouts} dropout(s) in ${mon.elapsed_s}s`
                                : "not run", mon ? (mon.passed ? "g" : "r") : "m", "CONTINUITY");
}

const SCREEN = {
SERIAL: {
  TEST: () => {
    const sc = state.score;
    const busy = Boolean(state.running);
    return card(
      `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
        gap:2px">${gauge(sc ? sc.score : null, sc ? sc.band : null)}
        <div style="font-family:var(--disp);font-weight:700;font-size:12px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--mu)">Health score</div></div>
       <div class="grow"></div>
       ${verdictInline()}`,
      "width:312px;flex-shrink:0") +
    `<div class="grow" style="display:flex;flex-direction:column;gap:11px;min-width:0">
       ${card(h2("Results", "tap for detail") + serialResultRows(), "flex-grow:0")}
       <div class="grow"></div>
       ${btn("btn-pincheck", "Run pin check",
             { kind: "primary", big: true, sub: "Two seconds", disabled: busy })}
       ${btn("btn-sweep", "Run baud sweep", { big: true, disabled: busy || !state.pinJob,
             sub: state.pinJob ? "Choose how hard to work it" : "Needs a passing pin check" })}
       ${btn("btn-cancel", "Cancel", { kind: "danger", disabled: !busy, style: "height:52px" })}
     </div>`;
  },

  PINS: () => {
    const r = state.pinResult;
    const rows = r ? r.pins.map((p) => {
      const tone = RESULT_TONE[p.result] || "m";
      return `<div class="trow">
        <span class="mono" style="width:22px;color:var(--mu)">${p.pin}</span>
        <span style="width:54px;font-weight:500">${p.signal}</span>
        <span class="grow" style="font-size:12.5px;color:var(--mu);
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.detail || ""}</span>
        <span class="${tone}" style="font-size:11.5px;font-weight:700;letter-spacing:.09em;
              text-transform:uppercase">${RESULT_LABEL[p.result] || p.result}</span></div>`;
    }).join("") : "";
    const bad = r ? r.pins.filter((p) => !["pass", "reference", "nc"].includes(p.result)).length : 0;
    // The heading follows the toggle. Hardcoding "male view" above a diagram
    // showing a female shell is how a technician ends up at the wrong pin.
    return card(h2(state.shell === "male" ? "Plug, male view" : "Plug, female view",
                   state.shell === "male" ? "1 to 5, left to right"
                                          : "5 to 1, left to right") +
        `<div style="display:flex;justify-content:center;margin-top:4px">${db9(r && r.pins, state.shell)}</div>
         <div class="grow"></div>
         ${shellToggle()}
         <div style="font-size:12.5px;color:var(--mu);line-height:1.4;margin-top:9px">${
           r ? r.topology.label : "Pin numbers are moulded into the plastic. Go by those."}</div>`,
        "width:344px;flex-shrink:0") +
      card(h2("Pin results", r ? (bad ? `${bad} fault(s)` : "all good") : "not run") +
        (r ? rows : empty("Run the pin check to see every pin graded.")), "flex-grow:1");
  },

  SWEEP: () => {
    const rows = window.CT.bauds.map((baud) => {
      const e = state.sweepRates[baud] || {};
      const g = e.grade;
      const tone = g ? { pass: "--good", marginal: "--wn", fail: "--bad" }[g.status] : null;
      const chip = (run) => {
        if (!run) return `<span class="chip m">${DASH}</span>`;
        const ok = !run.error && run.mismatched === 0 && run.missing === 0;
        const cls = ok ? "g" : (run.ber !== undefined && run.ber <= 1e-3 ? "w" : "r");
        return `<span class="chip ${cls}">${ok ? "Pass" : (cls === "w" ? "Marginal" : "Fail")}</span>`;
      };
      return `<div class="trow" style="height:44px">
        <span class="mono" style="width:104px;font-size:16px">${baud.toLocaleString()}</span>
        <span style="width:118px">${chip(e.none)}</span>
        <span style="width:118px">${chip(e.even)}</span>
        <span class="mono ${e.none && e.none.mismatched ? 'r' : 'm'}"
              style="width:92px">${e.none ? (e.none.mismatched + e.none.missing) : DASH}</span>
        <span class="mono m" style="width:110px">${e.none ? fmtBps(e.none.throughput_bps) : DASH}</span>
        <span class="bar"><i style="width:${g ? Math.round(g.credit * 100) : 0}%;
              background:var(${tone || '--bg3'})"></i></span></div>`;
    }).join("");
    const s = state.score;
    return card(
      h2("Baud sweep", s ? `${s.per_rate.filter((r) => r.status === "pass").length} of ${s.per_rate.length} clean`
                         : (state.running === "sweep" ? "running" : "not run")) +
      `<div class="thead"><span style="width:104px">Rate</span><span style="width:118px">No parity</span>
        <span style="width:118px">Even parity</span><span style="width:92px">Errors</span>
        <span style="width:110px">Throughput</span><span class="grow">Quality</span></div>` +
      rows +
      `<div class="grow"></div>
       <div class="row" style="align-items:center">
         <span style="font-family:var(--disp);font-weight:700;font-size:16px;
           color:var(${s ? BAND_VAR[s.band] : '--mu'})">${s ? s.verdict : ""}</span>
         <span class="grow"></span>
         ${btn("btn-sweep2", "Run sweep", { kind: "primary", style: "width:170px",
               disabled: Boolean(state.running) || !state.pinJob })}
       </div>`, "flex-grow:1");
  },
},
};

/* ---------------------------------------------------- ethernet screens */

/* Standard-independent: T568A and T568B swap the orange and green pairs
   wholesale, so the physical connection is identical either way. Blue and
   brown never move. That is why this chart needs no standard selector. */
/* Signal to DB9 pin. A technician repairs a pin, not a signal name. */
const PIN_FOR = { CTS: 8, DSR: 6, DCD: 1, RI: 9, Link: null };

const LOOPBACK = [
  ["White/Orange", "White/Green", "1 to 3", "#e08a3c", "#3faa62"],
  ["Orange", "Green", "2 to 6", "#e08a3c", "#3faa62"],
  ["Blue", "White/Brown", "4 to 7", "#4f7fd6", "#9a6b4a"],
  ["White/Blue", "Brown", "5 to 8", "#4f7fd6", "#9a6b4a"],
];
const PAIR_INFO = [
  ["Orange", "1, 2", "#e08a3c", 10],
  ["Green", "3, 6", "#3faa62", 10],
  ["Blue", "4, 5", "#4f7fd6", 1000],
  ["Brown", "7, 8", "#9a6b4a", 1000],
];
const ETH_SPEEDS = [10, 100, 1000];

function swatch(c, striped) {
  return `<span class="sw ${striped ? "half" : "solid"}" style="--c:${c}"></span>`;
}

const PICKER_STYLE = `font-family:var(--mono);font-size:15px;color:var(--tx);
  background:var(--bg3);border:0.5px solid var(--b2);border-radius:50px;height:50px;
  padding:0 16px;width:100%;-webkit-appearance:none;appearance:none`;

function ifacePicker(id, selected) {
  const opts = state.ifaces.map((i) => {
    const label = `${i.iface}${i.driver ? " · " + i.driver : ""}`;
    return `<option value="${i.iface}" ${i.testable ? "" : "disabled"} ${
      i.iface === selected ? "selected" : ""}>${label}${i.testable ? "" : "  (uplink)"}</option>`;
  }).join("");
  return `<select id="${id}" style="${PICKER_STYLE}">${
    opts || '<option value="">No ports found</option>'}</select>`;
}

function portPicker(selected) {
  const opts = state.ports.map((pt) =>
    `<option value="${pt.device}" ${pt.device === selected ? "selected" : ""}>${pt.device} · ${
      pt.description}</option>`).join("");
  return `<select id="port-pick" style="${PICKER_STYLE}">${
    opts || '<option value="">No serial ports found</option>'}</select>`;
}

function portsCard() {
  const row = (label, control) =>
    `<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px">
      <span style="font-family:var(--sans);font-size:10px;font-weight:600;letter-spacing:.12em;
        text-transform:uppercase;color:var(--mu)">${label}</span>${control}</div>`;
  return card(h2("Ports", "fixed by the kit") +
    row("Serial adapter", portPicker(state.port)) +
    row("Ethernet, end A", ifacePicker("eth-a", state.ethA)) +
    row("Ethernet, end B", ifacePicker("eth-b", state.ethB)) +
    `<div class="grow"></div>
     <div style="font-size:12.5px;color:var(--mu);line-height:1.45;margin-bottom:12px">
       These are wired into the case and do not change between cables, which is why they
       live here rather than on the test screen.</div>` +
    btn("btn-refresh", "Rescan ports", {}), "width:352px;flex-shrink:0");
}

SCREEN.ETHERNET = {
  TEST: () => {
    const sc = state.ethScore;
    const busy = Boolean(state.running);
    const note = state.ethCanTest ? "" :
      `<div class="verdict-sub" style="color:var(--wn);font-size:13px">ethtool is not installed,
       so no ethernet test can run. Run deploy/setup-pi.sh.</div>`;
    return card(
      `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
        gap:2px">${gauge(sc ? sc.score : null, sc ? sc.band : null)}
        <div style="font-family:var(--disp);font-weight:700;font-size:12px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--mu)">Health score</div></div>
       <div class="grow"></div>
       <div style="text-align:center;padding:0 4px">
         <div class="verdict" style="font-size:22px;${sc ? `color:var(${BAND_VAR[sc.band]})` : ""}">${
           sc ? sc.verdict : "Ready."}</div>
         <div class="verdict-sub" style="font-size:13px">${sc && sc.suspect_pairs
           ? "Suspect pairs " + sc.suspect_pairs
           : "Run the cable between the two ports set up in Setup, then start."}</div>${note}
       </div>`,
      "width:312px;flex-shrink:0") +
    `<div class="grow" style="display:flex;flex-direction:column;gap:11px;min-width:0">
       ${card(h2("Results", "tap for detail") + ethResultRows(), "flex-grow:0")}
       <div class="grow"></div>
       ${btn("btn-eth", "Run speed sweep", { kind: "primary", big: true,
             sub: "10, 100 and 1000 Mb", disabled: busy || !state.ethCanTest })}
       ${btn("btn-cancel", "Cancel", { kind: "danger", disabled: !busy, style: "height:52px" })}
     </div>`;
  },

  PAIRS: () => {
    const best = state.ethScore ? state.ethScore.best_speed : null;
    const rows = PAIR_INFO.map(([name, pins, colour, needs]) => {
      // A pair is only implicated once the ladder has told us something. With
      // no result the honest state is "unknown", not "good".
      let label = "Not tested", tone = "m";
      if (best !== null) {
        const ok = best >= needs;
        label = ok ? "Carrying" : "Not carrying";
        tone = ok ? "g" : "w";
      }
      return `<div style="display:flex;align-items:center;gap:12px;height:56px;padding:0 14px;
        border-radius:10px;background:var(--bg3)">${swatch(colour, true)}
        <div style="flex-grow:1;min-width:0">
          <div style="font-size:15px;font-weight:500">${name}</div>
          <div class="mono" style="font-size:11.5px;color:var(--mu)">pins ${pins}</div></div>
        <span class="${tone}" style="font-size:11.5px;font-weight:700;letter-spacing:.09em;
          text-transform:uppercase">${label}</span></div>`;
    }).join("");
    const explain = best === null
      ? empty("Run the speed sweep. Which speeds link is what tells you which pairs are sound.")
      : `<div style="font-size:15px;line-height:1.5;color:var(--mu)">
          <p style="margin-bottom:12px"><b style="color:var(--tx)">10 and 100 Mb use only the
            orange and green pairs.</b> Gigabit needs all four. So the highest speed that links
            says which conductors are carrying, with no reflectometry involved.</p>
          <p>${state.ethScore.verdict}</p></div>`;
    return card(h2("Pairs") +
        `<div style="display:flex;flex-direction:column;gap:9px;margin-top:4px">${rows}</div>`,
        "width:344px;flex-shrink:0") +
      card(h2("What this means", state.ethScore && state.ethScore.suspect_pairs
              ? "fault localised" : "") + explain, "flex-grow:1");
  },

  SPEED: () => {
    const rows = ETH_SPEEDS.map((sp) => {
      const r = state.ethRungs.find((x) => x.speed === sp);
      const chip = !r ? `<span class="chip m">${DASH}</span>`
        : `<span class="chip ${r.link ? "g" : "r"}">${r.link ? "Link" : "No link"}</span>`;
      return `<div class="trow" style="height:58px">
        <span class="mono" style="width:126px;font-size:19px">${sp} Mb</span>
        <span style="width:142px">${chip}</span>
        <span class="mono m" style="width:130px">${r && r.link && r.negotiated
              ? r.negotiated + "Mb/s" : DASH}</span>
        <span class="mono m" style="width:110px">${r && r.link && r.duplex ? r.duplex : DASH}</span>
        <span class="grow" style="font-size:13.5px;color:var(--mu)">${
          sp === 1000 ? "needs all four pairs" : "pairs 1-2 and 3-6 only"}</span></div>`;
    }).join("");
    const s = state.ethScore;
    return card(h2("Speed sweep", s ? `${state.ethRungs.filter((r) => r.link).length} of ${
        state.ethRungs.length} linked` : (state.running === "eth" ? "running" : "not run")) +
      `<div class="thead"><span style="width:126px">Speed</span><span style="width:142px">Link</span>
        <span style="width:130px">Negotiated</span><span style="width:110px">Duplex</span>
        <span class="grow">Pairs needed</span></div>` + rows +
      `<div class="grow"></div>
       <div class="row" style="align-items:center">
         <span style="font-family:var(--disp);font-weight:700;font-size:16px;
           color:var(${s ? BAND_VAR[s.band] : '--mu'})">${s ? s.verdict : ""}</span>
         <span class="grow"></span>
         ${btn("btn-eth2", "Run sweep", { kind: "primary", style: "width:170px",
               disabled: Boolean(state.running) || !state.ethCanTest })}
       </div>`, "flex-grow:1");
  },
};

/* ------------------------------------------------ shared screens */

const JUMPERS = [["2 to 3", "Data", "--wire-data"],
                 ["7 to 8", "Flow control", "--wire-flow"],
                 ["4 to 1 to 6", "Modem status", "--wire-modem"]];

SCREEN.SERIAL.WIRING = () =>
  card(h2("Loopback plug") +
    `<div style="display:flex;justify-content:center">${db9(null, state.shell)}</div>
     <div class="grow"></div>
     <div style="font-size:13px;color:var(--mu);line-height:1.45">Pin numbers are moulded into
       the plastic. Go by those, not by position. The rows mirror left to right between a male
       and a female shell.</div>`, "flex-grow:1") +
  card(h2("Jumpers") +
    JUMPERS.map(([p, n, c]) => `<div class="trow">
      <span style="width:26px;height:4px;border-radius:2px;background:var(${c});
        margin-right:13px"></span>
      <span class="mono" style="width:112px">${p}</span>
      <span style="color:var(--mu)">${n}</span></div>`).join("") +
    `<div class="trow" style="border:0"><span style="color:var(--mu);font-size:13px">
       Pin 9 is left unconnected.</span></div>
     <div class="grow"></div>
     <div style="font-size:13px;color:var(--mu);line-height:1.45">Use the shortest jumpers that
       will reach. Long loops inside the shell pick up noise and can make a good cable look
       marginal at 115200.</div>`, "width:340px;flex-shrink:0");

SCREEN.ETHERNET.WIRING = () =>
  card(h2("Loopback, gigabit", "1-3, 2-6, 4-7, 5-8") +
    `<div style="display:flex;flex-direction:column;gap:10px;margin-top:2px">${
      LOOPBACK.map(([a, b, pins, ca, cb]) => `<div style="display:flex;align-items:center;
        gap:11px;height:58px;padding:0 14px;border-radius:10px;background:var(--bg3)">
        ${swatch(ca, a.startsWith("White"))}
        <span style="width:104px;font-size:14px">${a}</span>
        <span style="color:var(--mu);font-size:17px">&harr;</span>
        ${swatch(cb, b.startsWith("White"))}
        <span style="width:104px;font-size:14px">${b}</span>
        <span class="grow"></span>
        <span class="mono m" style="font-size:14px">${pins}</span></div>`).join("")}</div>`,
    "flex-grow:1") +
  card(h2("Building it") +
    `<div style="font-size:14.5px;line-height:1.5;color:var(--mu)">
      <p style="margin-bottom:12px"><b style="color:var(--tx)">The colours are the same in T568A
        and T568B.</b> The two standards swap the orange and green pairs wholesale, so the
        connection is identical either way.</p>
      <p style="margin-bottom:12px"><b style="color:var(--bad)">Never tie a wire to its own
        stripe partner.</b> Blue to White/Blue is a dead short across a pair, not a loopback.</p>
      <p>Better still, run the cable between the two ports and skip the plug entirely. Two real
        ports negotiating with each other is a truer test than one listening to itself.</p>
     </div>`, "width:330px;flex-shrink:0");

state.monEvents = [];
state.monResult = null;
state.monStart = null;
state.monRate = 0;
state.monOpen = [];

function monElapsed() {
  if (!state.monStart) return "00:00";
  const t = Math.floor((Date.now() - state.monStart) / 1000);
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/* The timeline is the visual answer to "is this thing doing anything". A
   counter sitting on zero cannot tell you whether the monitor is watching
   hard or has quietly died, and it cannot tell you WHEN a dropout happened
   relative to where your hands were on the cable. */
function timeline(events, spanMs, live) {
  const span = Math.max(spanMs, 1000);
  const marks = events.map((e) => {
    const left = Math.max(0, Math.min(100, (e.at_ms / span) * 100));
    const dur = e.duration_ms === null ? span - e.at_ms : e.duration_ms;
    const width = Math.max(0.6, (dur / span) * 100);
    return `<span class="hit" style="left:${left}%;width:${width}%"
      title="${e.line} ${Math.round(dur)} ms"></span>`;
  }).join("");
  const secs = Math.round(span / 1000);
  return `<div class="spark${live ? "" : " idle"}">
    <span class="ok"></span>${marks}
    ${live ? '<span class="now" style="right:0"></span>' : ""}
    <span class="tick" style="left:7px">0s</span>
    <span class="tick" style="right:7px">${secs}s</span>
  </div>`;
}

const CONTINUITY = () => {
  const live = state.running === "continuity";
  const n = state.monEvents.length;
  const res = state.monResult;
  const openNow = state.monOpen || [];
  const serial = state.proto === "SERIAL";

  // Which conductors have misbehaved, newest counts first. Named on screen
  // because a technician repairs a pin, not a signal name.
  const byLine = {};
  state.monEvents.forEach((e) => { byLine[e.line] = (byLine[e.line] || 0) + 1; });
  const lines = Object.keys(byLine);
  const pins = state.monEvents.map((e) => PIN_FOR[e.line]).filter(Boolean);
  const bad = openNow.length > 0;
  const body = live
    ? `<div class="prompt">Move the cable
         <small>Flex it at both connectors, at the strain reliefs, and along its length.</small>
       </div>
       <div style="height:12px"></div>
       <div class="state" style="color:var(${bad ? "--bad" : "--good"})">${
         bad ? "OPEN" : "GOOD"}</div>
       <div style="font-family:var(--mono);font-size:15px;color:var(${bad ? "--bad" : "--mu"});
            min-height:22px">${
         bad ? openNow.map((l) => `${l} (pin ${PIN_FOR[l] || "?"})`).join(", ")
             : (lines.length
                ? lines.map((l) => `${l} pin ${PIN_FOR[l] || "?"}: ${byLine[l]}`).join("   ")
                : "all conductors holding")}</div>`
    : res
      ? `<div class="verdict" style="color:var(${res.passed ? "--good" : "--bad"});
           text-align:center;font-size:34px">${res.passed ? "GOOD" : "OPEN"}</div>
         <div class="verdict-sub" style="text-align:center;max-width:520px">${res.verdict}</div>`
      : `<div class="verdict" style="text-align:center">Find an intermittent fault</div>
         <div class="verdict-sub" style="text-align:center;max-width:520px">A cable that opens
           only when it moves passes every other test here. Start this, then work the cable
           with your hands while it watches.</div>`;

  const spanMs = live ? Math.max(1, Date.now() - state.monStart)
                      : (res ? res.elapsed_s * 1000 : 0);
  const rate = live ? state.monRate : (res ? res.sample_rate_hz : 0);
  const resolution = res ? res.resolution_ms : 10;

  return card(
    h2("Continuity", live ? `${monElapsed()} elapsed`
        : (res ? `${res.elapsed_s}s watched` : "not running")) +
    `<div class="wig">${body}</div>` +
    timeline(state.monEvents, spanMs, live) +
    `<div class="rate">
       <span>${rate ? Math.round(rate).toLocaleString() + " samples/s" : "idle"}</span>
       <span class="grow"></span>
       <span>sees breaks longer than ${Math.round(resolution)} ms</span>
     </div>` +
    `<div class="row">${live
      ? btn("btn-mon-stop", "Stop and record", { kind: "primary", style: "height:64px;flex-grow:1" })
      : btn("btn-mon", "Start watching", { kind: "primary", style: "height:64px;flex-grow:1",
            disabled: Boolean(state.running) })}</div>`,
    "flex-grow:1") +
  card((serial
      ? h2("Conductors", state.shell === "male" ? "male shell" : "female shell") +
        `<div style="display:flex;justify-content:center">${
          db9(null, state.shell, pins.length ? pins : (res ? res.affected_pins : []))}</div>` +
        shellToggle() +
        `<div style="height:11px"></div>`
      : "") +
    h2("Events", state.monEvents.length ? "" : "none yet") +
    (state.monEvents.length
      ? `<div class="log">${state.monEvents.slice(-8).map((e) =>
          `<div>${(e.at_ms / 1000).toFixed(1)}s <b>${e.line} pin ${PIN_FOR[e.line] || "?"} open ${
            e.duration_ms === null ? "(still open)" : Math.round(e.duration_ms) + " ms"}</b></div>`
        ).join("")}</div>`
      : `<div style="font-size:12.5px;color:var(--mu);line-height:1.45;padding:4px 2px">
           Every open is timestamped here, with the conductor that caused it.</div>`),
    "width:330px;flex-shrink:0");
};
SCREEN.SERIAL.CONTINUITY = CONTINUITY;
SCREEN.ETHERNET.CONTINUITY = CONTINUITY;

const SETUP = () => {
  const canExport = Boolean(state.lastPinJob);
  return portsCard() +
    card(h2("Sweep settings", "tap to edit") +
      (state.settings.length
        ? state.settings.map((x) => settingRow(x, null, true)).join("")
        : empty("Loading.")) +
      `<div class="grow"></div>
       <div class="row" style="margin-bottom:9px">
         ${btn("btn-reset", "Reset settings", {})}
         ${btn("btn-dark", "Dark", { kind: state.dark ? "primary" : "", style: "width:96px" })}
         ${btn("btn-light", "Light", { kind: state.dark ? "" : "primary", style: "width:96px" })}
       </div>
       <div class="row">
         ${btn("btn-json", "Export JSON", { disabled: !canExport })}
         ${btn("btn-print", "Print report", { kind: "primary", disabled: !canExport })}
       </div>
       <div style="font-family:var(--mono);font-size:11.5px;color:var(--mu);margin-top:11px">
         v${window.CT.version}${window.CT.simulating ? "  ·  SIMULATION" : ""}${
           canExport ? "" : "  ·  nothing to export yet"}</div>`,
      "flex-grow:1");
};

SCREEN.SERIAL.SETUP = SETUP;
SCREEN.ETHERNET.SETUP = SETUP;

/* ---------------------------------------------------------------- render */

const STATE_TEXT = {
  TEST: "Ready", PINS: "Pin check", SWEEP: "Baud sweep", CONTINUITY: "Continuity",
  PAIRS: "Pairs", SPEED: "Speed sweep", WIRING: "Reference", SETUP: "Setup",
};

function render() {
  $("under-test").textContent = underTest();
  $("under-test-label").textContent =
    state.proto === "ETHERNET" ? "Testing between" : "Testing on";
  const names = NAV[state.proto];
  if (!names.includes(state.screen)) state.screen = "TEST";

  $("nav").innerHTML = names.map((n) =>
    `<button class="navbtn${n === state.screen ? " on" : ""}" data-s="${n}">
       <svg viewBox="0 0 24 24">${ICON[n]}</svg>${n}</button>`).join("");

  const alert = $("alert");
  $("screens").innerHTML =
    `<section class="screen on">${SCREEN[state.proto][state.screen]()}</section>`;
  if (alert) $("screens").appendChild(alert);

  bind();
}

/* Handlers are rebound after every render because the screen is rebuilt from
   scratch. That is deliberate: a screen is a pure function of state, so there
   is no partial-update path to get wrong, and at this size the cost is
   nothing. */
function bind() {
  document.querySelectorAll(".navbtn").forEach((b) => {
    b.onclick = () => { state.screen = b.dataset.s; setState(STATE_TEXT[b.dataset.s]); render(); };
  });
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("btn-pincheck", runPinCheck);
  on("btn-sweep", openPicker);
  on("btn-sweep2", openPicker);
  on("btn-eth", runEthLadder);
  on("btn-eth2", runEthLadder);
  on("btn-cancel", cancelRunning);
  on("btn-mon", startContinuity);
  on("btn-mon-stop", cancelRunning);
  on("btn-json", () => { window.location = "/api/export.json" + exportQuery(); });
  on("btn-print", () => { window.open("/report" + exportQuery(), "_blank"); });
  on("btn-dark", () => applyTheme(true));
  on("btn-light", () => applyTheme(false));
  on("btn-reset", async () => {
    try {
      const d = await api("/api/sweep-settings/reset", { method: "POST" });
      state.settings = d.settings; render();
    } catch (err) { showAlert(err.message, err.hint); }
  });
  document.querySelectorAll("#screens .preset").forEach((b) => {
    b.onclick = () => openEditor(b.dataset.id);
  });
  document.querySelectorAll("[data-goto]").forEach((b) => {
    b.onclick = () => { state.screen = b.dataset.goto; setState(STATE_TEXT[b.dataset.goto]); render(); };
  });
  const pick = (id, key) => {
    const el = $(id);
    if (!el) return;
    el.onchange = () => { state[key] = el.value || null; saveSelection(); render(); };
  };
  pick("port-pick", "port");
  pick("eth-a", "ethA");
  pick("eth-b", "ethB");
  on("btn-refresh", () => { loadPorts(); loadInterfaces(); });
  document.querySelectorAll("[data-shell]").forEach((b) => {
    b.onclick = () => { state.shell = b.dataset.shell; saveSelection(); render(); };
  });
}

/* ------------------------------------------------------------ run tests */

function exportQuery() {
  const params = new URLSearchParams();
  if (state.lastPinJob) params.set("pincheck", state.lastPinJob);
  if (state.sweepJob) params.set("sweep", state.sweepJob);
  const id = $("cable-id").value.trim();
  if (id) params.set("cable_id", id);
  const q = params.toString();
  return q ? "?" + q : "";
}

async function runPinCheck() {
  const port = state.port;
  if (!port) {
    showAlert("No serial port selected.", "Choose one under Setup, then try again.");
    state.screen = "SETUP"; render(); return;
  }
  clearAlert();
  state.pinJob = null; state.sweepJob = null; state.score = null;
  state.pinResult = null; state.sweepRates = {};
  try {
    setRunning("pincheck");
    setState("Starting");
    const { job } = await api("/api/pincheck", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: port }),
    });
    state.currentJob = job;
    follow(job, "pincheck", {
      pin_step: (d) => setState(d.state === "asserting"
        ? `Asserting ${d.output}` : `${d.output} read back`),
      pincheck_result: (result) => {
        state.pinResult = result;
        state.pinJob = result.passed ? job : null;
        state.lastPinJob = job;
        setLamp(result.passed ? "ok" : "bad");
        // Move to PINS on a failure: the fault is the thing worth looking at,
        // and a technician should not have to go and find it.
        if (!result.passed) state.screen = "PINS";
        render();
      },
    });
  } catch (err) { setRunning(null); showAlert(err.message, err.hint); }
}

async function runSweep() {
  if (!state.pinJob) { showAlert("Run a passing pin check first."); return; }
  clearAlert();
  state.score = null; state.sweepRates = {};
  state.screen = "SWEEP";
  try {
    setRunning("sweep");
    const { job } = await api("/api/sweep", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: state.port, pincheck: state.pinJob,
                              setting: state.chosen }),
    });
    state.currentJob = job;
    state.sweepJob = job;
    follow(job, "sweep", {
      sweep_rate: (d) => {
        if (d.state === "start") { setState(`${d.baud} baud`); return; }
        const e = state.sweepRates[d.baud] || (state.sweepRates[d.baud] = {});
        e.grade = d.grade;
        render();
      },
      sweep_run: (d) => {
        const e = state.sweepRates[d.baud] || (state.sweepRates[d.baud] = {});
        e[d.parity] = d.run;
        render();
      },
      score: (score) => { state.score = score; render(); },
      finished: (data) => {
        if (data.result) {
          state.score = data.result.score;
          setLamp(data.result.score.band === "red" ? "bad" : "ok");
        }
        render();
      },
    });
  } catch (err) { setRunning(null); showAlert(err.message, err.hint); }
}

async function runEthLadder() {
  const a = state.ethA, b = state.ethB;
  if (!a || !b) {
    showAlert("Ethernet ports are not set.",
              "Choose both under Setup. The cable needs two ends.");
    state.screen = "SETUP"; render(); return;
  }
  clearAlert();
  state.ethRungs = []; state.ethScore = null;
  state.screen = "SPEED";
  try {
    setRunning("eth");
    const { job } = await api("/api/eth/ladder", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ iface_a: a, iface_b: b }),
    });
    state.currentJob = job;
    follow(job, "eth", {
      eth_rung_start: (d) => setState(`${d.speed} Mb`),
      eth_rung_done: (d) => {
        state.ethRungs = state.ethRungs.filter((r) => r.speed !== d.speed).concat(d)
          .sort((x, y) => x.speed - y.speed);
        if (d.anomaly) showAlert("The adapter is not honouring the advertisement.", d.anomaly);
        render();
      },
      score: (score) => { state.ethScore = score; render(); },
      finished: (data) => {
        if (data.result) {
          state.ethScore = data.result.score;
          setLamp(data.result.score.band === "red" ? "bad" : "ok");
        }
        render();
      },
    });
  } catch (err) { setRunning(null); showAlert(err.message, err.hint); }
}

/* ---------------------------------------------------------------- setup */

function applyTheme(dark) {
  state.dark = dark;
  document.documentElement.classList.toggle("dark", dark);
  try { localStorage.setItem("cabletester-theme", dark ? "dark" : "light"); } catch (_) {}
  render();
}

const SEL_KEY = "cabletester-selection";

function saveSelection() {
  try {
    localStorage.setItem(SEL_KEY, JSON.stringify(
      { port: state.port, ethA: state.ethA, ethB: state.ethB, shell: state.shell }));
  } catch (_) { /* private browsing, or no storage. Not worth failing over. */ }
}

function loadSelection() {
  try {
    Object.assign(state, JSON.parse(localStorage.getItem(SEL_KEY) || "{}"));
  } catch (_) { /* nothing saved yet */ }
}

function underTest() {
  if (state.proto === "ETHERNET") {
    return state.ethA && state.ethB ? `${state.ethA} to ${state.ethB}` : "not set";
  }
  return state.port || "not set";
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("cabletester-theme"); } catch (_) {}
  // Dark by default and deliberately NOT following the device: this runs full
  // screen on a shop bench, often in a dim building. An explicit choice sticks.
  state.dark = saved !== "light";
  document.documentElement.classList.toggle("dark", state.dark);
}

async function loadPorts() {
  try {
    const data = await api("/api/ports");
    state.ports = data.ports || [];
    // Keep a saved choice if it is still present; otherwise take the only
    // port, which is the kit's case. Never silently pick one of several: a
    // technician should know which adapter answered.
    if (!state.ports.some((pt) => pt.device === state.port)) {
      state.port = state.ports.length === 1 ? state.ports[0].device : null;
      saveSelection();
    }
    render();
  } catch (err) { showAlert("Could not list serial ports.", err.message); }
}

async function loadInterfaces() {
  try {
    const data = await api("/api/eth/interfaces");
    state.ifaces = data.interfaces || [];
    state.ethCanTest = data.can_test !== false;
    const testable = state.ifaces.filter((i) => i.testable);
    const ok = (name) => testable.some((i) => i.iface === name);
    // A two-port kit has exactly two testable ports, so preselecting them is
    // right and saves a setup step. Anything else is left for a person.
    if (!ok(state.ethA) || !ok(state.ethB) || state.ethA === state.ethB) {
      state.ethA = testable.length >= 2 ? testable[0].iface : null;
      state.ethB = testable.length >= 2 ? testable[1].iface : null;
      saveSelection();
    }
    render();
  } catch (err) { state.ifaces = []; state.ethCanTest = false; render(); }
}

function init() {
  initTheme();
  loadSelection();
  $("ver-btn").onclick = () => $("sheet").classList.add("on");
  $("sheet-close").onclick = () => $("sheet").classList.remove("on");
  $("proto").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.proto === state.proto || state.running) return;
    state.proto = b.dataset.proto;
    document.querySelectorAll("#proto button").forEach((x) => x.classList.toggle("on", x === b));
    render();
    if (state.proto === "ETHERNET") loadInterfaces();
  };
  $("pick-cancel").onclick = () => $("pick-scrim").classList.remove("on");
  $("pick-start").onclick = () => { $("pick-scrim").classList.remove("on"); runSweep(); };
  $("edit-cancel").onclick = () => $("edit-scrim").classList.remove("on");
  $("edit-save").onclick = saveEditor;
  for (const id of ["pick-scrim", "edit-scrim"]) {
    $(id).onclick = (e) => { if (e.target.id === id) $(id).classList.remove("on"); };
  }
  render();
  loadPorts();
  loadInterfaces();
  loadSettings();
}

document.addEventListener("DOMContentLoaded", init);

/* --------------------------------------------------------- sweep settings */

state.settings = [];
state.chosen = "standard";
state.editing = null;

async function loadSettings() {
  try {
    const d = await api("/api/sweep-settings");
    state.settings = d.settings || [];
    state.patterns = d.patterns || {};
    state.allRates = d.rates || window.CT.bauds;
    render();
  } catch (_) { state.settings = []; }
}

function settingRow(s, onclick, chevron) {
  return `<button class="preset${s.id === state.chosen && !chevron ? " sel" : ""}"
    data-id="${s.id}" style="${chevron ? "height:66px;margin-bottom:8px" : ""}">
    <span class="nm">${s.name}</span>
    <span class="ds">${s.summary}</span>
    <span class="tm">${s.duration}</span>
    ${chevron
      ? `<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="var(--mu)" stroke-width="2"
           stroke-linecap="round" style="opacity:1"><path d="M9 5l7 7-7 7"/></svg>`
      : `<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
           stroke-linecap="round"><path d="M4 12.5l5.5 5.5L20 7"/></svg>`}
  </button>`;
}

function openPicker() {
  if (!state.settings.length) { showAlert("Sweep settings are still loading."); return; }
  $("pick-list").innerHTML = state.settings.map((s) => settingRow(s, null, false)).join("");
  $("pick-list").querySelectorAll(".preset").forEach((b) => {
    b.onclick = () => {
      state.chosen = b.dataset.id;
      $("pick-list").querySelectorAll(".preset").forEach((x) =>
        x.classList.toggle("sel", x.dataset.id === state.chosen));
    };
  });
  $("pick-scrim").classList.add("on");
}

function openEditor(id) {
  const s = state.settings.find((x) => x.id === id);
  if (!s) return;
  state.editing = JSON.parse(JSON.stringify(s));
  $("edit-name").textContent = s.name;
  drawEditor();
  $("edit-scrim").classList.add("on");
}

function drawEditor() {
  const s = state.editing;
  const step = (label, value, dec, inc) =>
    `<div class="trow" style="height:54px">
      <span style="flex-grow:1;font-size:15px">${label}</span>
      <button class="btn" data-act="${dec}" style="width:44px;height:44px;padding:0;font-size:20px">&minus;</button>
      <span class="mono" style="min-width:150px;text-align:center;font-size:15px">${value}</span>
      <button class="btn" data-act="${inc}" style="width:44px;height:44px;padding:0;font-size:20px">+</button>
    </div>`;
  const rateText = s.rates.length === state.allRates.length ? "all eight"
    : s.rates.map((r) => r >= 1000 ? (r / 1000) + "k" : r).join(", ");
  $("edit-fields").innerHTML =
    step("Rates", rateText, "rates-", "rates+") +
    step("Payload per rate", s.payload_seconds.toFixed(1) + " s", "secs-", "secs+") +
    step("Passes", String(s.passes), "pass-", "pass+") +
    step("Parity", s.parity, "par", "par") +
    step("Pattern", s.pattern, "pat", "pat") +
    `<div style="font-size:12.5px;color:var(--mu);margin-top:10px;line-height:1.45">
      ${state.patterns[s.pattern] || ""}</div>`;
  $("edit-fields").querySelectorAll("button").forEach((b) => { b.onclick = () => editStep(b.dataset.act); });
}

/* Editing is stepper-only on purpose. Every value here is numeric or a short
   enum, and a stepper needs no keyboard, which this box does not reliably
   have. Nothing in this editor requires typing. */
function editStep(act) {
  const s = state.editing;
  const R = state.allRates;
  const PAR = ["none", "even", "both"];
  const PAT = Object.keys(state.patterns);
  if (act === "rates+") s.rates = R.slice(0, Math.min(R.length, s.rates.length + 1));
  if (act === "rates-") s.rates = R.slice(0, Math.max(1, s.rates.length - 1));
  if (act === "secs+") s.payload_seconds = Math.min(30, Math.round((s.payload_seconds + 0.5) * 10) / 10);
  if (act === "secs-") s.payload_seconds = Math.max(0.2, Math.round((s.payload_seconds - 0.5) * 10) / 10);
  if (act === "pass+") s.passes = Math.min(10, s.passes + 1);
  if (act === "pass-") s.passes = Math.max(1, s.passes - 1);
  if (act === "par") s.parity = PAR[(PAR.indexOf(s.parity) + 1) % PAR.length];
  if (act === "pat") s.pattern = PAT[(PAT.indexOf(s.pattern) + 1) % PAT.length];
  drawEditor();
}

async function saveEditor() {
  const s = state.editing;
  try {
    const d = await api(`/api/sweep-settings/${s.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rates: s.rates, payload_seconds: s.payload_seconds,
        passes: s.passes, parity: s.parity, pattern: s.pattern,
      }),
    });
    state.settings = d.settings;
    $("edit-scrim").classList.remove("on");
    render();
  } catch (err) { showAlert(err.message, err.hint); }
}

/* ------------------------------------------------------- continuity run */

async function startContinuity() {
  clearAlert();
  state.monEvents = []; state.monResult = null; state.monStart = Date.now();
  state.monRate = 0; state.monOpen = [];
  const body = state.proto === "ETHERNET"
    ? { protocol: "ethernet", iface_a: state.ethA, iface_b: state.ethB }
    : { protocol: "serial", port: state.port };
  const missing = state.proto === "ETHERNET"
    ? (!body.iface_a || !body.iface_b) : !body.port;
  if (missing) {
    showAlert("Ports are not set.", "Choose them under Setup, then try again.");
    state.screen = "SETUP"; render(); return;
  }
  try {
    setRunning("continuity");
    const { job } = await api("/api/continuity", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.currentJob = job;
    // The elapsed clock ticks from the browser rather than from events,
    // because a clean run produces no events at all and a frozen timer on a
    // test that is working perfectly reads as the instrument having hung.
    state.monTimer = setInterval(() => {
      if (state.running === "continuity" && state.screen === "CONTINUITY") render();
    }, 1000);
    follow(job, "continuity", {
      mon_baseline: (d) => setState(`Watching ${Object.keys(d.lines).length} lines`),
      mon_event: (e) => { state.monEvents.push(e); render(); },
      // A clean run emits no events at all, so the tick is what proves the
      // monitor is alive and shows how hard it is actually sampling.
      mon_tick: (d) => {
        state.monRate = d.rate_hz;
        state.monOpen = d.open_now || [];
        if (state.screen === "CONTINUITY") render();
      },
      finished: (data) => {
        clearInterval(state.monTimer);
        if (data.result) {
          state.monResult = data.result;
          setLamp(data.result.passed ? "ok" : "bad");
        }
        render();
      },
    });
  } catch (err) {
    clearInterval(state.monTimer);
    setRunning(null);
    showAlert(err.message, err.hint);
  }
}
