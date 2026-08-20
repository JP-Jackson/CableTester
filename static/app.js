/* RS-232 Cable Tester: front end.
   Talks to the Flask backend over JSON and Server-Sent Events. No build step.
   Chrome and tokens follow the Polk portal design system, see
   branding/brand-guide.md. */
"use strict";

const $ = (id) => document.getElementById(id);
const GAUGE_R = 140;
const ARC = Math.PI * GAUGE_R;         // length of the semicircular track
const PARITY_ORDER = { none: 0, even: 1 };
const RESULT_LABEL = { nc: "n/c", reference: "ref" };
const DASH = "-";   // never an em dash, see CLAUDE.md

const state = {
  ports: [],
  pinJob: null,        // id of the last PASSING pin check on the selected port
  lastPinJob: null,    // id of the last pin check, passing or not
  sweepJob: null,
  currentJob: null,
  stream: null,
  running: null,
  sweep: {},           // baud -> { runs: {}, grade }
};

/* ------------------------------------------------------------------ utils */
function setLamp(cls) {
  $("lamp").className = "lamp" + (cls ? " " + cls : "");
}

// The header's state block: an uppercase eyebrow over the live line, the
// same shape the Polk portal uses for its greeting.
function setStatus(text, label) {
  $("status").textContent = text;
  if (label !== undefined) $("status-label").textContent = label;
}

function showAlert(message, hint, kind) {
  const box = $("alert");
  box.className = "alert" + (kind === "info" ? " info" : "");
  box.innerHTML = "";
  box.appendChild(document.createTextNode(message));
  if (hint) {
    const span = document.createElement("span");
    span.className = "hint";
    span.textContent = hint;
    box.appendChild(span);
  }
  box.hidden = false;
}

function clearAlert() { $("alert").hidden = true; }

function fmt(n, digits) {
  if (n === null || n === undefined) return DASH;
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits || 0,
    maximumFractionDigits: digits === undefined ? 0 : digits,
  });
}

function fmtBps(bps) {
  if (!bps) return DASH;
  return bps >= 1000 ? (bps / 1000).toFixed(1) + " kbps" : Math.round(bps) + " bps";
}

/* JP's standard display format: Monday, 8/17/2026 8:25 PM. Built by hand
   because no toLocaleString option set gives a long weekday with a numeric
   date and no comma before the time. 'en-US' is passed explicitly, never
   undefined, so the same stamp does not render 17/08/2026 for anyone whose
   machine is not set to US English. See CLAUDE.md. */
function fmtWhen(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { weekday: "long" }) + ", " +
    (d.getMonth() + 1) + "/" + d.getDate() + "/" + d.getFullYear() + " " +
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function fmtBer(ber) {
  if (!ber) return "0";
  return ber.toExponential(1);
}

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

/* ------------------------------------------------------------------ gauge */
function initGauge() {
  const bands = [
    [".g-red", 0, 0.6],
    [".g-amber", 0.6, 0.85],
    [".g-green", 0.85, 1],
  ];
  for (const [selector, from, to] of bands) {
    const el = document.querySelector(selector);
    el.setAttribute("stroke-dasharray", `${(to - from) * ARC} ${ARC}`);
    el.setAttribute("stroke-dashoffset", `${-from * ARC}`);
  }
  setGauge(null, null, null);
}

function setGauge(score, band, verdict) {
  const value = $("g-value");
  const num = $("g-num");
  const fraction = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  value.setAttribute("stroke-dasharray", `${fraction * ARC} ${ARC}`);
  // a zero-length dash with a round cap would still paint a dot at 0
  value.style.display = fraction > 0 ? "" : "none";
  value.setAttribute("class", "g-value" + (band ? " " + band : ""));
  num.setAttribute("class", "g-num" + (band ? " " + band : ""));
  // no score yet: leave the dial blank rather than painting a placeholder glyph
  num.textContent = score === null ? "" : Math.round(score) + "%";
  if (verdict !== null && verdict !== undefined) {
    $("verdict").textContent = verdict;
    $("verdict").className = "verdict" + (band ? " " + band : "");
  }
  setLamp(band === "green" ? "ok" : band === "red" ? "bad" : band ? "busy" : "");
}

/* ------------------------------------------------------------------ theme */
/* The Polk portal follows the device's light/dark setting and defaults to
   light. This one defaults to DARK and does not track the device, because
   it runs full screen on a shop bench, often in a dim building, and a
   kiosk that boots to a white screen is the wrong instrument. An explicit
   choice is still remembered, and the toggle works both ways. */
