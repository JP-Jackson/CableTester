"""Flask app: routes, job runner, and the Server-Sent Events stream.

One serial port, one test at a time. This is a bench instrument, not a service.
Tests run on a worker thread; the browser follows along over SSE. Because the
worker owns the port, closing the browser mid-test can never leave it locked.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from . import (
    __version__,
    continuity,
    ethernet_tests,
    history,
    scoring,
    serial_tests,
    sweep_settings,
)

HEARTBEAT_S = 15.0

#: The kit's panel switch. Absent when the tester runs anywhere but the kit,
#: which is why every use of it is guarded rather than assumed.
PANEL_TOOL = "cabletester-mode"


def panel_control_available() -> bool:
    return shutil.which(PANEL_TOOL) is not None


def fmt_when(when=None):
    """Format a timestamp the way JP wants it shown: Monday, 8/17/2026 8:25 PM.

    Long weekday, comma, numeric M/D/YYYY, then 12-hour time with AM/PM. Built
    by hand because no strftime or locale option set produces a long weekday
    with a numeric date and no comma before the time. Display only: stored
    timestamps stay ISO so they sort and parse.
    """
    when = when or datetime.datetime.now()
    hour = when.hour % 12 or 12
    return (
        f"{when.strftime('%A')}, {when.month}/{when.day}/{when.year} "
        f"{hour}:{when.strftime('%M %p')}"
    )


def fmt_date(when):
    """Date with no time: Monday, 8/17/2026.

    A companion to fmt_when rather than a flag on it, deliberately. fmt_when is
    pinned to fmtWhen() in static/app.js and the two have to stay in step, so
    it does not gain parameters for cases the JS side does not have. Nothing in
    the browser formats a bare date: the server hands over the finished string.

    Accepts an ISO date string or a date/datetime.
    """
    if isinstance(when, str):
        when = datetime.datetime.strptime(when[:10], "%Y-%m-%d")
    return f"{when.strftime('%A')}, {when.month}/{when.day}/{when.year}"


class Job:
    """One running (or finished) test, with a replayable event log."""

    def __init__(self, kind: str, port: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.port = port
        self.state = "running"
        self.error: Optional[dict] = None
        self.result: Optional[dict] = None
        self.events: List[dict] = []
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.subscribers: List[queue.Queue] = []
        self.started = time.time()

    def emit(self, event_type: str, payload: dict) -> None:
        event = {"event": event_type, "data": payload, "job": self.id}
        with self.lock:
            # Bulk progress events are not replayed: a late subscriber only
            # needs the latest state, not every tick of a finished run.
            if event_type != "sweep_progress":
                self.events.append(event)
            subscribers = list(self.subscribers)
        for sub in subscribers:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        sub: queue.Queue = queue.Queue(maxsize=1000)
        with self.lock:
            backlog = list(self.events)
            self.subscribers.append(sub)
        for event in backlog:
            sub.put_nowait(event)
        return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self.lock:
            if sub in self.subscribers:
                self.subscribers.remove(sub)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "port": self.port,
            "state": self.state,
            "error": self.error,
            "result": self.result,
        }


class JobManager:
    """Keeps the single active test and a bounded history of finished ones."""

    MAX_HISTORY = 40

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: Dict[str, Job] = {}
        self.active: Optional[Job] = None

    def get(self, job_id: str) -> Optional[Job]:
        with self.lock:
            return self.jobs.get(job_id)

    def start(self, kind: str, port: str, target) -> Job:
        with self.lock:
            if self.active is not None and self.active.state == "running":
                raise RuntimeError(
                    f"A {self.active.kind} test is already running on "
                    f"{self.active.port}. Wait for it to finish or cancel it."
                )
            job = Job(kind, port)
            self.jobs[job.id] = job
            self.active = job
            self._prune()

        def runner():
            try:
                job.result = target(job)
                # Stopping a continuity monitor is how that test FINISHES, not
                # how it is abandoned: it runs until the technician has done
                # working the cable, and only they know when. Marking it
                # cancelled would put "Test cancelled" over a result that is
                # complete and may well have condemned the cable.
                stopped_is_done = job.kind == "continuity"
                job.state = ("done" if stopped_is_done or not job.cancel.is_set()
                             else "cancelled")
            except serial_tests.TestCancelled:
                job.state = "cancelled"
            except serial_tests.CableTesterError as exc:
                job.state = "error"
                job.error = {"message": str(exc), "hint": getattr(exc, "hint", "")}
            except Exception as exc:  # pragma: no cover - unexpected driver faults
                job.state = "error"
                job.error = {
                    "message": f"Unexpected error: {exc.__class__.__name__}: {exc}",
                    "hint": "Check the server console for the full traceback.",
                }
                import traceback

                traceback.print_exc()
            finally:
                job.emit(
                    "job_end",
                    {"state": job.state, "error": job.error, "result": job.result},
                )

        job.thread = threading.Thread(target=runner, name=f"job-{job.id}", daemon=True)
        job.thread.start()
        return job

    def _prune(self) -> None:
        if len(self.jobs) <= self.MAX_HISTORY:
            return
        finished = sorted(
            (j for j in self.jobs.values() if j.state != "running"),
            key=lambda j: j.started,
        )
        for job in finished[: len(self.jobs) - self.MAX_HISTORY]:
            self.jobs.pop(job.id, None)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config["JSON_SORT_KEYS"] = False
    # Serve static files with no cache lifetime. This box updates by git pull,
    # and a browser holding a cached style.css after an update shows a broken
    # or stale screen that looks like a bug in the tester. Revalidating every
    # asset costs nothing over localhost.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    jobs = JobManager()

    # ---------------------------------------------------------------- pages
    def _version_context():
        return {
            "version": history.current_version(),
            "versions": [
                dict(v, released_display=fmt_date(v["released"]))
                for v in history.VERSIONS
            ],
        }

    def _index_context() -> dict:
        """Everything index.html needs, in ONE place.

        Two routes render this template and they used to build the context
        separately, with a comment on the second saying it had to match. It
        did not survive the next variable being added: the 404 handler was
        left without it, Jinja handed the template an Undefined, tojson threw,
        and every 404 became a 500. Chromium asks for /favicon.ico on every
        page load, so that was every page load.

        A comment cannot keep two argument lists in step. A function can.
        """
        return dict(
            baud_rates=serial_tests.BAUD_RATES,
            weights=scoring.BAUD_WEIGHTS,
            simulating=serial_tests.simulation_active(),
            panel_control=panel_control_available(),
            **_version_context(),
        )

    @app.route("/")
    def index():
        return render_template("index.html", **_index_context())

    @app.post("/api/panel/desk")
    def api_panel_desk():
        """Drop the panel to the desktop, from the panel itself.

        The kiosk is the only way in on a sealed box: there is no keyboard and
        no window furniture, so without this the only exit is SSH from another
        machine. The server keeps running either way, which is why this is safe
        to offer at all: dropping to the desktop does not stop a sweep and does
        not make the instrument unreachable.
        """
        if not panel_control_available():
            return _error(
                "This box has no panel control installed.",
                hint="cabletester-mode is not on PATH, so there is no kiosk to "
                     "drop out of. This is normal when the tester is run from a "
                     "laptop.",
            )
        try:
            done = subprocess.run(
                [PANEL_TOOL, "desk"],
                capture_output=True, text=True, timeout=20, check=False,
                # A system service has no session bus of its own, and
                # 'systemctl --user' needs to know which user's manager to talk
                # to. Without this the call fails with "Failed to connect to
                # bus", which reads like the tool being broken rather than
                # being called from the wrong context.
                env=dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}"),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _error(f"Could not switch the panel: {exc}")
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip().splitlines()
            return _error(
                "The panel did not switch to the desktop.",
                hint=detail[-1] if detail
                     else f"cabletester-mode exited {done.returncode}.",
            )
        return jsonify({"mode": "desk"})

    @app.get("/api/history")
    def api_history():
        """Version history, for the screen behind the version in the nav rail."""
        return jsonify(dict(_version_context(), current=history.current_version()))

    # ----------------------------------------------------------------- api
    @app.get("/api/ports")
    def api_ports():
        return jsonify({"ports": serial_tests.list_serial_ports()})

    @app.post("/api/pincheck")
    def api_pincheck():
        body = request.get_json(silent=True) or {}
        port = body.get("port")
        if not port:
            return _error("Select a port first.")

        def target(job: Job):
            # No learned profiles any more: topology is identified against the
            # built-in references alone. The learn-and-save layer was removed
            # because its only interaction was typing a name into a prompt, and
            # this instrument now lives on a keyboardless panel. See DOC 12.
            return serial_tests.run_pin_check(port, emit=job.emit, cancel=job.cancel)

        try:
            job = jobs.start("pincheck", port, target)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        return jsonify({"job": job.id})

    @app.get("/api/sweep-settings")
    def api_sweep_settings():
        return jsonify({
            "settings": sweep_settings.load(),
            "patterns": sweep_settings.PATTERNS,
            "parities": sorted(sweep_settings.PARITIES),
            "rates": serial_tests.BAUD_RATES,
        })

    @app.put("/api/sweep-settings/<setting_id>")
    def api_save_sweep_setting(setting_id):
        try:
            saved = sweep_settings.save(setting_id, request.get_json(silent=True) or {})
        except ValueError as exc:
            return _error(str(exc))
        except OSError as exc:
            # hint=, not positional. The second parameter is the HTTP status,
            # so passing the message here made Flask return the exception text
            # as the status code. Same slip as the panel endpoint below.
            return _error("Could not save the setting.", hint=str(exc))
        return jsonify({"setting": saved, "settings": sweep_settings.load()})

    @app.post("/api/sweep-settings/reset")
    def api_reset_sweep_settings():
        return jsonify({"settings": sweep_settings.reset()})

    @app.post("/api/sweep")
    def api_sweep():
        body = request.get_json(silent=True) or {}
        port = body.get("port")
        pin_job = jobs.get(body.get("pincheck") or "")
        if not port:
            return _error("Select a port first.")
        # Server-side gate: the sweep is only meaningful once the pins check out.
        if pin_job is None or pin_job.kind != "pincheck" or not pin_job.result:
            return _error("Run the pin check before sweeping.")
        if not pin_job.result.get("passed"):
            return _error("The pin check failed. Fix the cable before sweeping.")
        if pin_job.result.get("port") != port:
            return _error("The pin check was run on a different port. Re-run it.")

        setting = sweep_settings.get(body.get("setting") or "standard")
        if setting is None:
            return _error("No such sweep setting.")

        def target(job: Job):
            def emit(event_type: str, payload: dict) -> None:
                # Grade each rate as it completes so the live rows can colour
                # themselves without the browser re-implementing scoring.py.
                if event_type == "sweep_rate" and payload.get("state") == "done":
                    graded = scoring.score_sweep([payload["entry"]])["per_rate"]
                    payload = dict(payload, grade=graded[0] if graded else None)
                job.emit(event_type, payload)

            result = serial_tests.run_baud_sweep(
                port,
                emit=emit,
                cancel=job.cancel,
                payload_seconds=setting["payload_seconds"],
                rates=setting["rates"],
                parities=sweep_settings.PARITIES[setting["parity"]],
                passes=setting["passes"],
                pattern=setting["pattern"],
            )
            result["setting"] = setting
            result["score"] = scoring.score_sweep(result["rates"])
            job.emit("score", result["score"])
            return result

        try:
            job = jobs.start("sweep", port, target)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        return jsonify({"job": job.id})

    # ------------------------------------------------------------- ethernet

    @app.get("/api/eth/interfaces")
    def api_eth_interfaces():
        """Interfaces a cable could be tested between.

        Anything carrying the default route comes back marked untestable rather
        than hidden, so the UI can explain why it is greyed out instead of
        leaving a technician wondering where their port went.
        """
        return jsonify({
            "interfaces": ethernet_tests.list_interfaces(),
            # The read path works without ethtool; running a ladder does not.
            # Reported so the screen can say why the button is disabled instead
            # of failing when someone presses it.
            "can_test": ethernet_tests.ethtool_available(),
            "note": "" if ethernet_tests.ethtool_available() else
                    "ethtool is not installed, so no ethernet test can run. "
                    "Run deploy/setup-pi.sh.",
        })

    @app.post("/api/eth/ladder")
    def api_eth_ladder():
        body = request.get_json(silent=True) or {}
        a = (body.get("iface_a") or "").strip()
        b = (body.get("iface_b") or "").strip()
        if not a or not b:
            return _error("Pick both ports. The cable needs two ends.")

        # Validated before a job is started, so a bad request comes back as a
        # message on screen rather than as a job that fails a second later.
        try:
            ethernet_tests._validate(a)
            ethernet_tests._validate(b)
            if a == b:
                raise ethernet_tests.EthernetTestError(
                    "Pick two different ports. The cable needs two ends.")
            for iface in (a, b):
                if ethernet_tests.carries_default_route(iface):
                    raise ethernet_tests.EthernetTestError(
                        f"'{iface}' carries this box's default route. Testing it "
                        f"would drop the network part way through.")
        except ethernet_tests.EthernetTestError as exc:
            return _error(str(exc))

        def target(job: Job):
            def emit(kind: str, payload: dict) -> None:
                job.emit("eth_" + kind, payload)

            result = ethernet_tests.run_speed_ladder(
                a, b, on_event=emit, cancelled=job.cancel.is_set
            )
            result["score"] = scoring.score_link_ladder(result["rungs"])
            job.emit("score", result["score"])
            return result

        try:
            job = jobs.start("eth_ladder", f"{a} to {b}", target)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        return jsonify({"job": job.id})

    # ----------------------------------------------------------- continuity

    @app.post("/api/continuity")
    def api_continuity():
        """Start a monitor that runs until the technician stops it.

        Unlike every other test here there is no duration. The test is over
        when they have finished working the cable, and only they know when.
        """
        body = request.get_json(silent=True) or {}
        proto = body.get("protocol", "serial")

        if proto == "ethernet":
            a = (body.get("iface_a") or "").strip()
            b = (body.get("iface_b") or "").strip()
            if not a or not b:
                return _error("Pick both ports. The cable needs two ends.")
            try:
                ethernet_tests._validate(a)
                ethernet_tests._validate(b)
            except ethernet_tests.EthernetTestError as exc:
                return _error(str(exc))
            subject = f"{a} to {b}"

            def target(job: Job):
                return continuity.run_eth_monitor(a, b, emit=job.emit, cancel=job.cancel)
        else:
            port = body.get("port")
            if not port:
                return _error("Select a port first.")
            subject = port

            def target(job: Job):
                return continuity.run_serial_monitor(port, emit=job.emit, cancel=job.cancel)

        try:
            job = jobs.start("continuity", subject, target)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        return jsonify({"job": job.id})

    @app.post("/api/cancel/<job_id>")
    def api_cancel(job_id):
        job = jobs.get(job_id)
        if job is None:
            return _error("Unknown job.", 404)
        job.cancel.set()
        return jsonify({"cancelled": True})

    @app.get("/api/job/<job_id>")
    def api_job(job_id):
        job = jobs.get(job_id)
        if job is None:
            return _error("Unknown job.", 404)
        return jsonify(job.summary())

    @app.get("/api/events/<job_id>")
    def api_events(job_id):
        job = jobs.get(job_id)
        if job is None:
            return _error("Unknown job.", 404)

        def stream():
            sub = job.subscribe()
            try:
                while True:
                    try:
                        event = sub.get(timeout=HEARTBEAT_S)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        if job.state != "running":
                            break
                        continue
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                    if event["event"] == "job_end":
                        break
            finally:
                # The worker owns the port, so a disconnected browser only ends
                # the stream. The test finishes and closes the port cleanly.
                job.unsubscribe(sub)

        response = Response(stream_with_context(stream()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    # -------------------------------------------------------------- export
    def _bundle(args) -> dict:
        pin_job = jobs.get(args.get("pincheck") or "")
        sweep_job = jobs.get(args.get("sweep") or "")
        bundle = {
            "tool": "rs232-cable-tester",
            "version": __version__,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "printed_at": fmt_when(),
            "cable_id": args.get("cable_id", "").strip(),
            "operator": args.get("operator", "").strip(),
            "notes": args.get("notes", "").strip(),
            "pin_check": pin_job.result if pin_job else None,
            "sweep": sweep_job.result if sweep_job else None,
        }
        bundle["port"] = (bundle["pin_check"] or bundle["sweep"] or {}).get("port", "")
        bundle["port_info"] = (bundle["pin_check"] or bundle["sweep"] or {}).get("port_info", {})
        bundle["score"] = (bundle["sweep"] or {}).get("score")
        return bundle

    @app.get("/api/export.json")
    def api_export_json():
        bundle = _bundle(request.args)
        name = bundle["cable_id"] or "cable"
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return Response(
            json.dumps(bundle, indent=2),
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="cabletest-{safe}-{stamp}.json"'
            },
        )

    @app.get("/report")
    def report():
        bundle = _bundle(request.args)
        return render_template("report.html", b=bundle, weights=scoring.BAUD_WEIGHTS)

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return _error("No such endpoint.", 404)
        # The same context object as the index route, not a copy of it.
        return render_template("index.html", **_index_context()), 404

    return app


def _error(message: str, status: int = 400, hint: str = ""):
    return jsonify({"error": message, "hint": hint}), status


def _eth_test_cli(iface_a: str, iface_b: str) -> int:
    """Run the ethernet ladder from the command line and print the result.

    Exists so the ladder can be exercised on real hardware before any of it is
    wired into the UI. Everything it reports came from a live interface, which
    is the opposite of the rest of this project's test coverage.
    """
    from . import ethernet_tests as eth

    print(f"\nEthernet speed ladder: {iface_a} <-> {iface_b}")
    print("String the cable under test between the two ports.\n")

    def on_event(kind: str, payload: dict) -> None:
        if kind == "rung_start":
            print(f"  {payload['speed']:>5} Mb  ... ", end="", flush=True)
        elif kind == "rung_done":
            if payload["link"]:
                print(f"link  {payload['negotiated']}Mb/s {payload['duplex']}", end="")
            else:
                print("no link", end="")
            print(f"   (needs pairs {payload['pairs']})")
            if payload.get("anomaly"):
                print(f"         ANOMALY: {payload['anomaly']}")

    try:
        result = eth.run_speed_ladder(iface_a, iface_b, on_event=on_event)
    except eth.EthernetTestError as exc:
        print(f"\n  {exc}\n")
        return 2

    verdict = scoring.score_link_ladder(result["rungs"])
    print(f"\n  Score:   {verdict['score']} ({verdict['band']})")
    if verdict["suspect_pairs"]:
        print(f"  Suspect: pairs {verdict['suspect_pairs']}")
    print(f"  Verdict: {verdict['verdict']}")
    print(f"\n  Took {result['elapsed']}s. Autonegotiation restored.\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cabletester", description="RS-232 cable tester, a bench instrument."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface for the web server (default 0.0.0.0, reachable over the shop network).",
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="TCP port for the web server (default 5000)."
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Add virtual cables (SIM-GOOD, SIM-MARGINAL, ...) so the UI can be "
        "exercised with no hardware attached.",
    )
    parser.add_argument("--debug", action="store_true", help="Flask debug mode.")
    parser.add_argument(
        "--eth-test",
        nargs=2,
        metavar=("IFACE_A", "IFACE_B"),
        help="Run the ethernet speed ladder between two interfaces and exit. "
             "String the cable under test between them, for example "
             "'--eth-test eth0 eth1'.",
    )
    args = parser.parse_args(argv)

    if args.eth_test:
        return _eth_test_cli(*args.eth_test)

    if args.simulate:
        from . import simulator

        simulator.install(serial_tests)
        print("[cabletester] simulation mode: virtual ports registered")

    app = create_app()
    print(f"[cabletester] v{__version__} serving on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
