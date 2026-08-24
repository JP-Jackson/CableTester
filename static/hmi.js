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
  ethOrientation: null,
  // Which step of the flow the test screen is showing the detail of. Null
  // means "follow the run", which is what it does until somebody taps a tile.
  step: null,
  // Which reference diagram the wiring screen is showing.
  tab: "loopback",
  // Live run timing, for the dial while a test is in flight.
  runStart: null,
  runEta: 0,
  runRates: null,
  runTicker: null,
  liveBps: 0,
  liveBaud: null,
  loadMbps: 0,
  loadFrames: 0,
  loadResult: null,
  // Used once, when a report is printed. Kept in state rather than in the DOM
  // because the screen it is typed on is rebuilt on every render.
  cableId: "",
};

/* Start again on the next cable. The instrument sits on a bench and grades one
   cable after another, so getting back to a clean slate is a first-class
   action rather than something you achieve by reloading the page. */
function clearResults() {
  Object.assign(state, {
    pinJob: null, lastPinJob: null, sweepJob: null, pinResult: null,
    sweepRates: {}, score: null, ethRungs: [], ethScore: null, loadResult: null,
    ethOrientation: null,
    monEvents: [], monResult: null, monStart: null, monRate: 0, monOpen: [],
    step: null, screen: "TEST",
  });
  state.cableId = "";
  clearAlert();
  setLamp(null);
  setState("Ready");
  render();
}

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

/* Bits on the wire. Labelled in bits, because that is what it is: the old
   version divided this by 1000 and called it kB/s, so 1200 baud read as
   "1.20 kB/s" when it is 1.2 kbit/s, or 150 bytes. Wrong unit and wrong by
   a factor of eight. */
function fmtBits(bps) {
  if (!bps && bps !== 0) return DASH;
  if (bps >= 1000) return `${fmt(bps / 1000, 1)} kbit/s`;
  return `${fmt(bps, 0)} bit/s`;
}

/* Payload bytes per second, auto-ranged. This is the number to compare
   against the size of a file, so it is the one the dial shows. */
function fmtBytes(Bps) {
  if (!Bps && Bps !== 0) return DASH;
  if (Bps >= 1e6) return `${fmt(Bps / 1e6, 2)} MB/s`;
  if (Bps >= 1000) return `${fmt(Bps / 1000, 2)} kB/s`;
  return `${fmt(Bps, 0)} B/s`;
}