function applyTheme(dark, persist) {
  const icon = $("theme-icon");
  document.documentElement.classList.toggle("dark", dark);
  if (icon) icon.className = "ti " + (dark ? "ti-moon" : "ti-sun");
  if (persist) localStorage.setItem("cabletester-theme", dark ? "dark" : "light");
}

function initTheme() {
  const saved = localStorage.getItem("cabletester-theme");
  applyTheme(saved ? saved === "dark" : true, false);
  const btn = $("theme-toggle");
  if (btn) {
    btn.onclick = () =>
      applyTheme(!document.documentElement.classList.contains("dark"), true);
  }
}

/* Tabler icons load from a CDN, and this box may sit on a shop network with
   no route to the internet. Mark the document when the icon font is not
   there so style.css can swap in plain unicode instead of empty squares.

   document.fonts.check() is NOT usable for this: per spec it answers "can
   this text be rendered", and an unknown family falls back to a system font,
   so it returns true even when the stylesheet never loaded. Look for the
   FontFace itself instead. */
function checkIcons() {
  const mark = () => document.documentElement.classList.add("no-icons");
  if (!document.fonts || !document.fonts.ready) { mark(); return; }
  document.fonts.ready.then(function () {
    let available = false;
    document.fonts.forEach(function (face) {
      if (/tabler/i.test(face.family) && face.status !== "error") available = true;
    });
    if (!available) mark();
  });
}

/* ------------------------------------------------------------------ ports */
async function loadPorts() {
  const select = $("port");
  const previous = select.value;
  try {
    const data = await api("/api/ports");
    state.ports = data.ports;
    select.innerHTML = "";
    if (!data.ports.length) {
      select.innerHTML = '<option value="">No serial ports found</option>';
      setStatus("No ports", "Status");
      return;
    }
    for (const port of data.ports) {
      const option = document.createElement("option");
      option.value = port.device;
      const id = port.vid_pid ? `  [${port.vid_pid}]` : "";
      option.textContent = `${port.device} \u00b7 ${port.description}${id}`;
      select.appendChild(option);
    }
    if (previous && data.ports.some((p) => p.device === previous)) select.value = previous;
    renderPortDetail();
    setStatus(`${data.ports.length} port(s) found`, "Status");
  } catch (err) {
    showAlert("Could not list serial ports.", err.message);
  }
}

function selectedPort() {
  return $("port").value;
}

function renderPortDetail() {
  const port = state.ports.find((p) => p.device === selectedPort());
  if (!port) { $("port-detail").textContent = "No port selected."; return; }
  $("port-detail").textContent = [
    `device       ${port.device}`,
    `description  ${port.description}`,
    `manufacturer ${port.manufacturer || DASH}`,
    `product      ${port.product || DASH}`,
    `serial       ${port.serial_number || DASH}`,
    `VID:PID      ${port.vid_pid || DASH}`,
    `hwid         ${port.hwid || DASH}`,
  ].join("\n");
}

/* ------------------------------------------------------ pin check render */
function renderPins(result) {
  const body = $("pin-rows");
  body.innerHTML = "";
  for (const pin of result.pins) {
    const row = document.createElement("tr");
    row.innerHTML =
      `<td class="mono">${pin.pin}</td>` +
      `<td class="mono">${pin.signal}</td>` +
      `<td class="res res-${pin.result}">${RESULT_LABEL[pin.result] || pin.result}</td>` +
      `<td class="detail"></td>`;
    row.lastChild.textContent = pin.detail;
    body.appendChild(row);

    // The diagram draws the connector twice, male and female, so every pin
    // number appears in two places. Both get the result.
    const cls = "pin " + (pin.result === "reference" ? "" : pin.result);
    document.querySelectorAll(`[data-pin="${pin.pin}"]`)
      .forEach((glyph) => glyph.setAttribute("class", cls));
  }

  const topo = result.topology;
  $("topo-name").textContent = topo.label;
  $("topo-name").className = "topo-name" + (topo.kind === "unknown" ? " unknown" : "");
  let note = "";
  if (topo.kind === "learned") note = "Matched a saved known-good profile.";
  else if (topo.kind === "ambiguous") note = "Matches more than one reference: " +
    topo.matches.map((m) => m.note).join(" ");
  else if (topo.kind === "match") note = topo.matches[0].note;
  else note = "This wiring matches no known reference. The observed map is shown below.";
  $("topo-note").textContent = note;
  $("topo-map").textContent = result.signature_text.join("\n");

  const badge = $("pin-badge");
  badge.textContent = result.passed ? "pass" : "fault";
  badge.className = "badge " + (result.passed ? "pass" : "fail");

  const matrix = $("matrix-rows");
  matrix.innerHTML = "";
  for (const output of ["DTR", "RTS"]) {
    const row = document.createElement("tr");
    const cells = ["CTS", "DSR", "DCD", "RI"].map((input) => {
      const hit = result.matrix[output][input];
      return `<td class="mono ${hit ? "hit" : "miss"}">${hit ? "responded" : DASH}</td>`;
    });
    row.innerHTML = `<td class="mono">${output}</td>` + cells.join("");
    matrix.appendChild(row);
  }
  const data = result.data_loopback;
  const dataRow = document.createElement("tr");
  dataRow.innerHTML =
    `<td class="mono">TXD data</td>` +
    `<td class="mono ${data.ok ? "res-pass" : "res-short"}" colspan="4">` +
    `sent ${data.sent} / got ${data.received || "(nothing)"}</td>`;
  matrix.appendChild(dataRow);
}

