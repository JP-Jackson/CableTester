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

const NAV = {
  SERIAL:   ["TEST", "PINS", "SWEEP", "WIRING", "SETUP"],
  ETHERNET: ["TEST", "PAIRS", "SPEED", "WIRING", "SETUP"],
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

function db9(pins) {
  const byPin = {};
  (pins || []).forEach((p) => { byPin[p.pin] = p; });
  const pos = {};
  [1, 2, 3, 4, 5].forEach((n, i) => { pos[n] = [60 + i * 46, 58]; });
  [6, 7, 8, 9].forEach((n, i) => { pos[n] = [83 + i * 46, 104]; });
  let out = `<path d="M28 26 L272 26 L252 136 L48 136 Z" fill="none"
             stroke="var(--b2)" stroke-width="2.5" stroke-linejoin="round"/>`;
  for (const n of Object.keys(pos)) {
    const [x, y] = pos[n];
    const res = byPin[n] ? byPin[n].result : null;
    const tone = res ? RESULT_TONE[res] || "m" : null;
    const c = tone ? `var(${{ g: "--good", w: "--wn", r: "--bad", m: "--mu" }[tone]})`
                   : "var(--mu)";
    out += `<circle class="pin" cx="${x}" cy="${y}" r="13" fill="${c}"
             fill-opacity="${res && tone !== 'm' ? '.30' : '.14'}" stroke="${c}" stroke-width="2.4"/>
            <text x="${x}" y="${y + 5}" text-anchor="middle" font-family="var(--mono)"
             font-size="13" font-weight="600" fill="${c}">${n}</text>`;
  }
  return `<svg viewBox="0 0 300 160" style="width:100%;max-width:300px">${out}</svg>`;
}

/* ------------------------------------------------------ serial screens */

function verdictBlock() {
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
  return card(`<div class="verdict" style="${tone}">${text}</div>
               <div class="verdict-sub">${sub}</div>`);
}

const SCREEN = {
SERIAL: {
  TEST: () => {
    const s = state.score;
    const busy = Boolean(state.running);
    return card(
      `<div style="display:flex;flex-direction:column;align-items:center;
        justify-content:center;height:100%;gap:2px">${gauge(s ? s.score : null, s ? s.band : null)}
        <div style="font-family:var(--disp);font-weight:700;font-size:12px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--mu)">Health score</div></div>`,
      "width:318px;flex-shrink:0") +
    `<div class="grow" style="display:flex;flex-direction:column;gap:11px;min-width:0">
       ${verdictBlock()}
       <div class="grow"></div>
       ${btn("btn-pincheck", "Run pin check",
             { kind: "primary", big: true, sub: "Two seconds", disabled: busy })}
       ${btn("btn-sweep", "Run baud sweep", { big: true, disabled: busy || !state.pinJob,
             sub: state.pinJob ? "Eight rates, both parities" : "Passes the pin check first" })}
       ${btn("btn-cancel", "Cancel", { kind: "danger", disabled: !busy, style: "height:56px" })}
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
    return card(h2("Plug, male view") +
        `<div style="display:flex;justify-content:center;margin-top:4px">${db9(r && r.pins)}</div>
         <div class="grow"></div>
         <div style="font-size:13px;color:var(--mu);line-height:1.45">${
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

function ifaceOptions(id) {
  const opts = state.ifaces.map((i) => {
    const label = `${i.iface}${i.driver ? " · " + i.driver : ""}`;
    return `<option value="${i.iface}" ${i.testable ? "" : "disabled"}>${label}${
      i.testable ? "" : "  (uplink)"}</option>`;
  }).join("");
  return `<select id="${id}" style="font-family:var(--mono);font-size:15px;color:var(--tx);
    background:var(--bg3);border:0.5px solid var(--b2);border-radius:50px;height:52px;
    padding:0 16px;width:100%;-webkit-appearance:none;appearance:none">${
    opts || '<option value="">No ports found</option>'}</select>`;
}

SCREEN.ETHERNET = {
  TEST: () => {
    const s = state.ethScore;
    const busy = Boolean(state.running);
    const note = state.ethCanTest ? "" :
      `<div class="verdict-sub" style="color:var(--wn)">ethtool is not installed, so no
       ethernet test can run. Run deploy/setup-pi.sh.</div>`;
    return card(
      `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
        height:100%;gap:2px">${gauge(s ? s.score : null, s ? s.band : null)}
        <div style="font-family:var(--disp);font-weight:700;font-size:12px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--mu)">Health score</div></div>`,
      "width:318px;flex-shrink:0") +
    `<div class="grow" style="display:flex;flex-direction:column;gap:11px;min-width:0">
       ${card(`<div class="verdict" style="${s ? `color:var(${BAND_VAR[s.band]})` : ''}">${
          s ? s.verdict : "Ready."}</div>
          <div class="verdict-sub">${s && s.suspect_pairs
            ? "Suspect pairs " + s.suspect_pairs
            : "Run the cable under test between the two ports below, then start the sweep."}</div>${note}`)}
       ${card(`<div class="row" style="align-items:center;gap:12px">
          <div style="flex-grow:1">${ifaceOptions("eth-a")}</div>
          <span style="color:var(--mu);font-size:19px">&harr;</span>
          <div style="flex-grow:1">${ifaceOptions("eth-b")}</div></div>`, "flex-grow:0")}
       <div class="grow"></div>
       ${btn("btn-eth", "Run speed sweep", { kind: "primary", big: true,
             sub: "10, 100 and 1000 Mb", disabled: busy || !state.ethCanTest })}
       ${btn("btn-cancel", "Cancel", { kind: "danger", disabled: !busy, style: "height:56px" })}
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
    `<div style="display:flex;justify-content:center">${db9(null)}</div>
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

const SETUP = () => {
  const canExport = Boolean(state.lastPinJob);
  return card(h2("Sweep settings", "Tap to edit") +
      (state.settings.length
        ? state.settings.map((s) => settingRow(s, null, true)).join("")
        : empty("Loading.")) +
      `<div class="grow"></div>` +
      btn("btn-reset", "Reset all to factory", {}),
      "flex-grow:1") +
    card(h2("Instrument") +
    [["Version", window.CT.version],
     ["Payload per rate", "2.0 s"],
     ["Settle time", "120 ms"],
     ["Mode", window.CT.simulating ? "SIMULATION" : "Live hardware"]]
      .map(([k, v]) => `<div class="trow"><span style="flex-grow:1;font-size:14.5px">${k}</span>
        <span class="mono m" style="font-size:15px">${v}</span></div>`).join("") +
    `<div class="grow"></div>
     <div class="row">${btn("btn-dark", "Dark", { kind: "primary" })}
       ${btn("btn-light", "Light", {})}</div>
     <div class="grow"></div>
     <div class="row">${btn("btn-json", "Export JSON", { disabled: !canExport })}
       ${btn("btn-print", "Print report", { kind: "primary", disabled: !canExport })}</div>`,
    "width:352px;flex-shrink:0");
};
SCREEN.SERIAL.SETUP = SETUP;
SCREEN.ETHERNET.SETUP = SETUP;

/* ---------------------------------------------------------------- render */

const STATE_TEXT = {
  TEST: "Ready", PINS: "Pin check", SWEEP: "Baud sweep",
  PAIRS: "Pairs", SPEED: "Speed sweep", WIRING: "Reference", SETUP: "Setup",
};

function render() {
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
  const port = $("port").value;
  if (!port) { showAlert("Select a port first."); return; }
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
      body: JSON.stringify({ port: $("port").value, pincheck: state.pinJob,
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
  const a = $("eth-a") ? $("eth-a").value : "";
  const b = $("eth-b") ? $("eth-b").value : "";
  if (!a || !b) { showAlert("Pick both ports.", "The cable needs two ends."); return; }
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
  document.documentElement.classList.toggle("dark", dark);
  try { localStorage.setItem("cabletester-theme", dark ? "dark" : "light"); } catch (_) {}
  render();
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("cabletester-theme"); } catch (_) {}
  // Dark by default and deliberately NOT following the device: this runs full
  // screen on a shop bench, often in a dim building. An explicit choice sticks.
  document.documentElement.classList.toggle("dark", saved !== "light");
}

async function loadPorts() {
  const select = $("port");
  const previous = select.value;
  try {
    const data = await api("/api/ports");
    state.ports = data.ports;
    select.innerHTML = data.ports.length
      ? data.ports.map((p) => `<option value="${p.device}">${p.device} · ${
          p.description}${p.vid_pid ? "  [" + p.vid_pid + "]" : ""}</option>`).join("")
      : '<option value="">No serial ports found</option>';
    if (previous && data.ports.some((p) => p.device === previous)) select.value = previous;
  } catch (err) { showAlert("Could not list serial ports.", err.message); }
}

async function loadInterfaces() {
  try {
    const data = await api("/api/eth/interfaces");
    state.ifaces = data.interfaces || [];
    state.ethCanTest = data.can_test !== false;
    const testable = state.ifaces.filter((i) => i.testable);
    if (state.proto === "ETHERNET") render();
    // Preselect the two testable ports, since a two-port kit has exactly two.
    if (testable.length >= 2 && $("eth-a") && $("eth-b")) {
      $("eth-a").value = testable[0].iface;
      $("eth-b").value = testable[1].iface;
    }
  } catch (err) { state.ifaces = []; state.ethCanTest = false; }
}

function init() {
  initTheme();
  $("refresh").onclick = () => { loadPorts(); loadInterfaces(); };
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