/* Split so the dial can show the number large and its unit small underneath. */
function splitBytes(Bps) {
  if (!Bps && Bps !== 0) return [DASH, "B/s"];
  if (Bps >= 1e6) return [fmt(Bps / 1e6, 2), "MB/s"];
  if (Bps >= 1000) return [fmt(Bps / 1000, 2), "kB/s"];
  return [fmt(Bps, 0), "B/s"];
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

const STEP_FOR_RUN = { pincheck: "pins", sweep: "sweep", eth: "speed",
                       ethload: "load", continuity: "flex" };

function setRunning(kind) {
  if (kind && kind !== state.running) {
    state.runStart = Date.now();
    state.liveBps = 0;
    // The dial's clock has to move even between events. A sweep at 1200 baud
    // emits nothing for seconds at a time and a frozen dial reads as a hang.
    clearInterval(state.runTicker);
    state.runTicker = setInterval(() => {
      if (state.running && state.screen === "TEST") render();
    }, 500);
  }
  if (!kind) {
    clearInterval(state.runTicker);
    state.runTicker = null;
    state.runStart = null;
    state.runEta = 0;
  }
  state.running = kind;
  // Follow the run. Starting a test and then having to go and find its
  // output was the complaint that reshaped this screen.
  if (kind && STEP_FOR_RUN[kind]) state.step = STEP_FOR_RUN[kind];
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
ICON.CONTINUITY = '<path d="M2 12c3-6 5 6 8 0s5 6 8 0 4-3 4-3"/>';

/* The rail is reference and detail. The procedure itself lives on TEST, so
   SWEEP and SPEED are not here: their tables are what the test screen shows
   while that step is selected, and having them in two places meant the result
   of the thing you just started was somewhere you had to go and find. */
const NAV = {
  SERIAL:   ["TEST", "PINS", "CONTINUITY", "WIRING", "SETUP"],
  ETHERNET: ["TEST", "PAIRS", "CONTINUITY", "WIRING", "SETUP"],
};

/* What the rail calls each screen. Separate from the key because "CONTINUITY"
   names the measurement and "FLEX TEST" names what the technician does, and
   the second is the one that tells somebody what the screen is for. */
const NAV_LABEL = {
  TEST: "TEST", PINS: "PINS", PAIRS: "PAIRS",
  CONTINUITY: "FLEX TEST", WIRING: "WIRING", SETUP: "SETUP",
};

/* ------------------------------------------------------------- the flow */

/* Testing a cable is a procedure with an order, and the instrument now says
   so. Each step knows how to report its own state, so the strip, the primary
   button and the detail panel all read from one place and cannot disagree. */
const STEPS = {
  SERIAL: [
    { key: "connect", label: "Connect", panel: "connect" },
    { key: "pins", label: "Pin check", panel: "pins" },
    { key: "sweep", label: "Baud sweep", panel: "sweep" },
    { key: "flex", label: "Flex test", panel: "flex", optional: true },
  ],
  ETHERNET: [
    { key: "connect", label: "Connect", panel: "connect" },
    { key: "speed", label: "Speed sweep", panel: "speed" },
    { key: "load", label: "Throughput", panel: "load" },
    { key: "flex", label: "Flex test", panel: "flex", optional: true },
  ],
};

/* Is the instrument connected to something it can test?
   Reported in words on step one, because a technician should never have to
   infer from a greyed-out button that the box cannot find its adapter. */
function connectState() {
  if (state.proto === "ETHERNET") {
    if (!state.ethCanTest) {
      return { ok: false, short: "ethtool missing",
               title: "Ethernet testing is not available on this box.",
               sub: "ethtool is not installed. Run deploy/setup-pi.sh." };
    }
    if (!state.ethA || !state.ethB) {
      return { ok: false, short: "ports not set",
               title: "Both ethernet ports are not set.",
               sub: "Choose them under Setup. A cable needs two ends." };
    }
    const a = state.ifaces.find((i) => i.iface === state.ethA) || {};
    const b = state.ifaces.find((i) => i.iface === state.ethB) || {};
    const linked = a.link && b.link;
    const speed = a.speed || b.speed;
    return {
      ok: true, linked: Boolean(linked),
      short: linked ? (speed ? `linked at ${speed} Mb` : "linked") : "no link",
      title: linked
        ? `Both ports linked${speed ? " at " + speed + " Mb" : ""}.`
        : "No link between the two ports.",
      sub: `${state.ethA} to ${state.ethB}`,
    };
  }
  if (!state.ports.length) {
    return { ok: false, short: "no adapter",
             title: "No serial adapter found.",
             sub: "Check the panel connector, then tap Rescan under Setup." };
  }
  if (!state.port) {
    return { ok: false, short: "not chosen",
             title: `${state.ports.length} adapters found. Pick one.`,
             sub: "Choose it under Setup so the report names the right port." };
  }
  const pt = state.ports.find((x) => x.device === state.port) || {};
  return { ok: true, linked: true, short: state.port,
           title: "Serial adapter ready.",
           sub: `${state.port}${pt.description ? "  ·  " + pt.description : ""}` };
}

/* One status per step, from state. "ready" means it is the next thing to do. */
function stepStates() {
  const conn = connectState();
  const running = state.running;
  const out = {};

  out.connect = conn.ok
    ? { status: "pass", note: conn.short }
    : { status: "fail", note: conn.short };

  if (state.proto === "SERIAL") {
    const r = state.pinResult;
    const bad = r ? r.pins.filter((p) => !["pass", "reference", "nc"].includes(p.result)).length : 0;
    out.pins = running === "pincheck" ? { status: "busy", note: "running" }
      : r ? (r.passed ? { status: "pass", note: "all nine good" }
                      : { status: "fail", note: `${bad} fault(s)` })
          : { status: conn.ok ? "ready" : "wait", note: "not run" };

    const sc = state.score;
    out.sweep = running === "sweep" ? { status: "busy", note: "running" }
      : sc ? { status: sc.band === "red" ? "fail" : "pass", note: `scored ${Math.round(sc.score)}` }
           : { status: state.pinJob ? "ready" : "wait",
               note: state.pinJob ? "not run" : "needs a passing pin check" };
  } else {
    const sc = state.ethScore;
    const linked = state.ethRungs.filter((x) => x.link).length;
    out.speed = running === "eth" ? { status: "busy", note: "running" }
      : sc ? { status: sc.band === "red" ? "fail" : "pass",
               note: `${linked} of ${state.ethRungs.length} linked` }
           : { status: conn.ok ? "ready" : "wait", note: "not run" };
  }

  if (state.proto === "ETHERNET") {
    const ld = state.loadResult;
    out.load = running === "ethload" ? { status: "busy", note: "moving data" }
      : ld ? { status: ld.passed ? "pass" : "fail",
               note: ld.passed ? `${ld.mbps} Mb/s clean`
                               : `${ld.frames_lost + ld.crc_errors} bad frame(s)` }
           : { status: state.ethRungs.length ? "ready" : "wait", note: "not run" };
  }

  const mon = state.monResult;
  out.flex = running === "continuity" ? { status: "busy", note: "watching" }
    : mon ? (mon.passed ? { status: "pass", note: `${mon.elapsed_s}s clean` }
                        : { status: "fail", note: `${mon.dropouts} dropout(s)` })
          : { status: conn.ok ? "ready" : "wait", note: "optional" };
  return out;
}

/* The one button that always does the next sensible thing.
   Its label is the action, never a mode, so nobody has to work out what
   tapping it will do. */
function nextAction() {
  const states = stepStates();
  const busy = Boolean(state.running);
  if (busy) return { id: "btn-cancel", label: "Cancel", kind: "danger", sub: "Stop this test" };

  if (states.connect.status !== "pass") {
    return { id: "btn-goto-SETUP", label: "Open setup", kind: "primary",
             sub: "The tester cannot see what it needs to test" };
  }
  if (state.proto === "SERIAL") {
    if (states.pins.status !== "pass") {
      return { id: "btn-pincheck", label: states.pins.status === "fail"
        ? "Run pin check again" : "Run pin check", kind: "primary",
        sub: states.pins.status === "fail"
          ? "Repair the cable first, then re-check" : "Two seconds" };
    }
    if (states.sweep.status !== "pass" && states.sweep.status !== "fail") {
      return { id: "btn-sweep", label: "Run baud sweep", kind: "primary",
               sub: settingSummary() };
    }
  } else {
    if (states.speed.status !== "pass" && states.speed.status !== "fail") {
      return { id: "btn-eth", label: "Run speed sweep", kind: "primary",
               sub: "10, 100 and 1000 Mb" };
    }
    if (states.load.status !== "pass" && states.load.status !== "fail") {
      return { id: "btn-load", label: "Run throughput test", kind: "primary",
               sub: "Move real data and count what does not arrive" };
    }
  }
  if (states.flex.status === "wait" || states.flex.status === "ready") {
    return { id: "btn-mon", label: "Run flex test", kind: "primary",
             sub: "Find faults that only appear when the cable moves" };
  }
  return { id: "btn-reset-run", label: "Test another cable", kind: "",
           sub: "Clear these results and start again" };
}

function settingSummary() {
  const s = state.settings.find((x) => x.id === state.chosen);
  return s ? `${s.name}, about ${s.duration}` : "Choose how hard to work it";
}

/* Which step panel to show. Follows the run, and follows a tap. */
function activeStep() {
  const names = STEPS[state.proto].map((x) => x.key);
  if (state.step && names.includes(state.step)) return state.step;
  const states = stepStates();
  return names.find((k) => states[k] && states[k].status !== "pass")
    || names[names.length - 1];
}

const TICK_SVG = '<svg viewBox="0 0 24 24"><path d="M4 12.5l5.5 5.5L20 7"/></svg>';
const CROSS_SVG = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';

function stepStrip() {
  const states = stepStates();
  const here = activeStep();
  return `<div class="steps">${STEPS[state.proto].map((step, i) => {
    const st = states[step.key] || { status: "wait", note: "" };
    const cls = { pass: "pass", fail: "fail", busy: "busy" }[st.status] || "";
    const badge = st.status === "pass" ? TICK_SVG
      : st.status === "fail" ? CROSS_SVG : String(i + 1);
    return `<button class="step ${cls}${step.key === here ? " on" : ""}"
        data-step="${step.key}">
      <span class="num">${badge}</span>
      <span class="txt"><span class="nm">${step.label}</span>
        <span class="st">${st.note}</span></span>
    </button>`;
  }).join("")}</div>`;
}

/* Gauge: a 240 degree arc. The dash length is the arc length, so the value
   is set by dash offset rather than by recomputing trigonometry. */
const ARC_PATH = "M 54.7 187 A 110 110 0 1 1 245.3 187";
const ARC_LEN = 460.77;
const BAND_VAR = { green: "--good", amber: "--wn", red: "--bad" };

/* The gauge has two jobs and they never overlap in time.
 *
 * While a test runs it is a progress meter: the arc is how far through the run
 * is, the number is what the cable is doing RIGHT NOW, and the caption is how
 * long it has been going against how long it should take. A test that takes
 * most of a minute with a dash in the middle of the dial reads as an
 * instrument that has hung.
 *
 * When the run ends it is the health score again. Same dial, same arc, so the
 * needle settling onto the final number is the answer arriving.
 */
function gauge(score, band, live) {
  if (live) return gaugeLive(live);
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

function gaugeLive(live) {
  const pct = Math.max(0, Math.min(100, live.percent || 0));
  const dash = (ARC_LEN * pct) / 100;
  // Big enough to read at arm's length, and it has to shrink for "115.2"
  // without spilling out of the dial.
  const size = String(live.value).length >= 5 ? 62 : 76;
  return `<svg viewBox="0 0 300 206" style="width:100%;max-width:296px">
    <path d="${ARC_PATH}" fill="none" stroke="var(--bg3)" stroke-width="17" stroke-linecap="round"/>
    <path d="${ARC_PATH}" fill="none" stroke="var(--ml)" stroke-width="17" stroke-linecap="round"
          stroke-dasharray="${dash} ${ARC_LEN}"/>
    <text x="150" y="140" text-anchor="middle" font-family="var(--disp)" font-weight="800"
          font-size="${size}" fill="var(--tx)">${live.value}</text>
    <text x="150" y="168" text-anchor="middle" font-family="var(--sans)" font-weight="600"
          font-size="15" letter-spacing="1.6" fill="var(--mu)">${live.unit}</text>
  </svg>`;
}

function mmss(seconds) {
  const t = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/* What the dial should show for whatever is running, or null when nothing is.
   One place, so the gauge, the caption and the progress cannot disagree. */
function liveGauge() {
  const kind = state.running;
  if (!kind) return null;
  const elapsed = state.runStart ? (Date.now() - state.runStart) / 1000 : 0;
  const eta = state.runEta || 0;
  const clock = eta ? `${mmss(elapsed)} of ${mmss(eta)}` : mmss(elapsed);

  if (kind === "sweep") {
    const wanted = state.runRates && state.runRates.length
      ? state.runRates : window.CT.bauds;
    const done = wanted.filter((b) => state.sweepRates[b] && state.sweepRates[b].grade).length;
    // Time is the better progress estimate when there is one: rates are not
    // equal in length, so counting them jumps in uneven steps.
    const percent = eta ? Math.min(99, (elapsed / eta) * 100)
                        : (done / wanted.length) * 100;
    // The RATE, not the throughput. Throughput in kB/s reads "0.3" at the
    // bottom of the sweep, which is a true number that tells a technician
    // nothing and looks like something is wrong. Which rate the cable is
    // being worked at is the thing they actually want to see moving.
    const at = state.liveBaud || wanted[Math.min(done, wanted.length - 1)];
    return { percent, value: at ? at.toLocaleString() : DASH, unit: "baud",
             caption: `${clock}   rate ${Math.min(done + 1, wanted.length)} of ${wanted.length}` };
  }
  if (kind === "ethload") {
    const pct = eta ? Math.min(99, (elapsed / eta) * 100) : 0;
    return { percent: pct, value: state.loadMbps ? fmt(state.loadMbps, 0) : DASH,
             unit: "Mb/s",
             caption: `${clock}   ${(state.loadFrames || 0).toLocaleString()} frames` };
  }
  if (kind === "eth") {
    const done = state.ethRungs.length;
    const last = done ? state.ethRungs[state.ethRungs.length - 1] : null;
    return { percent: (done / ETH_SPEEDS.length) * 100,
             value: last && last.negotiated ? last.negotiated : DASH, unit: "Mb/s",
             caption: `${mmss(elapsed)}   ${done} of ${ETH_SPEEDS.length} speeds` };
  }
  if (kind === "pincheck") {
    return { percent: Math.min(95, (elapsed / 2.2) * 100), value: DASH, unit: "checking pins",
             caption: mmss(elapsed) };
  }
  if (kind === "continuity") {
    // No end time: this one runs until the technician stops it, so the arc is
    // not progress towards anything. It shows the sample rate instead, which
    // is the thing that proves the monitor is alive.
    return { percent: 100, value: state.monRate ? Math.round(state.monRate).toLocaleString() : DASH,
             unit: "samples/s", caption: `${mmss(elapsed)}   watching` };
  }
  return null;
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

function db9(pins, view, highlight, jumpers) {
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

  // Jumpers are drawn BEFORE the pins so the pins sit on top of them, which is
  // how the wire actually disappears behind the pin it is soldered to. Drawn
  // as arcs rather than straight lines because 4 to 1 to 6 would otherwise run
  // straight through pins 2 and 3 and read as connecting them.
  for (const [a, b, colour, bow] of jumpers || []) {
    if (!pos[a] || !pos[b]) continue;
    // Always draw left to right. A quadratic curve is identical drawn either
    // way, but the perpendicular offset is not: taking the pins in their
    // listed order would flip every arc when the female shell mirrors the
    // rows, so 2 to 3 would bow up on one view and down on the other.
    const [from, to] = pos[a][0] <= pos[b][0] ? [pos[a], pos[b]] : [pos[b], pos[a]];
    const dx = to[0] - from[0], dy = to[1] - from[1];
    const len = Math.hypot(dx, dy) || 1;
    const cx = (from[0] + to[0]) / 2 - (dy / len) * bow;
    const cy = (from[1] + to[1]) / 2 + (dx / len) * bow;
    out += `<path d="M${from[0]} ${from[1]} Q${cx.toFixed(1)} ${cy.toFixed(1)} ${to[0]} ${to[1]}"
             fill="none" stroke="var(${colour})" stroke-width="5" stroke-linecap="round"/>`;
  }
  for (const n of Object.keys(pos)) {
    const [x, y] = pos[n];
    const res = byPin[n] ? byPin[n].result : null;
    const tone = hot.has(Number(n)) ? "r" : (res ? RESULT_TONE[res] || "m" : null);
    const c = tone ? `var(${{ g: "--good", w: "--wn", r: "--bad", m: "--mu" }[tone]})`
                   : "var(--mu)";
    const solid = hot.has(Number(n)) || (res && tone !== "m");
    // A male shell has PINS and a female shell has SOCKETS, and the drawing
    // says which rather than leaving it to the row order: a male pin is a
    // filled dot sitting proud, a female socket is an open circle you look
    // into. Order alone is easy to misread, and a technician who has the
    // shell wrong counts from the wrong end and repairs the wrong pin.
    const width = hot.has(Number(n)) ? 3.2 : 2.4;
    // Fully hollow against fully solid, not two shades of the same fill. A
    // subtler difference was there first and the two shells were impossible
    // to tell apart at a glance, which is the entire job of this drawing.
    out += female
      ? `<circle class="pin" cx="${x}" cy="${y}" r="13" fill="none"
           stroke="${c}" stroke-width="${width}"/>
         <circle cx="${x}" cy="${y}" r="9.2" fill="none" stroke="${c}"
           stroke-width="1" stroke-opacity=".55"/>
         <text x="${x}" y="${y + 5}" text-anchor="middle" font-family="var(--mono)"
           font-size="12" font-weight="700" fill="${c}">${n}</text>`
      : `<circle class="pin" cx="${x}" cy="${y}" r="13" fill="${c}"
           fill-opacity="${solid ? '1' : '.72'}" stroke="${c}" stroke-width="${width}"/>
         <text x="${x}" y="${y + 5}" text-anchor="middle" font-family="var(--mono)"
           font-size="12" font-weight="700" fill="var(--bg2)">${n}</text>`;
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

const RUNNING_TEXT = {
  pincheck: ["Checking every pin.", "Asserting each output in turn and reading what comes back."],
  sweep: ["Working the cable at speed.", "Every rate in turn, counting the bytes that come back wrong."],
  eth: ["Walking the link speeds.", "Each speed offered on its own. What links tells you which pairs carry."],
  ethload: ["Moving real data.", "Frames down the cable at full rate, counting what does not arrive intact."],
  continuity: ["Watching for opens.", "Move the cable while this runs. That is the test."],
};

function verdictParts() {
  const s = state.score;
  const pin = state.pinResult;
  let text, sub, tone = "";
  // A run in progress owns this line. It read "Run the sweep for a health
  // score" while the sweep was running, which is the screen offering you the
  // thing it is already doing.
  if (state.running && RUNNING_TEXT[state.running]) {
    const [t, sb] = RUNNING_TEXT[state.running];
    return { text: t, sub: sb, tone: "color:var(--ml)" };
  }
  if (s) {
    text = s.verdict;
    tone = `color:var(${BAND_VAR[s.band]})`;
    sub = (s.sensitivity_text ? s.sensitivity_text + " " : "") +
          `Scored across ${s.per_rate.length} rate(s), ${s.coverage}% of the ` +
          `weighted range.`;
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


/* ------------------------------------------------------- the test screen */

/* One screen for both protocols. The score and the next action stay put on
   the left while the right side shows whichever step is selected, so the
   answer to "what now" and the detail of what just ran are never on two
   different screens. */
function testScreen() {
  const sc = state.proto === "ETHERNET" ? state.ethScore : state.score;
  const act = nextAction();
  const panel = PANEL[activeStep()] || panelConnect;
  const live = liveGauge();
  return `<div class="stack">${stepStrip()}<div class="cols">` +
    card(
      `<div style="display:flex;flex-direction:column;align-items:center;gap:1px">
        ${gauge(sc ? sc.score : null, sc ? sc.band : null, live)}
        <div style="font-family:${live ? "var(--mono)" : "var(--disp)"};font-weight:700;
          font-size:${live ? "13.5px" : "11.5px"};letter-spacing:${live ? ".02em" : ".16em"};
          text-transform:${live ? "none" : "uppercase"};
          color:var(${live ? "--ml" : "--mu"})">${
          live ? live.caption : "Health score"}</div>
       </div>
       <div class="grow"></div>
       ${verdictInline()}
       <div class="grow"></div>
       ${btn(act.id, act.label, { kind: act.kind, big: true, sub: act.sub })}`,
      "width:312px;flex-shrink:0") +
    panel() +
    `</div></div>`;
}

/* Step one, and the single biggest fix for not knowing what to do next: say
   what the instrument can actually see, in words, before anything is run. */
function panelConnect() {
  const c = connectState();
  const tone = c.ok ? (c.linked === false ? "--wn" : "--good") : "--bad";
  const eth = state.proto === "ETHERNET";
  const how = eth
    ? `<p style="margin-bottom:9px"><b>1.</b> Plug the cable into both ethernet ports on the panel.</p>
       <p style="margin-bottom:9px"><b>2.</b> Push each plug in until the clip clicks.</p>
       <p><b>3.</b> Give the ports a few seconds to negotiate, then run the speed sweep.</p>`
    : `<p style="margin-bottom:9px"><b>1.</b> Plug the cable into the DB9 on the panel.</p>
       <p style="margin-bottom:9px"><b>2.</b> Fit the loopback plug to the far end of the cable.</p>
       <p><b>3.</b> Check both shells are seated, then run the pin check.</p>`;
  return card(h2("What the tester can see") +
    `<div class="conn">
       <span class="ic" style="color:var(${tone})">${c.ok ? "&check;" : "!"}</span>
       <span class="txt"><span class="nm">${c.title}</span>
         <span class="sub">${c.sub}</span></span>
     </div>
     <div class="grow"></div>
     ${h2("Set the cable up")}
     <div class="todo">${how}</div>
     <div class="grow"></div>
     <div class="row">
       ${btn("btn-refresh", "Rescan ports", { style: "flex-grow:1" })}
       ${btn("btn-goto-WIRING", "Wiring reference", { style: "flex-grow:1" })}
     </div>`, "flex-grow:1");
}

/* The connector, not the table. Which PIN is bad is the thing a technician
   acts on, and the rail's own PINS screen carries the full grading. */
function panelPins() {
  const r = state.pinResult;
  const bad = r ? r.pins.filter((p) => !["pass", "reference", "nc"].includes(p.result)).length : 0;
  const faulty = r ? r.pins.filter((p) => !["pass", "reference", "nc"].includes(p.result)) : [];
  return card(h2("Pin check", r ? (bad ? `${bad} fault(s)` : "all nine good") : "not run") +
    (r
      ? `<div style="display:flex;justify-content:center;margin-top:2px">${
           db9(r.pins, state.shell)}</div>
         ${shellToggle()}
         <div style="font-size:13px;color:var(--mu);line-height:1.45;margin-top:10px">${
           bad
             ? faulty.map((p) => `<b style="color:var(--bad)">Pin ${p.pin} ${p.signal}</b>: ${
                 p.detail || RESULT_LABEL[p.result] || p.result}`).join("<br>")
             : r.topology.label}</div>`
      : empty("Run the pin check. It proves every conductor is joined end to end before "
              + "anything is measured at speed.")) +
    `<div class="grow"></div>
     ${btn("btn-goto-PINS", "Every pin graded", { disabled: !r })}`, "flex-grow:1");
}

/* The sweep table, on the screen the sweep is started from. */
/* One bar per rate, doing two jobs in sequence.
 *
 * While a rate is being worked it fills as its payload goes through, so you
 * can see WHICH rate is running and how far into it the sweep is. A single
 * dial cannot show that: eight rates take very unequal times and the row that
 * is moving is the row worth watching.
 *
 * Once the rate has a grade the same bar becomes its quality, which is what it
 * always was. The bar does not move again after that, so a finished row reads
 * as finished. */
function rateBar(baud, entry, grade, tone) {
  if (grade) {
    return `<span class="bar"><i style="width:${Math.round(grade.credit * 100)}%;
      background:var(${tone || '--bg3'})"></i></span>`;
  }
  const running = state.running === "sweep" && state.liveBaud === baud;
  if (running) {
    // Payload time is known per rate, so this is a real fraction rather than
    // an indeterminate crawl: elapsed on this rate against what it should take.
    const started = state.rateStart || Date.now();
    const secs = state.runSecs || 0;
    const pct = secs ? Math.min(97, ((Date.now() - started) / 1000 / secs) * 100) : 40;
    return `<span class="bar"><i style="width:${pct.toFixed(0)}%;background:var(--ml)"></i></span>`;
  }
  const pending = state.running === "sweep";
  return `<span class="bar"><i style="width:0%"></i></span>${
    pending ? '' : ''}`;
}

function panelSweep() {
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
    return `<div class="trow" style="height:40px">
      <span class="mono" style="width:76px;font-size:15px">${baud.toLocaleString()}</span>
      <span style="width:88px">${chip(e.none)}</span>
      <span style="width:88px">${chip(e.even)}</span>
      <span class="mono ${e.none && e.none.mismatched ? 'r' : 'm'}"
            style="width:52px">${e.none ? (e.none.mismatched + e.none.missing) : DASH}</span>
      <span class="mono m" style="width:86px">${e.none ? fmtBytes(e.none.throughput_Bps) : DASH}</span>
      ${rateBar(baud, e, g, tone)}</div>`;
  }).join("");
  const s = state.score;
  return card(
    h2("Baud sweep", s ? `${s.per_rate.filter((r) => r.status === "pass").length} of ${
       s.per_rate.length} clean` : (state.running === "sweep" ? "running" : "not run")) +
    `<div class="thead"><span style="width:76px">Rate</span><span style="width:88px">No parity</span>
      <span style="width:88px">Even parity</span><span style="width:52px">Errors</span>
      <span style="width:86px">Throughput</span><span class="grow">Quality</span></div>` +
    rows +
    `<div class="grow"></div>
     <div style="font-size:12.5px;color:var(--mu);line-height:1.4;margin-top:8px">${
       s ? s.verdict
         : "Every rate is tried in turn. A cable that passes at 9600 and fails at 115200 is "
           + "the case a continuity check cannot see."}</div>` +
     // How much this result is entitled to claim. A green score means "good
     // to the depth we looked", and without this line nobody can tell how
     // deep that was.
     (s && s.sensitivity_text
       ? `<div style="font-size:12px;color:var(--wn);line-height:1.4;margin-top:7px;
            border-top:0.5px solid var(--b1);padding-top:7px">${s.sensitivity_text}</div>`
       : ""), "flex-grow:1");
}

const SCREEN = {
SERIAL: {
  TEST: () => testScreen(),

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

},
};

/* ---------------------------------------------------- ethernet screens */

/* Standard-independent: T568A and T568B swap the orange and green pairs
   wholesale, so the physical connection is identical either way. Blue and
   brown never move. That is why this chart needs no standard selector. */
/* Signal to DB9 pin. A technician repairs a pin, not a signal name. */
const PIN_FOR = { CTS: 8, DSR: 6, DCD: 1, RI: 9, Data: "2 and 3" };

/* Name a conductor the way a technician goes and looks at it. Ethernet lines
   have no DB9 pin, and reaching for this table regardless produced findings
   reading "Link A pin ?", which reads as the instrument having lost track of
   what it was measuring. */
function lineName(line) {
  const pin = PIN_FOR[line];
  if (!pin) return line;
  return `${line} (pin${String(pin).includes("and") ? "s" : ""} ${pin})`;
}

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
  TEST: () => testScreen(),

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

};

/* The ladder, on the screen it is started from, with the pairs it implicates
   underneath. Which speeds link IS the pair diagnosis, so showing them apart
   made the reader do the join themselves. */
function panelSpeed() {
  const best = state.ethScore ? state.ethScore.best_speed : null;
  const rows = ETH_SPEEDS.map((sp) => {
    const r = state.ethRungs.find((x) => x.speed === sp);
    const chip = !r ? `<span class="chip m">${DASH}</span>`
      : `<span class="chip ${r.link ? "g" : "r"}">${r.link ? "Link" : "No link"}</span>`;
    return `<div class="trow" style="height:48px">
      <span class="mono" style="width:96px;font-size:17px">${sp} Mb</span>
      <span style="width:110px">${chip}</span>
      <span class="mono m" style="width:96px">${r && r.link && r.negotiated
            ? r.negotiated + "Mb/s" : DASH}</span>
      <span class="grow" style="font-size:13px;color:var(--mu)">${
        sp === 1000 ? "needs all four pairs" : "orange and green only"}</span></div>`;
  }).join("");
  const pairs = PAIR_INFO.map(([name, pins, colour, needs]) => {
    let label = DASH, tone = "m";
    if (best !== null) {
      const ok = best >= needs;
      label = ok ? "carrying" : "suspect";
      tone = ok ? "g" : "w";
    }
    return `<div style="display:flex;align-items:center;gap:9px;flex:1 1 0;min-width:0;
      height:44px;padding:0 11px;border-radius:9px;background:var(--bg3)">${swatch(colour, true)}
      <div style="min-width:0;flex-grow:1">
        <div style="font-size:13px">${name}</div>
        <div class="mono" style="font-size:10.5px;color:var(--mu)">${pins}</div></div>
      <span class="${tone}" style="font-size:10px;font-weight:700;letter-spacing:.08em;
        text-transform:uppercase">${label}</span></div>`;
  }).join("");
  const s = state.ethScore;
  return card(
    h2("Speed sweep", s ? `${state.ethRungs.filter((r) => r.link).length} of ${
       state.ethRungs.length} linked` : (state.running === "eth" ? "running" : "not run")) +
    `<div class="thead"><span style="width:96px">Speed</span><span style="width:110px">Link</span>
      <span style="width:96px">Negotiated</span><span class="grow">Pairs needed</span></div>` +
    rows +
    `<div class="grow"></div>
     ${h2("Pairs", s && s.suspect_pairs ? "fault localised" : "")}
     <div class="row" style="gap:8px">${pairs}</div>
     <div style="font-size:12.5px;color:var(--mu);line-height:1.4;margin-top:9px">${
       s ? s.verdict
         : "The highest speed that links says which conductors are carrying. Gigabit needs all "
           + "four pairs; 10 and 100 need only two."}</div>` +
     // Reported, never scored. A crossover is a legitimate cable and this
     // tester links on one and grades it the same as any other.
     (state.ethOrientation
       ? `<div style="font-size:12px;line-height:1.4;margin-top:7px;
            border-top:0.5px solid var(--b1);padding-top:7px;color:var(${
              state.ethOrientation.kind === "crossover" ? "--wn" : "--mu"})">
            <b style="color:var(--tx)">${
              ({ straight: "Straight-through", crossover: "Crossover",
                 unknown: "Wiring not readable" })[state.ethOrientation.kind]}.</b>
            ${state.ethOrientation.detail}</div>`
       : ""), "flex-grow:1");
}

/* The flex test keeps its own screen, because watching needs the whole panel.
   This is the invitation to it, and the record of the last one. */
function panelFlex() {
  const mon = state.monResult;
  const serial = state.proto === "SERIAL";
  const body = mon
    ? `<div class="conn">
         <span class="ic" style="color:var(${mon.passed ? "--good" : "--bad"})">${
           mon.passed ? "&check;" : "!"}</span>
         <span class="txt"><span class="nm">${mon.passed
           ? "No opens while it was moved." : "The cable opened while it was moved."}</span>
           <span class="sub">${mon.elapsed_s}s watched  ·  ${mon.dropouts} dropout(s)</span></span>
       </div>
       <div style="font-size:13px;color:var(--mu);line-height:1.5">${mon.verdict}</div>`
    : `<div class="todo">
         <p style="margin-bottom:10px"><b>This is the test the other ones cannot do.</b> A cable
           with a conductor broken inside its insulation passes every static check, because the
           fault is not present while the cable lies still.</p>
         <p style="margin-bottom:10px">Start it, then <b>work the cable with your hands</b>: flex
           it at both connectors, at the strain reliefs, and along its length.</p>
         <p>It runs until you stop it. There is no set duration${
           serial ? "" : ", and it watches the link speed as well as the link itself"}.</p>
       </div>`;
  return card(h2("Flex test", mon ? `${mon.elapsed_s}s watched` : "optional") + body +
    `<div class="grow"></div>
     ${btn("btn-goto-CONTINUITY", mon ? "Open the flex test" : "Open the flex test", {})}`,
    "flex-grow:1");
}

/* The throughput result. This is the screen that has something to say about a
   cable that links at gigabit and then fails a large download. */
function panelLoad() {
  const r = state.loadResult;
  const busy = state.running === "ethload";
  const body = r
    ? `<div class="conn">
         <span class="ic" style="color:var(${r.passed ? "--good" : "--bad"})">${
           r.passed ? "&check;" : "!"}</span>
         <span class="txt"><span class="nm">${r.passed
           ? "Every frame arrived intact."
           : "Frames were lost or arrived damaged."}</span>
           <span class="sub">${r.frames_sent.toLocaleString()} sent  ·  ${
             r.mbps} Mb/s  ·  ${r.seconds}s</span></span>
       </div>
       <div class="thead"><span class="grow">Measurement</span><span style="width:130px">Result</span></div>
       ${[["Frames sent", r.frames_sent.toLocaleString(), "m"],
          ["Lost", r.frames_lost.toLocaleString(), r.frames_lost ? "r" : "g"],
          ["Corrupted", r.frames_corrupted.toLocaleString(), r.frames_corrupted ? "r" : "g"],
          ["CRC errors on the wire", r.crc_errors.toLocaleString(), r.crc_errors ? "r" : "g"],
         ].map(([k, v, tone]) => `<div class="trow" style="height:38px">
           <span class="grow" style="font-size:13.5px">${k}</span>
           <span class="mono ${tone}" style="width:130px">${v}</span></div>`).join("")}
       <div style="font-size:12.5px;color:var(--wn);line-height:1.4;margin-top:9px">${
         r.verdict}</div>`
    : `<div class="todo">
         <p style="margin-bottom:10px"><b>The speed sweep proves a link comes up.
           It moves no data at all.</b> A cable with marginal crosstalk can
           negotiate gigabit perfectly and still drop frames once traffic
           starts, which is the cable that passes every test and then fails a
           large download.</p>
         <p>This sends real frames down the cable at full rate and counts what
           does not arrive, plus what the network card itself rejects as
           physically damaged.</p>
       </div>`;
  return card(h2("Throughput", r ? `${r.mbps} Mb/s` : (busy ? "running" : "not run")) +
    body +
    `<div class="grow"></div>
     ${btn("btn-load", r ? "Run again" : "Run throughput test",
           { kind: r ? "" : "primary", disabled: busy || !state.ethRungs.length,
             sub: state.ethRungs.length ? "" : "Run the speed sweep first" })}`,
    "flex-grow:1");
}

/* Which panel each step shows. One table, so a step tile, the primary button
   and the detail on screen cannot get out of step with each other. */
const PANEL = {
  connect: panelConnect,
  pins: panelPins,
  sweep: panelSweep,
  speed: panelSpeed,
  load: panelLoad,
  flex: panelFlex,
};

/* ------------------------------------------------ shared screens */

const JUMPERS = [["2 to 3", "Data", "--wire-data"],
                 ["7 to 8", "Flow control", "--wire-flow"],
                 ["4 to 1 to 6", "Modem status", "--wire-modem"]];

/* ------------------------------------------------------------- wiring */

/* Three reference diagrams cannot share a panel that never scrolls, and each
   wants a different layout underneath, so the tab strip sits above the cards
   rather than inside one. Same three tabs on both protocols so the shape is
   learnable once. */
const TABS = [["loopback", "Loopback plug"], ["pinout", "Pinout"],
              ["types", "Cable types"]];

function tabStrip() {
  return `<div class="tabs">${TABS.map(([id, label]) =>
    `<button class="tab${state.tab === id ? " on" : ""}" data-tab="${id}">${label}</button>`
  ).join("")}</div>`;
}

function wiringScreen(panels) {
  const panel = panels[state.tab] || panels.loopback;
  return `<div class="stack">${tabStrip()}<div class="cols">${panel()}</div></div>`;
}

/* Every DB9 pin, by function group. The colours are the same three the jumper
   diagram uses, so a pin's colour means the same thing on both tabs. */
const DB9_PINS = [
  [1, "DCD", "in", "Carrier detect", "--wire-modem"],
  [2, "RXD", "in", "Receive data", "--wire-data"],
  [3, "TXD", "out", "Transmit data", "--wire-data"],
  [4, "DTR", "out", "Terminal ready", "--wire-modem"],
  [5, "GND", "", "Signal ground", "--mu"],
  [6, "DSR", "in", "Set ready", "--wire-modem"],
  [7, "RTS", "out", "Request to send", "--wire-flow"],
  [8, "CTS", "in", "Clear to send", "--wire-flow"],
  [9, "RI", "in", "Ring indicator", "--mu"],
];

/* 4 to 1 to 6 is two wires sharing pin 1, not one wire. Drawn as two arcs for
   that reason: a single line through pin 1 would say the loop is 4 to 6. */
const JUMPER_ARCS = [[2, 3, "--wire-data", -26], [7, 8, "--wire-flow", 26],
                     [4, 1, "--wire-modem", 40], [1, 6, "--wire-modem", -14]];

SCREEN.SERIAL.WIRING = () => wiringScreen({
  loopback: () =>
    card(h2("Loopback plug", state.shell === "male" ? "male shell" : "female shell") +
      `<div style="display:flex;justify-content:center;margin-top:2px">${
        db9(null, state.shell, null, JUMPER_ARCS)}</div>
       <div class="grow"></div>
       ${shellToggle()}
       <div style="font-size:12.5px;color:var(--mu);line-height:1.45;margin-top:9px">Pin
         numbers are moulded into the plastic. Go by those, not by position: the rows
         mirror left to right between a male and a female shell.</div>`,
      "flex-grow:1") +
    card(h2("Jumpers", "three wires") +
      JUMPERS.map(([pins, name, colour]) => `<div class="trow">
        <span style="width:26px;height:4px;border-radius:2px;background:var(${colour});
          margin-right:13px"></span>
        <span class="mono" style="width:106px">${pins}</span>
        <span style="color:var(--mu)">${name}</span></div>`).join("") +
      `<div class="trow" style="border:0"><span style="color:var(--mu);font-size:13px">
         Pin 9 is left unconnected.</span></div>
       <div class="grow"></div>
       <div style="font-size:13px;color:var(--mu);line-height:1.45">
         <p style="margin-bottom:10px"><b style="color:var(--tx)">4 to 1 to 6 is two
           wires, not one.</b> Both land on pin 1, so DTR drives DCD and DSR together.</p>
         <p>Use the shortest jumpers that will reach. Long loops inside the shell pick up
           noise and can make a good cable look marginal at 115200.</p></div>`,
      "width:330px;flex-shrink:0"),

  pinout: () =>
    card(h2("DB9 pinout", state.shell === "male" ? "male, 1 to 5 left to right"
                                                 : "female, 5 to 1 left to right") +
      `<div style="display:flex;justify-content:center;margin-top:2px">${
        db9(null, state.shell)}</div>
       <div class="grow"></div>
       ${shellToggle()}`, "width:330px;flex-shrink:0") +
    card(h2("Every pin", "in and out are from the tester") +
      `<div class="thead"><span style="width:34px">Pin</span><span style="width:62px">Signal</span>
        <span style="width:48px">Dir</span><span class="grow">What it does</span></div>` +
      DB9_PINS.map(([pin, sig, dir, what, colour]) => `<div class="trow" style="height:38px">
        <span class="mono" style="width:34px;color:var(--mu)">${pin}</span>
        <span style="width:62px;display:flex;align-items:center;gap:7px">
          <span style="width:9px;height:9px;border-radius:2px;background:var(${colour});
            flex-shrink:0"></span><b style="font-weight:600">${sig}</b></span>
        <span class="mono m" style="width:48px;font-size:12px">${dir || DASH}</span>
        <span class="grow" style="font-size:13.5px;color:var(--mu)">${what}</span></div>`).join(""),
      "flex-grow:1"),

  types: () => card(h2("Straight-through against null modem", "both are legitimate cables") +
    `<div style="display:flex;gap:22px;margin-top:2px;flex-grow:1;min-height:0">
       ${wireMap("Straight-through", "Every pin to the same pin. What a PC to modem lead is.",
                 [[1,1],[2,2],[3,3],[4,4],[5,5],[6,6],[7,7],[8,8]], false)}
       ${wireMap("Null modem", "Transmit meets receive. What connects two computers.",
                 [[2,3],[3,2],[5,5],[7,8],[8,7],[4,6],[4,1],[6,4],[1,4]], true)}
     </div>
     <div style="font-size:13px;color:var(--mu);line-height:1.45;margin-top:10px">
       <b style="color:var(--wn)">This tester cannot tell you which one you are holding.</b>
       Through a symmetric loopback plug the two read identically, and that is physics
       rather than a limitation of the software. The pin check reports the ambiguity
       instead of guessing. Go by the cable's label, or by what it is plugged into.</div>`,
    "flex-grow:1"),
});

/* Two columns of pins with the wires drawn between them. The clearest way to
   show a mapping, and the one every RS-232 reference uses, so it is the
   drawing a technician has probably already seen. */
function wireMap(title, sub, pairs, crossed) {
  const LEFT = 26, RIGHT = 188, TOP = 16, STEP = 26;
  const rows = [1, 2, 3, 4, 5, 6, 7, 8];
  const y = (pin) => TOP + (rows.indexOf(pin)) * STEP;
  const sig = {};
  DB9_PINS.forEach(([pin, s, , , colour]) => { sig[pin] = [s, colour]; });
  let out = "";
  for (const [a, b] of pairs) {
    const colour = sig[a] ? sig[a][1] : "--mu";
    // A gentle S rather than a straight line: on the crossed map several wires
    // share a y and a straight line would lie on top of the pin labels.
    out += `<path d="M${LEFT + 16} ${y(a)} C${LEFT + 70} ${y(a)} ${RIGHT - 70} ${y(b)} ${RIGHT - 16} ${y(b)}"
            fill="none" stroke="var(${colour})" stroke-width="2.2" opacity=".85"/>`;
  }
  for (const pin of rows) {
    for (const [x, anchor] of [[LEFT, "end"], [RIGHT, "start"]]) {
      const cx = x === LEFT ? x + 16 : x - 16;
      out += `<circle cx="${cx}" cy="${y(pin)}" r="3.4" fill="var(--mu)"/>
        <text x="${x === LEFT ? x + 6 : x - 6}" y="${y(pin) + 4}" text-anchor="${anchor}"
          font-family="var(--mono)" font-size="11.5" fill="var(--mu)">${pin} ${
          sig[pin] ? sig[pin][0] : ""}</text>`;
    }
  }
  return `<div style="flex:1 1 0;min-width:0;display:flex;flex-direction:column">
    <div style="font-family:var(--disp);font-weight:700;font-size:14px;letter-spacing:.09em;
      text-transform:uppercase;color:var(${crossed ? "--ml" : "--tx"})">${title}</div>
    <div style="font-size:12px;color:var(--mu);line-height:1.35;margin:3px 0 6px">${sub}</div>
    <svg viewBox="0 0 214 214" style="width:100%;flex-grow:1;min-height:0">${out}</svg>
  </div>`;
}

/* T568B pin order, which is the one in the field. T568A swaps the orange and
   green pairs wholesale; both are listed because a technician terminating an
   end needs whichever the other end used. */
const RJ45_PINS = [
  [1, "White/Orange", "White/Green", "#e08a3c", "#3faa62", "TX+"],
  [2, "Orange", "Green", "#e08a3c", "#3faa62", "TX-"],
  [3, "White/Green", "White/Orange", "#3faa62", "#e08a3c", "RX+"],
  [4, "Blue", "Blue", "#4f7fd6", "#4f7fd6", "gigabit"],
  [5, "White/Blue", "White/Blue", "#4f7fd6", "#4f7fd6", "gigabit"],
  [6, "Green", "Orange", "#3faa62", "#e08a3c", "RX-"],
  [7, "White/Brown", "White/Brown", "#9a6b4a", "#9a6b4a", "gigabit"],
  [8, "Brown", "Brown", "#9a6b4a", "#9a6b4a", "gigabit"],
];

/* An RJ45 seen from the front, contacts up, latch away from you: pin 1 is on
   the left. Drawn at the same scale as the DB9 so the two reference diagrams
   sit at the same visual weight. */
function rj45(highlight, jumpers) {
  const hot = new Set(highlight || []);
  // Geometry derived from the pin field rather than guessed, because it was
  // guessed once: the body was 180 units wide while pins 7 and 8 sat at 220
  // and 248, so the two right-hand contacts were drawn outside the shell.
  const LEFT = 44, PITCH = 24.5, W = 16;
  const X = (pin) => LEFT + (pin - 1) * PITCH;
  const BODY_L = X(1) - W / 2 - 16;          // 20
  const BODY_R = X(8) + W / 2 + 16;          // 239.5
  const TOP = 20, BOT = 92, LATCH = 112;
  const Y = 62;
  const latchL = (BODY_L + BODY_R) / 2 - 42;
  const latchR = (BODY_L + BODY_R) / 2 + 42;
  let out = `<path d="M${BODY_L} ${TOP} H${BODY_R} V${BOT} H${latchR} V${LATCH}
             H${latchL} V${BOT} H${BODY_L} Z" fill="none" stroke="var(--b2)"
             stroke-width="2.5" stroke-linejoin="round"/>`;
  for (const [a, b, colour, bow, striped] of jumpers || []) {
    const [from, to] = a <= b ? [a, b] : [b, a];
    const mid = (X(from) + X(to)) / 2;
    const d = `M${X(from)} ${Y} Q${mid} ${Y + bow} ${X(to)} ${Y}`;
    // A striped wire is drawn as white with the colour banded over it, which
    // is what the conductor actually looks like in the hand.
    out += striped
      ? `<path d="${d}" fill="none" stroke="#f2f2f2" stroke-width="4.5"
           stroke-linecap="round"/>
         <path d="${d}" fill="none" stroke="${colour}" stroke-width="4.5"
           stroke-dasharray="5 5" stroke-linecap="butt"/>`
      : `<path d="${d}" fill="none" stroke="${colour}" stroke-width="4.5"
           stroke-linecap="round"/>`;
  }
  for (const [pin, name, , cb] of RJ45_PINS) {
    const on = hot.has(pin);
    const x = X(pin) - W / 2;
    // Four of the eight conductors are striped, not solid: White/Orange is a
    // white wire with an orange stripe and is a DIFFERENT wire from Orange.
    // Drawing both as solid orange puts a technician on the wrong conductor,
    // which is the same class of mistake as getting the shell wrong on the DB9.
    const striped = name.startsWith("White");
    out += striped
      ? `<rect x="${x.toFixed(1)}" y="30" width="${W}" height="30" rx="2" fill="#f2f2f2"
           fill-opacity="${on ? 1 : .9}"/>
         <path d="M${(x + 1).toFixed(1)} 46 h${W - 2} M${(x + 1).toFixed(1)} 52 h${W - 2}
                  M${(x + 1).toFixed(1)} 40 h${W - 2} M${(x + 1).toFixed(1)} 34 h${W - 2}"
           stroke="${cb}" stroke-width="3" stroke-linecap="butt"/>
         <rect x="${x.toFixed(1)}" y="30" width="${W}" height="30" rx="2" fill="none"
           stroke="${on ? "var(--bad)" : "var(--b2)"}" stroke-width="${on ? 2.6 : 1}"/>`
      : `<rect x="${x.toFixed(1)}" y="30" width="${W}" height="30" rx="2"
           fill="${cb}" fill-opacity="${on ? 1 : .82}"
           stroke="${on ? "var(--bad)" : "var(--b2)"}" stroke-width="${on ? 2.6 : 1}"/>`;
    out += `<text x="${X(pin).toFixed(1)}" y="80" text-anchor="middle"
              font-family="var(--mono)" font-size="13" font-weight="600"
              fill="var(--mu)">${pin}</text>`;
  }
  return `<svg viewBox="0 0 260 124" style="width:100%;max-width:300px">${out}</svg>`;
}

SCREEN.ETHERNET.WIRING = () => wiringScreen({
  loopback: () =>
    card(h2("Loopback plug, gigabit", "1-3, 2-6, 4-7, 5-8") +
      `<div style="display:flex;justify-content:center;margin-top:4px">${
        rj45(null, [[1, 3, "#e08a3c", 44, true], [2, 6, "#3faa62", 74, false],
                    [4, 7, "#4f7fd6", 44, false], [5, 8, "#9a6b4a", 74, true]])}</div>
       <div class="grow"></div>
       <div style="font-size:12.5px;color:var(--mu);line-height:1.45">Seen from the front
         with the contacts facing you and the latch away. Pin 1 is on the left.</div>`,
      "flex-grow:1") +
    card(h2("Building it") +
      `<div style="display:flex;flex-direction:column;gap:7px;margin-bottom:11px">${
        LOOPBACK.map(([a, b, pins, ca, cb]) => `<div style="display:flex;align-items:center;
          gap:9px;height:44px;padding:0 11px;border-radius:9px;background:var(--bg3)">
          ${swatch(ca, a.startsWith("White"))}
          <span style="width:88px;font-size:12.5px">${a}</span>
          <span style="color:var(--mu)">&harr;</span>
          ${swatch(cb, b.startsWith("White"))}
          <span style="width:88px;font-size:12.5px">${b}</span>
          <span class="grow"></span>
          <span class="mono m" style="font-size:13px">${pins}</span></div>`).join("")}</div>
       <div class="grow"></div>
       <div style="font-size:13px;line-height:1.45;color:var(--mu)">
         <p style="margin-bottom:9px"><b style="color:var(--bad)">Never tie a wire to its own
           stripe partner.</b> Blue to White/Blue is a dead short across a pair.</p>
         <p>Better still, run the cable between the two ports and skip the plug. Two real
           ports negotiating is a truer test than one listening to itself.</p></div>`,
      "width:344px;flex-shrink:0"),

  pinout: () =>
    card(h2("RJ45 pinout", "front, contacts up") +
      `<div style="display:flex;justify-content:center;margin-top:4px">${rj45()}</div>
       <div class="grow"></div>
       <div style="font-size:12.5px;color:var(--mu);line-height:1.45">
         <b style="color:var(--good)">Use T568B unless the far end is already A.</b>
         It is what almost every installation uses. Both ends must match, and which one
         was used cannot be measured afterwards, so go by the colours you can see through
         the plug body.</div>`, "width:330px;flex-shrink:0") +
    card(h2("Every pin", "T568B is the common one") +
      `<div class="thead"><span style="width:34px">Pin</span>
        <span style="width:150px">T568B</span><span style="width:150px">T568A</span>
        <span class="grow">Carries</span></div>` +
      `<div style="font-size:12.5px;line-height:1.4;color:var(--mu);margin-bottom:8px">
         <b style="color:var(--tx)">Same standard at both ends is a straight-through
         cable, whichever you pick.</b> A at one end and B at the other makes a
         crossover. Blue and brown never move between the two.</div>` +
      RJ45_PINS.map(([pin, b, a, cb, ca, use]) => `<div class="trow" style="height:38px">
        <span class="mono" style="width:34px;color:var(--mu)">${pin}</span>
        <span style="width:150px;display:flex;align-items:center;gap:8px;font-size:13px">
          ${swatch(cb, b.startsWith("White"))}${b}</span>
        <span style="width:150px;display:flex;align-items:center;gap:8px;font-size:13px;
          color:var(--mu)">${swatch(ca, a.startsWith("White"))}${a}</span>
        <span class="grow mono" style="font-size:12px;color:var(--mu)">${use}</span></div>`).join(""),
      "flex-grow:1"),

  types: () => card(h2("Straight-through against crossover", "and why it barely matters now") +
    `<div style="display:flex;gap:22px;margin-top:2px;flex-grow:1;min-height:0">
       ${rjMap("Straight-through", "Every pin to the same pin. Almost every patch lead.",
               [[1,1],[2,2],[3,3],[4,4],[5,5],[6,6],[7,7],[8,8]])}
       ${rjMap("Crossover", "Transmit meets receive, the way a DB9 null modem does.",
               [[1,3],[2,6],[3,1],[4,7],[5,8],[6,2],[7,5],[8,4]])}
     </div>
     <div style="font-size:13px;color:var(--mu);line-height:1.45;margin-top:10px">
       <b style="color:var(--tx)">Anything gigabit sorts this out itself.</b> Auto MDI-X is
       part of 1000BASE-T rather than an extra, so a crossover lead is only needed for old
       10 and 100 kit that lacks it. A crossover cable is not a faulty cable, and this
       tester will link on one and score it normally.</div>`, "flex-grow:1"),
});

function rjMap(title, sub, pairs) {
  const LEFT = 22, RIGHT = 192, TOP = 16, STEP = 25;
  const y = (pin) => TOP + (pin - 1) * STEP;
  const colour = {}, striped = {};
  RJ45_PINS.forEach(([pin, name, , cb]) => {
    colour[pin] = cb;
    striped[pin] = name.startsWith("White");
  });
  let out = "";
  for (const [a, b] of pairs) {
    const d = `M${LEFT + 14} ${y(a)} C${LEFT + 66} ${y(a)} ${RIGHT - 66} ${y(b)} ${RIGHT - 14} ${y(b)}`;
    // Same rule as the connector drawings: a striped conductor is drawn
    // striped, because White/Orange and Orange are two different wires.
    out += striped[a]
      ? `<path d="${d}" fill="none" stroke="#f2f2f2" stroke-width="2.6"/>
         <path d="${d}" fill="none" stroke="${colour[a]}" stroke-width="2.6"
           stroke-dasharray="4 4"/>`
      : `<path d="${d}" fill="none" stroke="${colour[a]}" stroke-width="2.4" opacity=".9"/>`;
  }
  const node = (cx, pin) => striped[pin]
    ? `<circle cx="${cx}" cy="${y(pin)}" r="3.6" fill="#f2f2f2"/>
       <path d="M${cx - 3.6} ${y(pin)} h7.2" stroke="${colour[pin]}" stroke-width="2.6"/>`
    : `<circle cx="${cx}" cy="${y(pin)}" r="3.4" fill="${colour[pin]}"/>`;
  for (let pin = 1; pin <= 8; pin++) {
    out += node(LEFT + 14, pin) +
      `<text x="${LEFT + 4}" y="${y(pin) + 4}" text-anchor="end" font-family="var(--mono)"
        font-size="11.5" fill="var(--mu)">${pin}</text>` +
      node(RIGHT - 14, pin) +
      `<text x="${RIGHT + 4}" y="${y(pin) + 4}" text-anchor="start" font-family="var(--mono)"
        font-size="11.5" fill="var(--mu)">${pin}</text>`;
  }
  return `<div style="flex:1 1 0;min-width:0;display:flex;flex-direction:column">
    <div style="font-family:var(--disp);font-weight:700;font-size:14px;letter-spacing:.09em;
      text-transform:uppercase">${title}</div>
    <div style="font-size:12px;color:var(--mu);line-height:1.35;margin:3px 0 6px">${sub}</div>
    <svg viewBox="0 0 214 210" style="width:100%;flex-grow:1;min-height:0">${out}</svg>
  </div>`;
}

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
  const pins = (res ? res.affected_pins : []).slice();
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
         bad ? openNow.map(lineName).join(", ")
             : (lines.length
                ? lines.map((l) => `${lineName(l)}: ${byLine[l]}`).join("   ")
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
    // There is always a way onward from here. This screen was a dead end once
    // a run had finished: it offered only "start" and the rail, so the end of
    // the last step of the test had no exit and reading it as finished was
    // left to the technician.
    `<div class="row">${live
      ? btn("btn-mon-stop", "Stop", { kind: "primary", style: "height:64px;flex-grow:1" })
      : (res
          ? btn("btn-goto-TEST", "Done, back to test",
                { kind: "primary", style: "height:64px;flex-grow:1" }) +
            btn("btn-mon-start", "Watch again", { style: "height:64px;width:210px" })
          : btn("btn-mon-start", "Start watching",
                { kind: "primary", style: "height:64px;flex-grow:1",
                  disabled: Boolean(state.running) }) +
            btn("btn-goto-TEST", "Back", { style: "height:64px;width:150px" }))
     }</div>`,
    "flex-grow:1") +
  card((serial
      ? h2("Conductors", state.shell === "male" ? "male shell" : "female shell") +
        `<div style="display:flex;justify-content:center">${
          db9(null, state.shell, pins)}</div>` +
        shellToggle() +
        `<div style="height:11px"></div>`
      : "") +
    h2("Events", state.monEvents.length ? "" : "none yet") +
    (state.monEvents.length
      ? `<div class="log">${state.monEvents.slice(-8).map((e) =>
          `<div>${(e.at_ms / 1000).toFixed(1)}s <b>${lineName(e.line)} ${
            e.line === "Speed" ? `fell to ${e.to || "a lower speed"}Mb` : "open"} ${
            e.duration_ms === null ? "(still)" : Math.round(e.duration_ms) + " ms"}</b></div>`
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
       <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:9px">
         <span style="font-family:var(--sans);font-size:10px;font-weight:600;
           letter-spacing:.12em;text-transform:uppercase;color:var(--mu)">Cable ID, for the report</span>
         <input id="cable-id" type="text" placeholder="e.g. XFC-07" autocomplete="off"
           value="${state.cableId.replace(/"/g, "&quot;")}"
           style="${PICKER_STYLE};font-size:16px">
       </div>
       <div class="row">
         ${btn("btn-json", "Export JSON", { disabled: !canExport })}
         ${btn("btn-print", "Print report", { kind: "primary", disabled: !canExport })}
       </div>` +
       // Only on the kit. On a laptop there is no kiosk to leave, and a
       // button that always fails is worse than no button.
       (window.CT.panelControl
         ? `<div class="row" style="margin-top:9px">
              ${btn("btn-desk", "Exit to desktop", { style: "flex-grow:1" })}
            </div>`
         : "") +
      `
       <div style="font-family:var(--mono);font-size:11.5px;color:var(--mu);margin-top:11px">
         v${window.CT.version}${window.CT.simulating ? "  ·  SIMULATION" : ""}${
           canExport ? "" : "  ·  nothing to export yet"}</div>`,
      "flex-grow:1");
};

SCREEN.SERIAL.SETUP = SETUP;
SCREEN.ETHERNET.SETUP = SETUP;

/* ---------------------------------------------------------------- render */

const STATE_TEXT = {
  TEST: "Ready", PINS: "Pin check", CONTINUITY: "Flex test",
  PAIRS: "Pairs", WIRING: "Reference", SETUP: "Setup",
};

function render() {
  $("under-test").textContent = underTest();
  $("under-test-label").textContent =
    state.proto === "ETHERNET" ? "Testing between" : "Testing on";
  const names = NAV[state.proto] || NAV.SERIAL;
  if (!names.includes(state.screen)) state.screen = "TEST";

  $("nav").innerHTML = names.map((n) =>
    `<button class="navbtn${n === state.screen ? " on" : ""}" data-s="${n}">
       <svg viewBox="0 0 24 24">${ICON[n]}</svg>${NAV_LABEL[n] || n}</button>`).join("");

  document.querySelectorAll("#proto .modebtn").forEach((b) => {
    b.classList.toggle("on", b.dataset.proto === state.proto);
    // Switching protocol mid-run would abandon a test without saying so.
    b.disabled = Boolean(state.running);
  });

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
  on("btn-eth", runEthLadder);
  on("btn-load", runEthLoad);
  on("btn-cancel", cancelRunning);
  on("btn-mon", () => {
    state.screen = "CONTINUITY";
    state.step = "flex";
    setState("Flex test");
    render();
    startContinuity();
  });
  on("btn-mon-start", startContinuity);
  on("btn-mon-stop", cancelRunning);
  on("btn-reset-run", clearResults);

  // Step tiles are the flow's own navigation: tapping one shows its detail
  // without starting anything.
  document.querySelectorAll(".step").forEach((b) => {
    b.onclick = () => { state.step = b.dataset.step; render(); };
  });
  // One handler for every "go to that screen" button, so a new one needs no
  // new wiring: the screen name is in the id.
  document.querySelectorAll('[id^="btn-goto-"]').forEach((b) => {
    const target = b.id.slice("btn-goto-".length);
    b.onclick = () => {
      state.screen = target;
      setState(STATE_TEXT[target] || target);
      render();
    };
  });
  document.querySelectorAll(".tab").forEach((b) => {
    b.onclick = () => { state.tab = b.dataset.tab; render(); };
  });
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
  const pick = (id, key) => {
    const el = $(id);
    if (!el) return;
    el.onchange = () => { state[key] = el.value || null; saveSelection(); render(); };
  };
  pick("port-pick", "port");
  pick("eth-a", "ethA");
  pick("eth-b", "ethB");
  on("btn-refresh", () => { loadPorts(); loadInterfaces(); });
  on("btn-desk", () => confirmThen(
    "Exit to the desktop?",
    "The panel drops to the normal desktop. The tester keeps running and stays "
    + "reachable over the network, but this box has no keyboard, so getting back "
    + "means SSH or a reboot.",
    async () => {
      try {
        await api("/api/panel/desk", { method: "POST" });
      } catch (err) { showAlert(err.message, err.hint); }
    }));
  const cid = $("cable-id");
  if (cid) cid.oninput = () => { state.cableId = cid.value.trim(); };
  document.querySelectorAll("[data-shell]").forEach((b) => {
    b.onclick = () => { state.shell = b.dataset.shell; saveSelection(); render(); };
  });
}

/* ------------------------------------------------------------ run tests */

function exportQuery() {
  const params = new URLSearchParams();
  if (state.lastPinJob) params.set("pincheck", state.lastPinJob);
  if (state.sweepJob) params.set("sweep", state.sweepJob);
  if (state.cableId) params.set("cable_id", state.cableId);
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
  const chosen = state.settings.find((x) => x.id === state.chosen);
  state.runEta = chosen ? chosen.seconds : 0;
  state.runRates = chosen ? chosen.rates : null;
  // How long ONE rate should take, for the per-rate bars. Both parities and
  // every pass go through the same payload, so they all count.
  state.runSecs = chosen
    ? chosen.payload_seconds * chosen.passes * (chosen.parity === "both" ? 2 : 1)
    : 0;
  state.liveBaud = null;
  state.screen = "TEST";
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
        if (d.state === "start") {
          state.liveBaud = d.baud;
          state.rateStart = Date.now();
          setState(`${d.baud} baud`);
          if (state.screen === "TEST") render();
          return;
        }
        const e = state.sweepRates[d.baud] || (state.sweepRates[d.baud] = {});
        e.grade = d.grade;
        render();
      },
      sweep_run: (d) => {
        const e = state.sweepRates[d.baud] || (state.sweepRates[d.baud] = {});
        e[d.parity] = d.run;
        if (d.run && d.run.throughput_bps) state.liveBps = d.run.throughput_bps;
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
  state.ethRungs = []; state.ethScore = null; state.ethOrientation = null;
  state.screen = "TEST";
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
          state.ethOrientation = data.result.orientation || null;
          setLamp(data.result.score.band === "red" ? "bad" : "ok");
        }
        render();
      },
    });
  } catch (err) { setRunning(null); showAlert(err.message, err.hint); }
}

async function runEthLoad() {
  const a = state.ethA, b = state.ethB;
  if (!a || !b) {
    showAlert("Ethernet ports are not set.", "Choose both under Setup.");
    state.screen = "SETUP"; render(); return;
  }
  clearAlert();
  state.loadResult = null; state.loadMbps = 0; state.loadFrames = 0;
  state.screen = "TEST";
  const seconds = 10;
  try {
    setRunning("ethload");
    state.runEta = seconds;
    const { job } = await api("/api/eth/load", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ iface_a: a, iface_b: b, seconds }),
    });
    state.currentJob = job;
    follow(job, "ethload", {
      load_progress: (d) => {
        state.loadMbps = d.mbps;
        state.loadFrames = d.sent;
        if (state.screen === "TEST") render();
      },
      finished: (data) => {
        if (data.result) {
          state.loadResult = data.result;
          setLamp(data.result.passed ? "ok" : "bad");
        }
        render();
      },
    });
  } catch (err) { setRunning(null); showAlert(err.message, err.hint); }
}