/* ---------------------------------------------------------- sweep render */
function resetSweepRows() {
  state.sweep = {};
  document.querySelectorAll("tr.rate").forEach((row) => {
    row.className = "rate idle";
    row.querySelector(".progress i").style.width = "0%";
    ["col-bytes", "col-errors", "col-timeouts", "col-tput", "col-parity", "col-result"]
      .forEach((cls) => { row.querySelector("." + cls).textContent = DASH; });
  });
  $("detail-rows").innerHTML = '<tr class="empty"><td colspan="13">No sweep data.</td></tr>';
}

function onSweepProgress(data) {
  const row = $("rate-" + data.baud);
  if (!row) return;
  row.classList.remove("idle");
  row.classList.add("active");
  const half = PARITY_ORDER[data.parity] || 0;
  const overall = (half + data.fraction) / 2;
  row.querySelector(".progress i").style.width = (overall * 100).toFixed(1) + "%";
  row.querySelector(".col-bytes").textContent = `${fmt(data.received)}/${fmt(data.total)}`;
  row.querySelector(".col-parity").textContent = data.parity;
}

function onSweepRun(data) {
  const row = $("rate-" + data.baud);
  if (!row) return;
  const run = data.run;
  const store = state.sweep[data.baud] || (state.sweep[data.baud] = { runs: {} });
  store.runs[data.parity] = run;

  const errors = Object.values(store.runs)
    .reduce((sum, r) => sum + r.mismatched + r.missing, 0);
  const timeouts = Object.values(store.runs).reduce((sum, r) => sum + r.timeouts, 0);
  row.querySelector(".col-bytes").textContent =
    `${fmt(run.received)}/${fmt(run.total)}`;
  row.querySelector(".col-errors").textContent = fmt(errors);
  row.querySelector(".col-timeouts").textContent = fmt(timeouts);
  row.querySelector(".col-tput").textContent = fmtBps(run.throughput_bps);
  row.querySelector(".col-parity").textContent = data.parity;
  const half = PARITY_ORDER[data.parity] || 0;
  row.querySelector(".progress i").style.width = ((half + 1) / 2 * 100) + "%";
}

function onSweepRate(data) {
  const row = $("rate-" + data.baud);
  if (!row) return;
  if (data.state === "start") {
    row.className = "rate active";
    row.querySelector(".col-result").textContent = "running";
    return;
  }
  const grade = data.grade;
  state.sweep[data.baud] = Object.assign(state.sweep[data.baud] || {}, {
    entry: data.entry, grade: grade,
  });
  row.className = "rate " + (grade ? grade.status : "");
  row.querySelector(".progress i").style.width = "100%";
  row.querySelector(".col-result").textContent = grade
    ? { pass: "pass", marginal: "marginal", fail: "FAIL" }[grade.status]
    : DASH;
  row.querySelector(".col-parity").textContent = grade
    ? `${grade.none}/${grade.even}` : DASH;
}

function renderDetails(sweepResult) {
  const body = $("detail-rows");
  body.innerHTML = "";
  const grades = {};
  (sweepResult.score ? sweepResult.score.per_rate : []).forEach((g) => { grades[g.baud] = g; });

  for (const entry of sweepResult.rates) {
    const grade = grades[entry.baud] || {};
    for (const parity of ["none", "even"]) {
      const run = entry.runs[parity];
      if (!run) continue;
      const row = document.createElement("tr");
      row.innerHTML = [
        entry.baud, parity, fmt(run.sent), fmt(run.received), fmt(run.mismatched),
        fmt(run.missing), fmt(run.timeouts), fmtBer(run.ber), run.elapsed_s + " s",
        fmtBps(run.throughput_bps), run.efficiency_pct + "%",
        parity === "none" ? (grade.weight || "") : "",
        parity === "none" ? (grade.credit !== undefined ? grade.credit.toFixed(2) : "") : "",
      ].map((cell) => `<td class="mono">${cell}</td>`).join("");
      if (run.error) {
        row.querySelector("td:nth-child(2)").classList.add("res-short");
        row.title = run.error;
      }
      body.appendChild(row);
    }
  }
  if (!body.children.length) {
    body.innerHTML = '<tr class="empty"><td colspan="13">No sweep data.</td></tr>';
  }
}

