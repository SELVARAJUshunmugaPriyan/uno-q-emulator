#!/usr/bin/env python3
"""Keyboard-controlled Windows mouse client for the gesture WebSocket service.

Install the Windows dependency:

    py -3 -m pip install websocket-client

Controls:

    s  start a new collection session
    d  disconnect and save the current session
    q  disconnect, save, and quit
    h  print help

Each session automatically ends after 60 seconds unless disconnected earlier.
Mouse samples are sent every 16 ms only while a session is active.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import msvcrt
import sys
import threading
import time
from ctypes import wintypes

import websocket


USER32 = ctypes.WinDLL("user32", use_last_error=True)
VK_LBUTTON = 0x01
GET_ASYNC_KEY_STATE_DOWN = 0x8000
DEFAULT_SESSION_SECONDS = 60.0


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


USER32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
USER32.GetCursorPos.restype = wintypes.BOOL
USER32.GetAsyncKeyState.argtypes = [ctypes.c_int]
USER32.GetAsyncKeyState.restype = ctypes.c_short


def cursor_position() -> tuple[int, int]:
    point = POINT()
    if not USER32.GetCursorPos(ctypes.byref(point)):
        error = ctypes.get_last_error()
        raise OSError(error, "GetCursorPos failed")
    return int(point.x), int(point.y)


def left_button_down() -> bool:
    return bool(USER32.GetAsyncKeyState(VK_LBUTTON) & GET_ASYNC_KEY_STATE_DOWN)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keyboard-controlled Windows mouse WebSocket client."
    )
    parser.add_argument(
        "--endpoint",
        default="ws://localhost:9100/ws/sensor",
        help="gesture WebSocket endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--interval-ms",
        type=float,
        default=16.0,
        help="mouse sampling interval in milliseconds (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=float,
        default=5000.0,
        help="WebSocket connection timeout in milliseconds (default: %(default)s)",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=DEFAULT_SESSION_SECONDS,
        help="maximum duration of each session (default: %(default)s)",
    )
    args = parser.parse_args()
    if args.interval_ms <= 0:
        parser.error("--interval-ms must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    if args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    return args


def print_help() -> None:
    print("Controls: [s] start session  [d] disconnect/save  [q] save and quit  [h] help")
    print("Each session ends automatically after 60 seconds by default.")


class CollectionSession:
    """Owns one WebSocket and continuously receives server messages.

    The receiver thread is important: it consumes server ping/pong and close
    frames while the main thread remains responsible for 16 ms mouse sampling.
    """

    def __init__(self, socket: websocket.WebSocket, session_id: str) -> None:
        self.socket = socket
        self.session_id = session_id
        self.receiver_stop = threading.Event()
        self.saved = threading.Event()
        self.saved_result: dict[str, object] | None = None
        self.receiver = threading.Thread(
            target=self._receive_loop,
            name="websocket-receiver",
            daemon=True,
        )
        self.receiver.start()

    @classmethod
    def connect(cls, endpoint: str, timeout: float) -> "CollectionSession":
        socket = websocket.create_connection(
            endpoint,
            timeout=timeout,
            enable_multithread=True,
        )
        socket.settimeout(1.0)
        try:
            message = json.loads(socket.recv())
        except (websocket.WebSocketTimeoutException, json.JSONDecodeError) as exc:
            socket.close()
            raise RuntimeError(
                f"did not receive session_started from server: {exc}"
            ) from exc
        if message.get("type") != "session_started":
            socket.close()
            raise RuntimeError(f"unexpected server response: {message}")
        session = cls(socket, str(message.get("session_id", "unknown")))
        print(f"Session started: {session.session_id}")
        return session

    def _receive_loop(self) -> None:
        while not self.receiver_stop.is_set():
            try:
                message = self.socket.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (
                websocket.WebSocketConnectionClosedException,
                OSError,
            ):
                return
            if not message:
                return
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                print(f"Received non-JSON server message: {message}", file=sys.stderr)
                continue
            message_type = payload.get("type")
            if message_type == "session_saved":
                self.saved_result = payload
                self.saved.set()
                return
            if message_type == "error":
                print(f"Server error: {payload.get('error')}", file=sys.stderr)

    def send_sample(self, payload: dict[str, object]) -> None:
        self.socket.send(json.dumps(payload, separators=(",", ":")))

    def disconnect(self) -> None:
        try:
            self.socket.send(json.dumps({"type": "disconnect"}, separators=(",", ":")))
            if self.saved.wait(timeout=5.0) and self.saved_result is not None:
                print(
                    "Session saved: "
                    f"{self.saved_result.get('samples_written', 0)} samples -> "
                    f"{self.saved_result.get('csv_path')}"
                )
            else:
                print("Server did not return session_saved before timeout.")
        except (
            websocket.WebSocketConnectionClosedException,
            websocket.WebSocketTimeoutException,
            OSError,
        ) as exc:
            print(f"Connection already closed: {exc}", file=sys.stderr)
        finally:
            self.close()

    def close(self) -> None:
        self.receiver_stop.set()
        self.socket.close()
        self.receiver.join(timeout=1.0)


def main() -> int:
    args = parse_args()
    interval_seconds = args.interval_ms / 1000.0
    timeout_seconds = args.timeout_ms / 1000.0
    session: CollectionSession | None = None
    session_deadline: float | None = None
    sequence = 0
    sent = 0
    failed = 0
    next_sample = time.perf_counter()
    previous_position = cursor_position()

    print(f"WebSocket endpoint: {args.endpoint}")
    print("No collection is active.")
    print_help()

    try:
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key == "h":
                    print("Key pressed: 'h'")
                    print_help()
                elif key == "s":
                    print("Key pressed: 's'")
                    if session is not None:
                        print("A collection session is already active.")
                    else:
                        try:
                            session = CollectionSession.connect(
                                args.endpoint, timeout_seconds
                            )
                            sequence = 0
                            previous_position = cursor_position()
                            next_sample = time.perf_counter()
                            session_deadline = next_sample + args.duration_seconds
                        except Exception as exc:
                            print(f"Unable to start session: {exc}", file=sys.stderr)
                            session = None
                elif key in {"d", "q"}:
                    print(f"Key pressed: '{key}'")
                    if session is not None:
                        session.disconnect()
                        session = None
                        session_deadline = None
                    else:
                        print("No collection session is active.")
                    if key == "q":
                        break

            if session is None:
                time.sleep(0.02)
                continue

            now = time.perf_counter()
            if session_deadline is not None and now >= session_deadline:
                print("60-second collection period complete; saving session.")
                session.disconnect()
                session = None
                session_deadline = None
                continue

            if now < next_sample:
                time.sleep(next_sample - now)

            try:
                current_position = cursor_position()
                payload = {
                    "type": "sample",
                    "sequence": sequence,
                    "client_time_ms": int(time.time() * 1000),
                    "dx": current_position[0] - previous_position[0],
                    "dy": current_position[1] - previous_position[1],
                    "left_button": left_button_down(),
                }
                previous_position = current_position
                session.send_sample(payload)
                sent += 1
                sequence += 1
                next_sample += interval_seconds
                if next_sample < time.perf_counter() - interval_seconds:
                    next_sample = time.perf_counter() + interval_seconds
            except (
                websocket.WebSocketConnectionClosedException,
                websocket.WebSocketTimeoutException,
                OSError,
            ) as exc:
                failed += 1
                print(f"WebSocket disconnected: {exc}", file=sys.stderr)
                session.close()
                session = None
                session_deadline = None

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received; stopping client.")
    finally:
        if session is not None:
            session.disconnect()

    print(f"Summary: sent={sent} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
