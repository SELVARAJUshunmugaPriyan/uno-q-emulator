#!/usr/bin/env python3
"""WebSocket collection/detection service for the UNO Q gesture exercise."""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

LOG = logging.getLogger("gesture-service")
FIELDS = ("time", "raw_x", "raw_y", "raw_z")


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        value = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return default if value is None else int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("GESTURE_HOST", "0.0.0.0")
    port: int = env_int("GESTURE_PORT", 9100)
    mode: str = os.getenv("GESTURE_MODE", "collection").lower()
    label: str = os.getenv("GESTURE_LABEL", "idle")
    # This is the model path inside the runner, not a local Python-service file.
    model_path: str = os.getenv("GESTURE_MODEL", "/models/custom/gesture-recognition/gesture_recognition_1_3-linux-aarch64-v2-impulse-#1.eim")
    window_size: int = env_int("GESTURE_WINDOW_SIZE", 200)
    queue_size: int = env_int("GESTURE_QUEUE_SIZE", 1000)
    data_dir: Path = Path(os.getenv("GESTURE_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
    idle_x: float = env_float("GESTURE_IDLE_X", 0.0)
    idle_y: float = env_float("GESTURE_IDLE_Y", 0.0)
    idle_z: float = env_float("GESTURE_IDLE_Z", 0.0)
    scale_x: float = env_float("GESTURE_SCALE_X", 0.01)
    scale_y: float = env_float("GESTURE_SCALE_Y", 0.01)
    scale_z: float = env_float("GESTURE_SCALE_Z", 0.01)
    min_value: float = env_float("GESTURE_MIN_VALUE", -4.0)
    max_value: float = env_float("GESTURE_MAX_VALUE", 4.0)
    detection_scale: float = env_float("GESTURE_DETECTION_SCALE", 1.0)
    confidence: float = env_float("GESTURE_CONFIDENCE", 0.1)

    def validate(self) -> None:
        if self.mode not in {"collection", "detection"}:
            raise ValueError("GESTURE_MODE must be collection or detection")
        if not self.label or not 1 <= self.port <= 65535:
            raise ValueError("invalid GESTURE_LABEL or GESTURE_PORT")
        if self.window_size < 1 or self.queue_size < 1:
            raise ValueError("window and queue sizes must be positive")
        if self.min_value >= self.max_value:
            raise ValueError("GESTURE_MIN_VALUE must be less than GESTURE_MAX_VALUE")
        if self.detection_scale <= 0 or not 0 <= self.confidence <= 1:
            raise ValueError("invalid detection scale or confidence")


class CsvCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.samples: list[dict[str, float]] = []
        self.windows_written = self.samples_written = 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.path = settings.data_dir / f"train_data_{settings.label}_{stamp}.csv"
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        LOG.info("CSV output: %s", self.path)

    def _write(self, rows: list[dict[str, float]]) -> None:
        if not rows:
            return
        with self.path.open("a", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            if output.tell() == 0:
                writer.writeheader()
            writer.writerows(rows)
        self.samples_written += len(rows)

    def add(self, timestamp: float, x: float, y: float, z: float) -> None:
        self.samples.append({"time": timestamp, "raw_x": x, "raw_y": y, "raw_z": z})
        if len(self.samples) < self.settings.window_size:
            return
        self._write(self.samples)
        self.windows_written += 1
        LOG.info("wrote complete window=%d samples=%d path=%s", self.windows_written, self.settings.window_size, self.path)
        self.samples.clear()

    def flush(self) -> int:
        count = len(self.samples)
        if count:
            self._write(self.samples)
            LOG.info("flushed partial window samples=%d path=%s", count, self.path)
            self.samples.clear()
        return count


class Mapper:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def map(self, dx: float, dy: float, left: bool) -> tuple[float, float, float]:
        x = self.s.idle_x + dx * self.s.scale_x
        if left:
            y, z = self.s.idle_y, self.s.idle_z + dy * self.s.scale_z
        else:
            y, z = self.s.idle_y + dy * self.s.scale_y, self.s.idle_z
        return tuple(max(self.s.min_value, min(self.s.max_value, value)) for value in (x, y, z))


@dataclass
class Sample:
    sequence: int | None
    timestamp: float
    dx: float
    dy: float
    left: bool


def log_session_summary(result: dict[str, Any]) -> None:
    lines = [
        f"Session ended | mode={result['mode']} | id={result['session_id'][:8]}",
        "  Samples: {samples_received} received, {samples_processed} processed, "
        "{failed_samples} failed".format(**result),
    ]
    if result["mode"] == "detection":
        confidence = result["last_confidence"]
        if confidence is None:
            prediction = "none (no completed inference)"
        elif result["last_prediction"] is None:
            prediction = f"below threshold (highest confidence: {confidence:.2%})"
        else:
            prediction = f"{result['last_prediction']} ({confidence:.2%})"
        lines.extend([
            f"  Inference: {result['detections']} windows "
            f"({result['model_window_samples']} samples/window)",
            f"  Last prediction: {prediction}",
            f"  Partial window: {result['partial_samples_discarded']} samples discarded",
        ])
    else:
        lines.extend([
            f"  CSV: {result['samples_written']} samples saved "
            f"({result['windows_written']} complete windows, "
            f"{result['partial_samples_flushed']} partial samples)",
            f"  File: {result['csv_path']}",
        ])
    if result["last_error"]:
        lines.append(f"  Last error: {result['last_error']}")
    LOG.info("\n".join(lines))
    LOG.debug("Session details: %s", result)


class Detector:
    def __init__(self, settings: Settings) -> None:
        from arduino.app_bricks.motion_detection import MotionDetection

        self.s = settings
        self.model = MotionDetection(confidence=settings.confidence)
        info = self.model.get_model_info()
        if info is None or info.axis_count != 3 or info.input_features_count % 3:
            raise ValueError("Gesture model must accept complete raw_x/raw_y/raw_z samples")
        if not math.isclose(info.interval_ms, 16.0, abs_tol=0.1):
            raise ValueError(f"Model interval is {info.interval_ms} ms; Windows client supplies 16 ms samples")
        self.feature_count = info.input_features_count
        self.labels = info.labels
        self.features: list[float] = []
        self.lock = threading.Lock()
        self.reset()
        LOG.info("gesture runner ready: %s model=%s samples/window=%d labels=%s",
                 self.model.url, settings.model_path, self.feature_count // 3, self.labels)

    def reset(self) -> None:
        self.features.clear()
        self.samples_fed = self.detections = 0
        self.last_classification: dict[str, float] | None = None
        self.last_prediction: str | None = None
        self.last_confidence: float | None = None

    def on_detection(self, classification: dict[str, float]) -> None:
        with self.lock:
            self.detections += 1
            self.last_classification = dict(classification)
            label = max(classification, key=classification.get)
            self.last_confidence = float(classification[label])
            self.last_prediction = label if self.last_confidence >= self.s.confidence else None
            LOG.info("Prediction: %s confidence=%.4f classification=%s",
                     self.last_prediction or "below threshold", self.last_confidence, classification)

    def add(self, x: float, y: float, z: float) -> None:
        scale = self.s.detection_scale
        self.features.extend((x * scale, y * scale, z * scale))
        self.samples_fed += 1
        if len(self.features) < self.feature_count:
            return
        features, self.features = self.features, []
        # The service already owns a sample worker. Invoke the brick's public
        # runner API synchronously so queue draining also waits for inference.
        # accumulate_samples() alone only buffers; it needs an App-managed loop.
        response = self.model.infer_from_features(features)
        classification = (response or {}).get("result", {}).get("classification")
        if not isinstance(classification, dict) or not classification:
            raise RuntimeError("Gesture runner returned no classification")
        self.on_detection(classification)

    def finish(self) -> int:
        # A partial model window cannot be inferred. Never carry it across clients.
        partial = len(self.features) // 3
        self.features.clear()
        return partial

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {"model_path": self.s.model_path, "runner_url": self.model.url,
                    "model_window_samples": self.feature_count // 3, "labels": self.labels,
                    "samples_fed": self.samples_fed, "detections": self.detections,
                    "last_prediction": self.last_prediction, "last_confidence": self.last_confidence,
                    "last_classification": self.last_classification}


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.mapper = Mapper(settings)
        self.detector = Detector(settings) if settings.mode == "detection" else None
        self.q: queue.Queue[Sample | None] = queue.Queue(maxsize=settings.queue_size)
        self.lock = threading.Lock()
        self.collector: CsvCollector | None = None
        self.session_id: str | None = None
        self.active = self.closing = False
        self.last_sequence: int | None = None
        self.received = self.accepted = self.processed = self.rejected = self.dropped = 0
        self.failed = 0
        self.last_error: str | None = None
        self.worker = threading.Thread(target=self._run, name="sample-worker", daemon=True)
        self.worker.start()

    def start(self) -> str | None:
        with self.lock:
            if self.active or self.closing:
                return None
            self.collector = CsvCollector(self.s) if self.s.mode == "collection" else None
            if self.detector is not None:
                self.detector.reset()
            self.session_id = uuid.uuid4().hex
            self.active = True
            self.last_sequence = None
            self.received = self.accepted = self.processed = self.rejected = self.dropped = 0
            self.failed = 0
            self.last_error = None
            LOG.info("started WebSocket session=%s mode=%s", self.session_id, self.s.mode)
            return self.session_id

    def submit(self, sample: Sample) -> tuple[bool, str | None]:
        with self.lock:
            if not self.active:
                return False, "no active WebSocket session"
            self.received += 1
            if sample.sequence == 0:
                self.last_sequence = None
            if sample.sequence is not None and self.last_sequence is not None and sample.sequence <= self.last_sequence:
                self.rejected += 1
                return False, "sequence must increase monotonically"
            if sample.sequence is not None:
                self.last_sequence = sample.sequence
            try:
                self.q.put_nowait(sample)
            except queue.Full:
                self.dropped += 1
                return False, "sample queue is full"
            self.accepted += 1
        return True, None

    def _run(self) -> None:
        while True:
            sample = self.q.get()
            try:
                if sample is None:
                    return
                x, y, z = self.mapper.map(sample.dx, sample.dy, sample.left)
                if self.collector is not None:
                    self.collector.add(sample.timestamp, x, y, z)
                elif self.detector is not None:
                    self.detector.add(x, y, z)
                with self.lock:
                    self.processed += 1
            except Exception as exc:
                # Keep draining on failure; a dead worker would hang disconnect.
                LOG.exception("Sample processing failed")
                with self.lock:
                    self.failed += 1
                    self.last_error = str(exc)
            finally:
                self.q.task_done()

    def stop(self, expected_session: str | None = None) -> dict[str, Any]:
        with self.lock:
            if expected_session is not None and expected_session != self.session_id:
                return {"session_id": expected_session, "samples_processed": 0}
            collector, session_id, was_active = self.collector, self.session_id, self.active
            if not was_active:
                return {"session_id": session_id, "samples_processed": self.processed}
            self.active = False
            self.closing = True
        self.q.join()
        result: dict[str, Any] = {"session_id": session_id, "mode": self.s.mode, "samples_received": self.received, "samples_processed": self.processed,
                                  "failed_samples": self.failed, "last_error": self.last_error}
        if collector is not None:
            partial = collector.flush()
            result.update({"csv_path": str(collector.path), "samples_written": collector.samples_written, "partial_samples_flushed": partial, "windows_written": collector.windows_written})
        if self.detector is not None:
            result.update(self.detector.status())
            result["partial_samples_discarded"] = self.detector.finish()
        with self.lock:
            self.collector = self.session_id = None
            self.closing = False
        log_session_summary(result)
        return result

    def close(self) -> None:
        self.stop()
        self.q.put(None)
        self.worker.join()

    def status(self) -> dict[str, Any]:
        with self.lock:
            result: dict[str, Any] = {"active": self.active, "closing": self.closing, "session_id": self.session_id, "mode": self.s.mode, "received_samples": self.received, "accepted_samples": self.accepted, "processed_samples": self.processed, "rejected_samples": self.rejected, "dropped_samples": self.dropped, "last_sequence": self.last_sequence, "queue_depth": self.q.qsize(), "sample_rate_hz": 62.5}
            result.update({"failed_samples": self.failed, "last_error": self.last_error})
            if self.collector is not None:
                result.update({"label": self.s.label, "window_size": self.s.window_size, "windows_written": self.collector.windows_written, "partial_samples": len(self.collector.samples), "csv_path": str(self.collector.path)})
            if self.detector is not None:
                result.update(self.detector.status())
            return result


def parse_sample(payload: Any) -> Sample:
    if not isinstance(payload, dict):
        raise ValueError("sample message must be a JSON object")
    sequence = payload.get("sequence")
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)):
        raise ValueError("sequence must be an integer")

    def number(name: str, default: float | None = None) -> float:
        value = payload.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value

    timestamp, dx, dy = number("client_time_ms", time.time() * 1000), number("dx"), number("dy")
    left = payload.get("left_button", False)
    if not isinstance(left, bool):
        raise ValueError("left_button must be boolean")
    if abs(dx) > 10000 or abs(dy) > 10000:
        raise ValueError("mouse delta is outside the allowed range")
    return Sample(sequence, timestamp, dx, dy, left)


def build_app(settings: Settings) -> FastAPI:
    settings.validate()
    pipeline = Pipeline(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            await run_in_threadpool(pipeline.close)

    app = FastAPI(title="UNO Q Gesture Service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "gesture-service", "mode": settings.mode}

    @app.get("/v1/status")
    async def status() -> dict[str, Any]:
        return pipeline.status()

    @app.websocket("/ws/sensor")
    async def sensor_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        session_id = pipeline.start()
        if session_id is None:
            await websocket.close(code=1013, reason="another client is active")
            return
        try:
            await websocket.send_json({"type": "session_started", "session_id": session_id, "sample_rate_hz": 62.5, "mode": settings.mode})
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    await websocket.send_json({"type": "error", "error": "message must be an object"})
                    continue
                if message.get("type") == "disconnect":
                    result = await run_in_threadpool(pipeline.stop, session_id)
                    await websocket.send_json({"type": "session_saved", **result})
                    await websocket.close(code=1000, reason="session saved")
                    return
                if message.get("type", "sample") != "sample":
                    await websocket.send_json({"type": "error", "error": "unknown message type"})
                    continue
                try:
                    accepted, error = pipeline.submit(parse_sample(message))
                except ValueError as exc:
                    accepted, error = False, str(exc)
                if not accepted:
                    await websocket.send_json({"type": "error", "error": error})
        except WebSocketDisconnect as exc:
            LOG.info("WebSocket client disconnected code=%s", exc.code)
        finally:
            await run_in_threadpool(pipeline.stop, session_id)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="UNO Q gesture WebSocket service")
    parser.add_argument("--mode", choices=("collection", "detection"), default=None)
    args = parser.parse_args()
    settings = Settings()
    if args.mode:
        settings = replace(settings, mode=args.mode)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, ws_ping_interval=20.0, ws_ping_timeout=20.0)


if __name__ == "__main__":
    main()
