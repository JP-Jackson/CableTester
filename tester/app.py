"""Flask app: routes, job runner, and the Server-Sent Events stream.

One serial port, one test at a time. This is a bench instrument, not a service.
Tests run on a worker thread; the browser follows along over SSE. Because the
worker owns the port, closing the browser mid-test can never leave it locked.
"""

from __future__ import annotations

import argparse
import datetime
import json
import queue
import threading
import time
import uuid
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from . import __version__, profiles as profiles_mod, scoring, serial_tests

HEARTBEAT_S = 15.0


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
                job.state = "cancelled" if job.cancel.is_set() else "done"
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


def create_app(profiles_path: str = profiles_mod.DEFAULT_PROFILE_PATH) -> Flask:
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
    store = profiles_mod.ProfileStore(profiles_path)

    # ---------------------------------------------------------------- pages
    @app.route("/")
    def index():
        return render_template(
            "index.html",
            version=__version__,
            baud_rates=serial_tests.BAUD_RATES,
            weights=scoring.BAUD_WEIGHTS,
            simulating=serial_tests.simulation_active(),
        )

    # ----------------------------------------------------------------- api
    @app.get("/api/ports")
    def api_ports():
        return jsonify({"ports": serial_tests.list_serial_ports()})

    @app.get("/api/profiles")
    def api_profiles():
        return jsonify(
            {"learned": store.load(), "builtin": profiles_mod.BUILTIN_PROFILES}
        )

    @app.post("/api/profiles")
    def api_learn_profile():
        body = request.get_json(silent=True) or {}
        job_id = body.get("job")
        name = (body.get("name") or "").strip()
        job = jobs.get(job_id) if job_id else None
        if job is None or job.kind != "pincheck" or not job.result:
            return _error("Run a pin check first. There is no matrix to learn from.")
        if not name:
            return _error("Give the profile a name so it can be recognised later.")
        try:
            profile = store.save(
                name,
                job.result["signature"],
                body.get("notes", ""),
                extra={
                    "port": job.result["port"],
                    "port_info": job.result.get("port_info", {}),
                },
            )
        except (ValueError, OSError) as exc:
            return _error(str(exc))
        return jsonify({"profile": profile, "learned": store.load()})

    @app.delete("/api/profiles/<profile_id>")
    def api_delete_profile(profile_id):
        if not store.delete(profile_id):
            return _error(f"No profile named {profile_id}.", 404)
        return jsonify({"learned": store.load()})

    @app.post("/api/pincheck")
    def api_pincheck():
        body = request.get_json(silent=True) or {}
        port = body.get("port")
        if not port:
            return _error("Select a port first.")
        learned = store.load()

        def target(job: Job):
            return serial_tests.run_pin_check(
                port, emit=job.emit, cancel=job.cancel, learned=learned
            )

        try:
            job = jobs.start("pincheck", port, target)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        return jsonify({"job": job.id})

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

        try:
            seconds = float(body.get("payload_seconds", serial_tests.DEFAULT_PAYLOAD_SECONDS))
        except (TypeError, ValueError):
            return _error("Payload seconds must be a number.")
        seconds = max(0.2, min(30.0, seconds))

        def target(job: Job):
            def emit(event_type: str, payload: dict) -> None:
                # Grade each rate as it completes so the live rows can colour
                # themselves without the browser re-implementing scoring.py.
                if event_type == "sweep_rate" and payload.get("state") == "done":
                    graded = scoring.score_sweep([payload["entry"]])["per_rate"]
                    payload = dict(payload, grade=graded[0] if graded else None)
                job.emit(event_type, payload)

            result = serial_tests.run_baud_sweep(
                port, emit=emit, cancel=job.cancel, payload_seconds=seconds
            )
            result["score"] = scoring.score_sweep(result["rates"])
            job.emit("score", result["score"])
            return result

        try:
            job = jobs.start("sweep", port, target)
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
        return render_template("index.html", version=__version__,
                               baud_rates=serial_tests.BAUD_RATES,
                               weights=scoring.BAUD_WEIGHTS,
                               simulating=serial_tests.simulation_active()), 404

    return app


def _error(message: str, status: int = 400, hint: str = ""):
    return jsonify({"error": message, "hint": hint}), status


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
        "--profiles",
        default=profiles_mod.DEFAULT_PROFILE_PATH,
        help="Path to the learned-profile JSON file.",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Add virtual cables (SIM-GOOD, SIM-MARGINAL, ...) so the UI can be "
        "exercised with no hardware attached.",
    )
    parser.add_argument("--debug", action="store_true", help="Flask debug mode.")
    args = parser.parse_args(argv)

    if args.simulate:
        from . import simulator

        simulator.install(serial_tests)
        print("[cabletester] simulation mode: virtual ports registered")

    app = create_app(args.profiles)
    print(f"[cabletester] v{__version__} serving on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
