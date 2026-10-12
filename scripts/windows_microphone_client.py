#!/usr/bin/env python3
"""Live microphone -> UNO Q keyword HTTP service. Install: pip install sounddevice."""

import argparse
from array import array
import json
import math
import queue
import sys
import threading
import time
import urllib.error
import urllib.request


def request_json(endpoint, path, method="GET", data=None, timeout=40):
    request = urllib.request.Request(
        endpoint.rstrip("/") + path, method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        with exc:
            detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Server HTTP {exc.code}: {detail}") from exc


class AudioWindows:
    """Assemble contiguous PCM windows with 50% overlap and a bounded backlog."""
    def __init__(self, samples):
        self.window_bytes = samples * 2
        self.hop_bytes = max(1, samples // 2) * 2
        self.buffer = bytearray()
        self.queue = queue.Queue(maxsize=2)
        self.dropped = 0
        self.overflows = 0

    def capture(self, data, frames, timing, status):
        if status:
            # Never join samples across a device overrun into a model window.
            self.overflows += 1
            self.buffer.clear()
        self.buffer.extend(bytes(data))
        while len(self.buffer) >= self.window_bytes:
            window = bytes(self.buffer[:self.window_bytes])
            del self.buffer[:self.hop_bytes]
            try:
                self.queue.put_nowait(window)
            except queue.Full:
                # Discard the oldest pending window to keep latency bounded.
                try:
                    self.queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass
                self.queue.put_nowait(window)


class MicrophoneSession:
    def __init__(self, endpoint, sd, device=None):
        self.endpoint = endpoint
        self.stopping = threading.Event()
        self.sent = 0
        self.error = None
        self.closed = False
        info = request_json(endpoint, "/v1/sessions", "POST", timeout=10)
        self.session_id = info["session_id"]
        self.sample_rate = info["sample_rate"]
        self.audio = AudioWindows(info["window_samples"])
        self.stream = None
        try:
            sd.check_input_settings(device=device, channels=1, dtype="int16", samplerate=self.sample_rate)
            self.stream = sd.RawInputStream(
                device=device, samplerate=self.sample_rate, channels=1, dtype="int16",
                blocksize=max(1, self.sample_rate // 10), callback=self.audio.capture,
                finished_callback=self.stopping.set,
            )
            self.stream.start()
            self.started = time.monotonic()
            self.worker = threading.Thread(target=self.send_windows, name="audio-sender", daemon=True)
            self.worker.start()
        except Exception:
            if self.stream is not None:
                self.stream.close()
            try:
                request_json(endpoint, f"/v1/sessions/{self.session_id}", "DELETE", timeout=10)
            except Exception as exc:
                print(f"Session cleanup failed: {exc}")
            raise
        print(f"Listening: {self.sample_rate} Hz, mono PCM16, "
              f"{info['window_samples']} samples/window (50% overlap).")

    def send_windows(self):
        while not self.stopping.is_set():
            try:
                window = self.audio.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.stopping.is_set():
                break
            try:
                samples = array("h")
                samples.frombytes(window)  # PortAudio int16 uses native byte order.
                result = request_json(self.endpoint, "/v1/audio", "POST", {
                    "session_id": self.session_id, "sequence": self.sent,
                    "sample_rate": self.sample_rate, "features": samples.tolist(),
                })
                self.sent += 1
                label = result["prediction"]
                confidence = result["classification"][label]
                print(f"Prediction: {label} ({confidence:.1%}) | MCU triggered: {result['bridge_triggered']}")
                if result.get("bridge_error"):
                    print(f"MCU notification error: {result['bridge_error']}")
            except Exception as exc:
                self.error = str(exc)
                self.stopping.set()

    def close(self):
        if self.closed:
            return
        self.stopping.set()
        try:
            self.stream.stop()
        except Exception as exc:
            print(f"Microphone stop error: {exc}")
        finally:
            self.stream.close()
        print("Microphone stopped. Finishing the current request...")
        self.worker.join()
        try:
            result = request_json(self.endpoint, f"/v1/sessions/{self.session_id}", "DELETE", timeout=10)
            print(f"Session ended: {result['windows']} windows, {result['keyword_triggers']} keyword triggers.")
        except Exception as exc:
            print(f"Could not close server session: {exc}. An abandoned session expires after 90 seconds of inactivity.")
        print(f"Audio: {self.audio.dropped} stale windows dropped, {self.audio.overflows} capture warnings. "
              "Unsent/partial audio discarded.")
        if self.error:
            print(f"Session error: {self.error}")
        self.closed = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9200")
    parser.add_argument("--device", type=int, help="Input device index from --list-devices")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--duration-seconds", type=float, default=0, help="Auto-stop each session; 0 means unlimited")
    args = parser.parse_args()
    if args.duration_seconds < 0 or not math.isfinite(args.duration_seconds):
        parser.error("duration must be finite and nonnegative")
    try:
        import sounddevice as sd
    except ImportError:
        parser.error("Install the microphone dependency: py -3.11 -m pip install sounddevice")
    if args.list_devices:
        print(sd.query_devices())
        return
    if sys.platform != "win32":
        parser.error("Interactive controls require Windows; run with Windows Python")
    import msvcrt

    session = None
    print(f"Keyword server: {args.endpoint}")
    print("Controls: [s] start microphone  [d] disconnect  [q] quit. No audio capture is active.")
    try:
        while True:
            if session and (session.stopping.is_set() or (
                args.duration_seconds and time.monotonic() - session.started >= args.duration_seconds
            )):
                session.close()
                session = None
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            key = msvcrt.getwch().lower()
            if key in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            if key == "\x03":
                break
            if key not in ("s", "d", "q"):
                continue
            print(f"Key pressed: {key!r}")
            if key == "s" and session is None:
                try:
                    session = MicrophoneSession(args.endpoint, sd, args.device)
                except Exception as exc:
                    print(f"Unable to start microphone session: {exc}")
            elif key in ("d", "q"):
                if session:
                    session.close()
                    session = None
                if key == "q":
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if session:
            session.close()


if __name__ == "__main__":
    main()
