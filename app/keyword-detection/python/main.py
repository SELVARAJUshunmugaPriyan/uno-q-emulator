#!/usr/bin/env python3
"""HTTP keyword inference service for live Windows microphone clients."""
import json
import logging
import math
import os
import threading
import time
import uuid
import urllib.error
import urllib.request

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StrictInt

LOG = logging.getLogger("keyword-service")


def request_json(url, payload=None, timeout=30):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise


class AudioWindow(BaseModel):
    session_id: str
    sequence: StrictInt = Field(ge=0)
    sample_rate: StrictInt = Field(gt=0)
    features: list[StrictInt] = Field(min_length=1, max_length=96000)


class KeywordService:
    def __init__(self, runner_url=None, mcu_url=None):
        self.runner_url = (runner_url or os.getenv("KEYWORD_RUNNER_URL", "http://runner:1337")).rstrip("/")
        self.mcu_url = (mcu_url or os.getenv("MCU_URL", "http://mcu:9000")).rstrip("/")
        self.label = os.getenv("KEYWORD_LABEL", "hey_dragon")
        self.threshold = float(os.getenv("KEYWORD_THRESHOLD", "0.5"))
        self.cooldown = float(os.getenv("KEYWORD_COOLDOWN_SECONDS", "2"))
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("KEYWORD_THRESHOLD must be between 0 and 1")
        if not math.isfinite(self.cooldown) or self.cooldown < 0:
            raise ValueError("KEYWORD_COOLDOWN_SECONDS must be nonnegative")
        info = request_json(self.runner_url + "/api/info")
        params = info["modelParameters"]
        self.sample_rate = int(params["frequency"])
        self.window_samples = int(params["input_features_count"])
        self.labels = params["labels"]
        if params.get("axis_count", 1) != 1 or not 0 < self.window_samples <= 96000 or self.sample_rate <= 0:
            raise ValueError("Expected a mono audio model with a valid sample rate/window")
        if self.label not in self.labels:
            raise ValueError(f"KEYWORD_LABEL={self.label!r} is absent from model labels {self.labels}")
        self.lock = threading.Lock()
        self.session_id = None
        self.last_activity = 0.0
        self.last_trigger = float("-inf")
        self.sequence = -1
        self.windows = self.triggers = 0
        self.last_result = None
        LOG.info("Runner ready | %d Hz | %d samples/window | keyword=%s",
                 self.sample_rate, self.window_samples, self.label)

    def start(self):
        with self.lock:
            # Recover from a client that crashed without closing its session.
            if self.session_id and time.monotonic() - self.last_activity < 90:
                raise HTTPException(409, "Another microphone session is active")
            self.session_id = uuid.uuid4().hex
            self.last_activity = time.monotonic()
            self.last_trigger = float("-inf")
            self.sequence = -1
            self.windows = self.triggers = 0
            self.last_result = None
            LOG.info("Microphone session started | id=%s", self.session_id[:8])
            return {"session_id": self.session_id, "sample_rate": self.sample_rate,
                    "window_samples": self.window_samples, "labels": self.labels}

    def check_session(self, session_id):
        if self.session_id != session_id:
            raise HTTPException(409, "Session is not active; start a new session")

    def stop(self, session_id):
        with self.lock:
            self.check_session(session_id)
            result = {"session_id": self.session_id, "windows": self.windows, "keyword_triggers": self.triggers}
            self.session_id = None
            LOG.info("Microphone session ended | windows=%d | keyword triggers=%d", self.windows, self.triggers)
            return result

    def infer(self, window):
        if window.sample_rate != self.sample_rate or len(window.features) != self.window_samples:
            raise HTTPException(422, f"Expected {self.window_samples} samples at {self.sample_rate} Hz")
        if any(value < -32768 or value > 32767 for value in window.features):
            raise HTTPException(422, "Audio must contain signed 16-bit PCM integers")
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, "Previous window is still being processed")
        try:
            self.check_session(window.session_id)
            if window.sequence <= self.sequence:
                raise HTTPException(409, "Audio sequence must increase; duplicate window rejected")
            self.sequence = window.sequence
            self.last_activity = time.monotonic()
            try:
                result = request_json(self.runner_url + "/api/features", {"features": window.features})
                classification = result["result"]["classification"]
                if not classification:
                    raise ValueError("Empty classification")
                score = float(classification.get(self.label, 0))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                LOG.exception("Keyword inference failed")
                raise HTTPException(502, "Keyword runner unavailable or invalid response") from exc
            self.windows += 1
            detected = score >= self.threshold
            triggered = False
            bridge_error = None
            if detected and time.monotonic() - self.last_trigger >= self.cooldown:
                # Reserve the cooldown before sending: an uncertain HTTP failure must
                # not produce repeated MCU events for the same spoken keyword.
                self.last_trigger = time.monotonic()
                try:
                    request_json(self.mcu_url + "/bridge/call",
                                 {"method": "keyword_detected", "args": [self.label]}, timeout=5)
                    self.triggers += 1
                    triggered = True
                except (OSError, ValueError) as exc:
                    bridge_error = str(exc)
                    LOG.error("MCU notification failed: %s", exc)
            prediction = max(classification, key=classification.get)
            self.last_activity = time.monotonic()
            self.last_result = {"sequence": window.sequence, "prediction": prediction,
                                "classification": classification, "keyword_detected": detected,
                                "bridge_triggered": triggered, "bridge_error": bridge_error}
            LOG.info("Prediction: %s | keyword confidence=%.1f%% | MCU triggered=%s",
                     prediction, score * 100, triggered)
            return self.last_result
        finally:
            self.lock.release()


def build_app(service=None):
    service = service or KeywordService()
    app = FastAPI(title="UNO Q Live Keyword Detection")

    @app.get("/health")
    def health():
        return {"status": "ok", "sample_rate": service.sample_rate, "window_samples": service.window_samples}

    @app.get("/v1/status")
    def status():
        return {"active": service.session_id is not None, "windows": service.windows,
                "keyword_triggers": service.triggers, "last_result": service.last_result}

    @app.post("/v1/sessions")
    def start_session():
        return service.start()

    @app.delete("/v1/sessions/{session_id}")
    def stop_session(session_id: str):
        return service.stop(session_id)

    @app.post("/v1/audio")
    def audio(window: AudioWindow):
        return service.infer(window)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("KEYWORD_PORT", "9200")))