/* ------------------------------------------------------------- job stream */
function closeStream() {
  if (state.stream) { state.stream.close(); state.stream = null; }
}

function setRunning(kind) {
  state.running = kind;
  const busy = Boolean(kind);
  $("btn-pincheck").disabled = busy;
  $("btn-cancel").disabled = !busy;
  $("btn-learn").disabled = busy || !state.pinJob;
  $("btn-sweep").disabled = busy || !state.pinJob;
  $("refresh").disabled = busy;
  setLamp(busy ? "busy" : null);
}

function follow(jobId, kind, handlers) {
  closeStream();
  state.currentJob = jobId;
  const source = new EventSource(`/api/events/${jobId}`);
  state.stream = source;
  for (const [name, handler] of Object.entries(handlers)) {
    source.addEventListener(name, (event) => handler(JSON.parse(event.data)));
  }
  source.addEventListener("job_end", (event) => {
    const data = JSON.parse(event.data);
    closeStream();
    setRunning(null);
    if (data.state === "error") {
      showAlert(data.error.message, data.error.hint);
      setLamp("bad");
      setStatus("Error", "Status");
    } else if (data.state === "cancelled") {
      showAlert("Test cancelled.", "", "info");
      setStatus("Cancelled", "Status");
    } else {
      setStatus("Done", "Status");
    }
    if (handlers.finished) handlers.finished(data);
  });
  source.onerror = () => {
    // The stream ends when the job ends; only surface a real mid-run drop.
    if (state.running === kind && source.readyState === EventSource.CLOSED) {
      closeStream();
      setRunning(null);
      showAlert("Lost the event stream.", "The test may still be running. Reload the page.");
    }
  };
}

/* ------------------------------------------------------------- run tests */
async function runPinCheck() {
  const port = selectedPort();
  if (!port) { showAlert("Select a port first."); return; }
  clearAlert();
  state.pinJob = null;
  state.sweepJob = null;
  resetSweepRows();
  setGauge(null, null, "Pin check running.");
  $("verdict-sub").textContent = `Driving DTR and RTS on ${port}.`;
  $("sweep-badge").textContent = "locked";
  $("sweep-badge").className = "badge";
  document.querySelectorAll(".pin").forEach((p) => p.setAttribute("class", "pin"));

  try {
    setRunning("pincheck");
    setStatus("Starting", "Pin check");
    const { job } = await api("/api/pincheck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: port }),
    });
    follow(job, "pincheck", {
      pin_step: (data) => setStatus(
        data.state === "asserting" ? `Asserting ${data.output}` : `${data.output} read back`,
        "Pin check"
      ),
      pincheck_result: (result) => {
        renderPins(result);
        state.pinJob = result.passed ? job : null;
        state.lastPinJob = job;
        $("btn-json").disabled = false;
        $("btn-print").disabled = false;
        if (result.passed) {
          $("verdict").textContent = "Pin check passed. Run the baud sweep for a health score.";
          $("verdict").className = "verdict";
          $("sweep-badge").textContent = "ready";
          $("verdict-sub").textContent = result.summary;
        } else {
          setGauge(0, "red", "Pin check failed. The cable has a wiring fault.");
          $("verdict-sub").textContent = result.summary;
        }
      },
      finished: () => {
        $("btn-sweep").disabled = !state.pinJob;
        $("btn-learn").disabled = !state.lastPinJob;
      },
    });
  } catch (err) {
    setRunning(null);
    showAlert(err.message, err.hint);
  }
}

