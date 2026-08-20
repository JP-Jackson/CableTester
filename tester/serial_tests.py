"""Serial I/O: port enumeration, pin check, and baud sweep.

Everything that touches a serial port lives here. Ports are always opened and
closed inside these functions so a crashed test or a dropped browser connection
can never leave an adapter locked.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Dict, List, Optional

import serial
from serial.tools import list_ports

from . import profiles as profiles_mod

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

OUTPUT_LINES = ["DTR", "RTS"]
INPUT_LINES = ["CTS", "DSR", "DCD", "RI"]

#: pin -> (signal, direction as seen from the tester/DTE)
DB9_PINS: Dict[int, tuple] = {
    1: ("DCD", "in"),
    2: ("RXD", "in"),
    3: ("TXD", "out"),
    4: ("DTR", "out"),
    5: ("GND", "ref"),
    6: ("DSR", "in"),
    7: ("RTS", "out"),
    8: ("CTS", "in"),
    9: ("RI", "in"),
}

SIGNAL_PINS = {sig: pin for pin, (sig, _dir) in DB9_PINS.items()}

#: Which output is expected to drive which input through the loopback plug
#: (7-8 RTS/CTS, 4-1-6 DTR/DCD/DSR).  Used for reporting only — topology is
#: determined empirically, see profiles.identify().
EXPECTED_DRIVER = {"CTS": "RTS", "DSR": "DTR", "DCD": "DTR", "RI": None}

#: Time allowed for a modem-control line to settle after a change. USB-serial
#: adapters route these over USB control transfers, so they are far from instant.
LINE_SETTLE_S = 0.12

#: Pattern used to prove the 2/3 data path during the pin check.
PIN_CHECK_PATTERN = bytes([0x55, 0xAA, 0x00, 0xFF, 0x0F, 0xF0, 0x5A, 0xA5])
PIN_CHECK_BAUD = 9600

#: Baud sweep payload sizing.
DEFAULT_PAYLOAD_SECONDS = 2.0
MIN_PAYLOAD_BYTES = 64
MAX_PAYLOAD_BYTES = 65536
PAYLOAD_SEED = 0x5232  # "R232" — seeded so runs are reproducible.

_POPCOUNT = [bin(i).count("1") for i in range(256)]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class CableTesterError(Exception):
    """Base class for errors we can explain to a technician."""

    hint = ""


class PortBusyError(CableTesterError):
    hint = (
        "Another program is holding the port. PCCU is the usual culprit — close "
        "it (including any minimised instance) and try again."
    )


class PortNotFoundError(CableTesterError):
    hint = "The adapter may have been unplugged. Refresh the port list."


class PortAccessError(CableTesterError):
    hint = (
        "On Linux add your user to the 'dialout' group and log out and back in: "
        "sudo usermod -aG dialout $USER"
    )


class TestCancelled(CableTesterError):
    """Raised internally when the operator cancels a running test."""


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


def list_serial_ports() -> List[dict]:
    """Enumerate serial ports with enough detail to tell adapters apart."""
    found = []
    for info in sorted(list_ports.comports(), key=lambda p: p.device):
        vid = getattr(info, "vid", None)
        pid = getattr(info, "pid", None)
        found.append(
            {
                "device": info.device,
                "description": info.description or "n/a",
                "manufacturer": getattr(info, "manufacturer", None) or "",
                "product": getattr(info, "product", None) or "",
                "serial_number": getattr(info, "serial_number", None) or "",
                "vid": vid,
                "pid": pid,
                "vid_pid": f"{vid:04X}:{pid:04X}" if vid is not None and pid is not None else "",
                "hwid": info.hwid or "",
            }
        )
    return found


def port_info(device: str) -> dict:
    for entry in list_serial_ports():
        if entry["device"] == device:
            return entry
    return {"device": device, "description": "unknown", "vid_pid": "", "hwid": ""}


def _translate_serial_error(device: str, exc: Exception) -> CableTesterError:
    text = str(exc).lower()
    if "permission" in text or "access is denied" in text or "access denied" in text:
        # Windows reports a held port as an access error too.
        if "access is denied" in text or "access denied" in text:
            return PortBusyError(f"{device} is in use or access was denied.")
        return PortAccessError(f"Permission denied opening {device}.")
    if "busy" in text or "in use" in text or "resource temporarily unavailable" in text:
        return PortBusyError(f"{device} is already open in another program.")
    if "no such file" in text or "could not open port" in text or "filenotfound" in text:
        return PortNotFoundError(f"{device} is not available.")
    return CableTesterError(f"Could not open {device}: {exc}")


def open_serial(
    device: str,
    baudrate: int = PIN_CHECK_BAUD,
    parity: str = serial.PARITY_NONE,
    timeout: float = 0.2,
    write_timeout: float = 5.0,
    serial_factory: Optional[Callable[..., serial.SerialBase]] = None,
) -> serial.SerialBase:
    """Open a port, translating driver errors into something a tech can act on."""
    factory = serial_factory or serial.Serial
    try:
        port = factory(
            port=device,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=parity,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=write_timeout,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
    except (serial.SerialException, OSError, ValueError) as exc:
        raise _translate_serial_error(device, exc) from exc
    return port


def _noop(event_type: str, payload: dict) -> None:
    return None


def _check_cancel(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise TestCancelled("Test cancelled by operator.")


# --------------------------------------------------------------------------
# Stage 1 — Pin check
# --------------------------------------------------------------------------


def _read_inputs(ser: serial.SerialBase) -> Dict[str, bool]:
    return {
        "CTS": bool(ser.cts),
        "DSR": bool(ser.dsr),
        "DCD": bool(ser.cd),
        "RI": bool(ser.ri),
    }


def _set_output(ser: serial.SerialBase, line: str, state: bool) -> None:
    if line == "DTR":
        ser.dtr = state
    elif line == "RTS":
        ser.rts = state
    else:  # pragma: no cover - guarded by OUTPUT_LINES
        raise ValueError(f"Unknown output line {line}")


def _data_loopback(ser: serial.SerialBase) -> dict:
    """Send a short pattern and see if it comes back (proves pins 2 and 3)."""
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    pattern = PIN_CHECK_PATTERN
    started = time.monotonic()
    ser.write(pattern)
    ser.flush()
    # 9600 baud, 8 bytes -> ~8 ms. One second is luxurious but costs nothing
    # when the cable is good.
    deadline = started + 1.0
    received = bytearray()
    while len(received) < len(pattern) and time.monotonic() < deadline:
        chunk = ser.read(len(pattern) - len(received))
        if chunk:
            received.extend(chunk)
    elapsed = time.monotonic() - started
    return {
        "sent": pattern.hex(),
        "received": bytes(received).hex(),
        "ok": bytes(received) == pattern,
        "elapsed_s": round(elapsed, 4),
    }


def run_pin_check(
    device: str,
    emit: Callable[[str, dict], None] = _noop,
    cancel: Optional[threading.Event] = None,
    learned: Optional[List[dict]] = None,
    serial_factory: Optional[Callable[..., serial.SerialBase]] = None,
) -> dict:
    """Stage 1: drive each output in turn and record every input's response.

    Builds the full stimulus/response matrix empirically, then compares it
    against reference and learned signatures to name the topology.
    """
    emit("stage", {"stage": "pincheck", "state": "start", "port": device})
    info = port_info(device)
    ser = open_serial(device, baudrate=PIN_CHECK_BAUD, serial_factory=serial_factory)
    try:
        # Everything off, then let the far end settle before the baseline read.
        _set_output(ser, "DTR", False)
        _set_output(ser, "RTS", False)
        time.sleep(LINE_SETTLE_S * 2)
        baseline = _read_inputs(ser)
        emit("pin_baseline", {"baseline": baseline})

        matrix: Dict[str, Dict[str, bool]] = {}
        raw: Dict[str, dict] = {}
        for out in OUTPUT_LINES:
            _check_cancel(cancel)
            emit("pin_step", {"output": out, "state": "asserting"})
            _set_output(ser, out, True)
            time.sleep(LINE_SETTLE_S)
            asserted = _read_inputs(ser)

            _set_output(ser, out, False)
            time.sleep(LINE_SETTLE_S)
            released = _read_inputs(ser)

            # A line "responded" only if it followed the output both up and back
            # down again. A line that changed but never returned is stuck, not
            # connected, and is reported as such below.
            responses = {}
            stuck = {}
            for inp in INPUT_LINES:
                followed_up = asserted[inp] != baseline[inp]
                came_back = released[inp] == baseline[inp]
                responses[inp] = bool(followed_up and came_back)
                stuck[inp] = bool(followed_up and not came_back)
            matrix[out] = responses
            raw[out] = {"asserted": asserted, "released": released, "stuck": stuck}
            emit("pin_step", {"output": out, "state": "done", "responses": responses})

        _check_cancel(cancel)
        emit("pin_step", {"output": "TXD", "state": "asserting"})
        data = _data_loopback(ser)
        emit("pin_step", {"output": "TXD", "state": "done", "responses": {"RXD": data["ok"]}})
    finally:
        _close_quietly(ser)

    signature = profiles_mod.canonical(matrix, data["ok"])
    topology = profiles_mod.identify(signature, learned)
    pins = _grade_pins(matrix, raw, baseline, data)
    passed = all(p["result"] == "pass" for p in pins if p["graded"])

    result = {
        "type": "pincheck",
        "port": device,
        "port_info": info,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "baseline": baseline,
        "matrix": matrix,
        "raw": raw,
        "data_loopback": data,
        "signature": signature,
        "signature_text": profiles_mod.describe(signature),
        "topology": topology,
        "pins": pins,
        "passed": passed,
        "summary": _pin_summary(pins, topology, passed),
    }
    emit("stage", {"stage": "pincheck", "state": "done", "passed": passed})
    emit("pincheck_result", result)
    return result


def _grade_pins(matrix, raw, baseline, data) -> List[dict]:
    """Turn the matrix into a per-pin pass / open / short verdict."""
    pins = []
    for pin in sorted(DB9_PINS):
        signal, direction = DB9_PINS[pin]
        entry = {
            "pin": pin,
            "signal": signal,
            "direction": direction,
            "graded": True,
            "result": "pass",
            "detail": "",
        }

        if signal in INPUT_LINES:
            expected = EXPECTED_DRIVER[signal]
            drivers = [out for out in OUTPUT_LINES if matrix[out].get(signal)]
            unexpected = [out for out in drivers if out != expected]
            stuck = any(raw[out]["stuck"].get(signal) for out in OUTPUT_LINES)

            if unexpected:
                entry["result"] = "short"
                entry["detail"] = (
                    f"responded to {', '.join(unexpected)} "
                    f"(expected {expected or 'no stimulus'}) — cross-connected"
                )
            elif expected is None:
                if baseline.get(signal):
                    entry["result"] = "short"
                    entry["detail"] = "reads asserted with no stimulus"
                else:
                    entry["detail"] = "idle as expected (RI is unused)"
            elif expected in drivers:
                entry["detail"] = f"followed {expected}"
            elif stuck:
                entry["result"] = "short"
                entry["detail"] = f"followed {expected} but did not release — stuck"
            else:
                entry["result"] = "open"
                entry["detail"] = f"no response when {expected} was asserted"

        elif signal in OUTPUT_LINES:
            driven = [inp for inp in INPUT_LINES if matrix[signal].get(inp)]
            if driven:
                entry["detail"] = f"drove {', '.join(driven)}"
            else:
                entry["result"] = "open"
                entry["detail"] = "asserting this line produced no response anywhere"

        elif signal in ("TXD", "RXD"):
            if data["ok"]:
                entry["detail"] = "byte pattern looped back intact"
            elif data["received"]:
                entry["result"] = "short"
                entry["detail"] = (
                    f"pattern returned corrupted (sent {data['sent']}, got {data['received']})"
                )
            else:
                entry["result"] = "open"
                entry["detail"] = "no bytes returned"

        else:  # pin 5, signal ground
            entry["graded"] = False
            entry["result"] = "reference"
            entry["detail"] = (
                "signal ground — not directly testable; a working data path "
                "implies a good return"
            )

        pins.append(entry)
    return pins


def _pin_summary(pins, topology, passed) -> str:
    if passed:
        if topology["kind"] == "unknown":
            return "All tested pins responded, but the wiring map is non-standard."
        if topology["kind"] == "ambiguous":
            return f"All tested pins responded. Topology: {topology['label']}."
        return f"All tested pins responded. Topology: {topology['label']}."
    opens = [f"pin {p['pin']} ({p['signal']})" for p in pins if p["result"] == "open"]
    shorts = [f"pin {p['pin']} ({p['signal']})" for p in pins if p["result"] == "short"]
    parts = []
    if opens:
        parts.append("open: " + ", ".join(opens))
    if shorts:
        parts.append("short/cross: " + ", ".join(shorts))
    return "Faults found — " + "; ".join(parts)


# --------------------------------------------------------------------------
# Stage 2 — Baud sweep
# --------------------------------------------------------------------------


def payload_for(baud: int, seconds: float = DEFAULT_PAYLOAD_SECONDS) -> bytes:
    """Reproducible pseudorandom payload, sized so each rate takes ~`seconds`.

    Scaling with baud keeps 1200 from taking a minute while still giving 115200
    enough traffic to expose a marginal cable.
    """
    nbytes = int(baud / 10.0 * seconds)
    nbytes = max(MIN_PAYLOAD_BYTES, min(MAX_PAYLOAD_BYTES, nbytes))
    rng = random.Random(PAYLOAD_SEED ^ baud)
    return bytes(rng.getrandbits(8) for _ in range(nbytes))


def _bits_per_byte(parity: str) -> int:
    # 1 start + 8 data + optional parity + 1 stop
    return 11 if parity != serial.PARITY_NONE else 10


def _close_quietly(ser: Optional[serial.SerialBase]) -> None:
    if ser is None:
        return
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    try:
        ser.close()
    except Exception:
        pass


def _transfer(
    ser: serial.SerialBase,
    payload: bytes,
    baud: int,
    parity: str,
    emit: Callable[[str, dict], None],
    progress_key: dict,
    cancel: Optional[threading.Event],
) -> dict:
    """Push the payload through the loopback, interleaving writes and reads.

    Writing everything before reading would overrun the driver's receive buffer
    on the larger payloads, so this alternates in chunks.
    """
    total = len(payload)
    bits = _bits_per_byte(parity)
    byte_time = bits / float(baud)

    # Generous at low baud, tight at high: allow 2.5x the theoretical time plus
    # a fixed allowance for USB latency.
    expected_s = total * byte_time
    deadline = time.monotonic() + expected_s * 2.5 + 1.0
    idle_limit = max(0.5, byte_time * 200)

    chunk = max(64, min(1024, int(baud / 40) or 64))
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    sent = 0
    received = bytearray()
    timeouts = 0
    last_rx = time.monotonic()
    last_emit = 0.0
    started = time.monotonic()

    while received.__len__() < total:
        _check_cancel(cancel)
        now = time.monotonic()
        if now > deadline:
            timeouts += 1
            break

        if sent < total:
            try:
                written = ser.write(payload[sent : sent + chunk])
            except serial.SerialTimeoutException:
                timeouts += 1
                break
            sent += written if written is not None else chunk

        waiting = 0
        try:
            waiting = ser.in_waiting
        except Exception:
            waiting = 0
        want = min(total - len(received), max(waiting, 1))
        data = ser.read(want)
        if data:
            received.extend(data)
            last_rx = time.monotonic()
        elif sent >= total and (time.monotonic() - last_rx) > idle_limit:
            timeouts += 1
            break

        now = time.monotonic()
        if now - last_emit > 0.15:
            last_emit = now
            emit(
                "sweep_progress",
                dict(
                    progress_key,
                    sent=sent,
                    received=len(received),
                    total=total,
                    fraction=round(len(received) / total, 4),
                    elapsed_s=round(now - started, 3),
                ),
            )

    elapsed = time.monotonic() - started
    got = bytes(received)
    compared = min(len(got), total)
    mismatched = 0
    bit_errors = 0
    first_bad = None
    for i in range(compared):
        if got[i] != payload[i]:
            mismatched += 1
            bit_errors += _POPCOUNT[got[i] ^ payload[i]]
            if first_bad is None:
                first_bad = i
    missing = total - compared
    bit_errors += missing * 8

    bits_total = total * 8
    ber = bit_errors / bits_total if bits_total else 0.0
    throughput_bps = (compared * bits) / elapsed if elapsed > 0 else 0.0

    return {
        "baud": baud,
        "parity": "even" if parity != serial.PARITY_NONE else "none",
        "sent": sent,
        "total": total,
        "received": len(got),
        "mismatched": mismatched,
        "missing": missing,
        "timeouts": timeouts,
        "bit_errors": bit_errors,
        "bits_total": bits_total,
        "ber": ber,
        "elapsed_s": round(elapsed, 3),
        "throughput_bps": round(throughput_bps, 1),
        "theoretical_bps": baud,
        "efficiency_pct": round(throughput_bps / baud * 100.0, 1) if baud else 0.0,
        "first_bad_offset": first_bad,
    }


def run_baud_sweep(
    device: str,
    emit: Callable[[str, dict], None] = _noop,
    cancel: Optional[threading.Event] = None,
    payload_seconds: float = DEFAULT_PAYLOAD_SECONDS,
    rates: Optional[List[int]] = None,
    serial_factory: Optional[Callable[..., serial.SerialBase]] = None,
) -> dict:
    """Stage 2: run every rate, twice (no parity then even parity).

    Never aborts on first failure — knowing a cable is clean to 19200 but fails
    at 57600 is the useful result.
    """
    rates = rates or BAUD_RATES
    emit("stage", {"stage": "sweep", "state": "start", "port": device, "rates": rates})
    results: List[dict] = []
    cancelled = False

    for baud in rates:
        entry = {"baud": baud, "runs": {}}
        results.append(entry)
        payload = payload_for(baud, payload_seconds)
        emit(
            "sweep_rate",
            {"baud": baud, "state": "start", "bytes": len(payload)},
        )
        for parity_name, parity in (("none", serial.PARITY_NONE), ("even", serial.PARITY_EVEN)):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            ser = None
            try:
                ser = open_serial(
                    device,
                    baudrate=baud,
                    parity=parity,
                    timeout=0.05,
                    write_timeout=max(2.0, len(payload) * 11.0 / baud * 3),
                    serial_factory=serial_factory,
                )
                run = _transfer(
                    ser,
                    payload,
                    baud,
                    parity,
                    emit,
                    {"baud": baud, "parity": parity_name},
                    cancel,
                )
            except TestCancelled:
                cancelled = True
                break
            except CableTesterError as exc:
                run = _failed_run(baud, parity_name, len(payload), str(exc))
            except (serial.SerialException, OSError) as exc:
                run = _failed_run(baud, parity_name, len(payload), str(exc))
            finally:
                _close_quietly(ser)

            entry["runs"][parity_name] = run
            emit("sweep_run", {"baud": baud, "parity": parity_name, "run": run})

        emit("sweep_rate", {"baud": baud, "state": "done", "entry": entry})
        if cancelled:
            break

    result = {
        "type": "sweep",
        "port": device,
        "port_info": port_info(device),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "payload_seconds": payload_seconds,
        "rates": results,
        "cancelled": cancelled,
    }
    emit("stage", {"stage": "sweep", "state": "done", "cancelled": cancelled})
    return result


def _failed_run(baud: int, parity_name: str, total: int, error: str) -> dict:
    return {
        "baud": baud,
        "parity": parity_name,
        "sent": 0,
        "total": total,
        "received": 0,
        "mismatched": 0,
        "missing": total,
        "timeouts": 1,
        "bit_errors": total * 8,
        "bits_total": total * 8,
        "ber": 1.0,
        "elapsed_s": 0.0,
        "throughput_bps": 0.0,
        "theoretical_bps": baud,
        "efficiency_pct": 0.0,
        "first_bad_offset": 0,
        "error": error,
    }