/* ---------------------------------------------------------------- setup */

/* One confirm dialog, reused. Anything that a stray touch should not be able
   to do on a sealed instrument goes through here. */
function confirmThen(title, body, action) {
  $("ask-title").textContent = title;
  $("ask-body").textContent = body;
  $("ask-scrim").classList.add("on");
  $("ask-ok").onclick = () => { $("ask-scrim").classList.remove("on"); action(); };
}

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
    // dataset.proto is the test, not "is it a button". A stray button inside
    // this element once made every rail tap set the protocol to undefined,
    // and the failure surfaced as the nav going dead rather than as anything
    // to do with the switch.
    if (!b || !b.dataset.proto) return;
    if (b.dataset.proto === state.proto || state.running) return;
    state.proto = b.dataset.proto;
    // The flow restarts: the steps are different and a step key from the
    // other protocol would select a panel this one does not have.
    state.step = null;
    state.screen = "TEST";
    setState("Ready");
    render();
    if (state.proto === "ETHERNET") loadInterfaces();
  };
  $("ask-cancel").onclick = () => $("ask-scrim").classList.remove("on");
  $("pick-cancel").onclick = () => $("pick-scrim").classList.remove("on");
  $("pick-start").onclick = () => { $("pick-scrim").classList.remove("on"); runSweep(); };
  $("edit-cancel").onclick = () => $("edit-scrim").classList.remove("on");
  $("edit-save").onclick = saveEditor;
  for (const id of ["pick-scrim", "edit-scrim", "ask-scrim"]) {
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