async function runSweep() {
  const port = selectedPort();
  if (!state.pinJob) { showAlert("Run a passing pin check first."); return; }
  clearAlert();
  resetSweepRows();
  setGauge(null, null, "Baud sweep running.");
  $("verdict-sub").textContent = "Each rate is run twice: no parity, then even parity.";
  $("sweep-badge").textContent = "running";
  $("sweep-badge").className = "badge busy";

  try {
    setRunning("sweep");
    const { job } = await api("/api/sweep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        port: port,
        pincheck: state.pinJob,
        payload_seconds: parseFloat($("payload-seconds").value) || 2,
      }),
    });
    state.sweepJob = job;
    follow(job, "sweep", {
      sweep_rate: (data) => {
        onSweepRate(data);
        if (data.state === "start") setStatus(`${data.baud} baud`, "Baud sweep");
      },
      sweep_run: onSweepRun,
      sweep_progress: onSweepProgress,
      score: (score) => setGauge(score.score, score.band, score.verdict),
      finished: (data) => {
        const badge = $("sweep-badge");
        if (data.result) {
          renderDetails(data.result);
          const score = data.result.score;
          setGauge(score.score, score.band, score.verdict);
          badge.textContent = data.result.cancelled ? "partial" : "complete";
          badge.className = "badge " + (score.band === "green" ? "pass"
            : score.band === "red" ? "fail" : "busy");
          $("verdict-sub").textContent =
            `Scored across ${score.per_rate.length} rate(s), ${score.coverage}% of the ` +
            `weighted range. Higher rates count for more.`;
        } else {
          badge.textContent = "stopped";
          badge.className = "badge fail";
        }
      },
    });
  } catch (err) {
    setRunning(null);
    showAlert(err.message, err.hint);
  }
}

/* -------------------------------------------------------------- profiles */
async function loadProfiles() {
  try {
    const data = await api("/api/profiles");
    const box = $("profile-list");
    box.innerHTML = "";
    if (!data.learned.length) { box.textContent = "none saved"; return; }
    for (const profile of data.learned) {
      const row = document.createElement("div");
      row.className = "profile-row";
      const label = document.createElement("span");
      label.className = "grow";
      label.innerHTML = "<b></b><br>";
      label.querySelector("b").textContent = profile.name;
      label.appendChild(document.createTextNode(
        `DTR to ${(profile.signature.DTR || []).join("/") || DASH}   ` +
        `RTS to ${(profile.signature.RTS || []).join("/") || DASH}   ` +
        `data ${profile.signature.data ? "ok" : "open"}   ` +
        `learned ${fmtWhen(profile.learned_at) || "at an unknown time"}`
      ));
      const del = document.createElement("button");
      del.className = "del";
      del.textContent = "×";
      del.title = "Delete this profile";
      del.onclick = async () => {
        await api(`/api/profiles/${profile.id}`, { method: "DELETE" });
        loadProfiles();
      };
      row.append(label, del);
      box.appendChild(row);
    }
  } catch (err) {
    $("profile-list").textContent = "could not load profiles: " + err.message;
  }
}

async function learnProfile() {
  const jobId = state.lastPinJob;
  if (!jobId) { showAlert("Run a pin check on the known-good cable first."); return; }
  const name = window.prompt(
    "Name this known-good cable profile:", $("cable-id").value || "Known-good cable"
  );
  if (!name) return;
  try {
    await api("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: jobId, name: name }),
    });
    await loadProfiles();
    showAlert(`Saved profile "${name}". Later cables are compared against it first.`, "", "info");
  } catch (err) {
    showAlert(err.message, err.hint);
  }
}

/* ---------------------------------------------------------------- export */
function exportQuery() {
  const params = new URLSearchParams();
  if (state.lastPinJob) params.set("pincheck", state.lastPinJob);
  if (state.sweepJob) params.set("sweep", state.sweepJob);
  params.set("cable_id", $("cable-id").value.trim());
  return params.toString();
}

/* ------------------------------------------------------------------ wire */
function init() {
  initTheme();
  checkIcons();
  initGauge();
  loadPorts();
  loadProfiles();

  $("refresh").onclick = loadPorts;
  $("port").onchange = () => {
    state.pinJob = null;
    state.lastPinJob = null;
    state.sweepJob = null;
    $("btn-sweep").disabled = true;
    $("btn-learn").disabled = true;
    renderPortDetail();
  };
  $("btn-pincheck").onclick = runPinCheck;
  $("btn-sweep").onclick = runSweep;
  $("btn-learn").onclick = learnProfile;
  $("btn-cancel").onclick = async () => {
    const jobId = state.currentJob;
    if (jobId) await api(`/api/cancel/${jobId}`, { method: "POST" }).catch(() => {});
  };
  $("btn-details").onclick = () => {
    const panel = $("details");
    panel.hidden = !panel.hidden;
    $("btn-details").setAttribute("aria-expanded", String(!panel.hidden));
    $("btn-details").textContent = panel.hidden ? "Show details" : "Hide details";
  };
  $("btn-json").onclick = () => { window.location = "/api/export.json?" + exportQuery(); };
  $("btn-print").onclick = () => { window.open("/report?" + exportQuery(), "_blank"); };

  window.addEventListener("beforeunload", closeStream);
}

document.addEventListener("DOMContentLoaded", init);
