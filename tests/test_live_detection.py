"""Hardware-free checks using real HTTP servers and simulated model responses.

Run with the gesture image's Python dependencies and this repo mounted at /workspace.
"""
import base64
from array import array
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import uvicorn
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


keyword = load("keyword_app", "app/keyword-detection/python/main.py")
microphone = load("microphone_client", "scripts/windows_microphone_client.py")


class HttpApp:
    def __init__(self, app):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("HTTP app failed to start")
            time.sleep(0.01)
        return self

    def request(self, path, body=None, method=None):
        req = urllib.request.Request(self.url + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()
        assert not self.thread.is_alive(), "HTTP server did not stop"


class FakeRunner(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({"modelParameters": {"frequency": 16000, "input_features_count": 4,
                    "axis_count": 1, "labels": ["hey_dragon", "noise"]}})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/bridge/call":
            self.server.events.append(payload)
            self.reply({"ok": True})
        elif self.server.fail:
            self.reply({"error": "test failure"}, 500)
        else:
            self.server.windows.append(payload["features"])
            self.reply({"result": {"classification": {"hey_dragon": self.server.score,
                                                       "noise": 1 - self.server.score}}})


class KeywordTests(unittest.TestCase):
    def setUp(self):
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeRunner)
        self.fake.events, self.fake.windows = [], []
        self.fake.fail, self.fake.score = False, 0.9
        self.thread = threading.Thread(target=self.fake.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)
        url = f"http://127.0.0.1:{self.fake.server_port}"
        self.service = keyword.KeywordService(url, url)

    def cleanup(self):
        self.fake.shutdown()
        self.fake.server_close()
        self.thread.join()

    def test_live_http_contract_validation_and_cooldown(self):
        with HttpApp(keyword.build_app(self.service)) as app:
            session = app.request("/v1/sessions", {}, "POST")
            payload = {"session_id": session["session_id"], "sequence": 0,
                       "sample_rate": 16000, "features": [-32768, 0, 100, 32767]}
            result = app.request("/v1/audio", payload)
            self.assertTrue(result["bridge_triggered"])
            self.assertEqual(self.fake.windows[0], payload["features"])
            with self.assertRaises(urllib.error.HTTPError) as error:
                app.request("/v1/audio", payload)
            self.assertEqual(error.exception.code, 409)
            payload["sequence"] = 1
            self.assertFalse(app.request("/v1/audio", payload)["bridge_triggered"])
            self.assertEqual(len(self.fake.events), 1)
            payload["features"] = [True, 0, 0, 0]
            with self.assertRaises(urllib.error.HTTPError) as error:
                app.request("/v1/audio", payload)
            self.assertEqual(error.exception.code, 422)
            summary = app.request(f"/v1/sessions/{session['session_id']}", method="DELETE")
            self.assertEqual(summary["windows"], 2)
            self.assertFalse(app.request("/v1/status")["active"])

    def test_low_confidence_and_runner_failure(self):
        session = self.service.start()
        self.fake.score = 0.1
        window = keyword.AudioWindow(session_id=session["session_id"], sequence=0,
                                     sample_rate=16000, features=[0, 0, 0, 0])
        self.assertFalse(self.service.infer(window)["keyword_detected"])
        self.assertFalse(self.fake.events)
        self.fake.fail = True
        window.sequence = 1
        with self.assertRaises(keyword.HTTPException) as error:
            self.service.infer(window)
        self.assertEqual(error.exception.status_code, 502)
        self.service.stop(session["session_id"])
        self.assertIsNone(self.service.session_id)

    def test_microphone_sender_to_server(self):
        class Stream:
            def start(self): pass
            def stop(self): pass
            def close(self): pass

        class AudioDevice:
            def check_input_settings(self, **kwargs): pass
            def RawInputStream(self, **kwargs): return Stream()

        with HttpApp(keyword.build_app(self.service)) as app:
            session = microphone.MicrophoneSession(app.url, AudioDevice())
            try:
                session.audio.capture(array("h", [1, 2, 3, 4]).tobytes(), 4, None, False)
                deadline = time.monotonic() + 5
                while session.sent < 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(session.sent, 1)
            finally:
                session.close()
            self.assertEqual(self.fake.windows, [[1, 2, 3, 4]])
            self.assertEqual(len(self.fake.events), 1)
            self.assertIsNone(self.service.session_id)

    def test_audio_overlap_backpressure_and_capture_gap(self):
        audio = microphone.AudioWindows(4)
        audio.capture(array("h", range(1, 11)).tobytes(), 10, None, False)
        self.assertEqual(audio.queue.qsize(), 2)
        self.assertEqual(audio.dropped, 2)
        self.assertEqual(list(array("h", audio.queue.get_nowait())), [5, 6, 7, 8])
        self.assertEqual(list(array("h", audio.queue.get_nowait())), [7, 8, 9, 10])
        audio.capture(array("h", [11, 12]).tobytes(), 2, None, True)
        self.assertTrue(audio.queue.empty())
        self.assertEqual(audio.overflows, 1)


class ObjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Model:
            def detect(self, image, confidence):
                return {"detection": [{"label": "test"}]}
            def draw_bounding_boxes(self, image, results):
                return image
        with patch("arduino.app_bricks.object_detection.ObjectDetection", Model):
            cls.module = load("object_app", "app/object-detection/python/main.py")
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, format="PNG")
        cls.payload = {"image": base64.b64encode(output.getvalue()).decode(), "confidence": 0.5}

    def test_rest_and_legacy_socketio_result_routing(self):
        with HttpApp(self.module.ui.app) as app:
            result = app.request("/api/detect", self.payload)
            self.assertEqual(result["detection_count"], 1)
            self.assertTrue(base64.b64decode(result["result_image"]).startswith(b"\x89PNG"))
            with self.assertRaises(urllib.error.HTTPError) as error:
                app.request("/api/detect", {"image": "bad!"})
            self.assertEqual(error.exception.code, 400)
            self.module.inference_lock.acquire()
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    app.request("/api/detect", self.payload)
                self.assertEqual(error.exception.code, 429)
            finally:
                self.module.inference_lock.release()
        with patch.object(self.module.ui, "send_message") as send:
            self.module.on_detect_objects("client-123", self.payload)
            self.assertEqual(send.call_args.kwargs["room"], "client-123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
