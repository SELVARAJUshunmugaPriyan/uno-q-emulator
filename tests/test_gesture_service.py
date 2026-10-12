"""Run in the gesture image; exercises the installed Arduino brick against a fake runner.

docker run --rm --platform linux/arm64 --network none \
  -v "$PWD:/workspace:ro" --entrypoint python uno-q-gesture-gesture \
  /workspace/tests/test_gesture_service.py
"""

import csv
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/gesture-recognition/python"))
import main as service
from arduino.app_bricks.motion_detection import MotionDetection
from websockets.sync.client import connect


class RunnerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/api/info":
            return self.reply({}, 404)
        self.reply({"project": {"name": "test gesture"}, "modelParameters": {
            "axis_count": 3, "input_features_count": 6, "frequency": 62.5,
            "interval_ms": 16, "labels": ["idle", "circle"], "thresholds": []}})

    def do_POST(self):
        if self.path != "/api/features":
            return self.reply({}, 404)
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.features.append(payload["features"])
        if self.server.fail:
            return self.reply({"error": "inference failed"}, 500)
        self.reply({"result": {"classification": {"idle": 0.05, "circle": 0.95}}})


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner = ThreadingHTTPServer(("127.0.0.1", 0), RunnerHandler)
        self.runner.features = []
        self.runner.fail = False
        self.runner_thread = threading.Thread(target=self.runner.serve_forever, daemon=True)
        self.runner_thread.start()
        self.addCleanup(self.stop_runner)
        url = f"http://127.0.0.1:{self.runner.server_port}"
        self.address_patch = patch.object(MotionDetection, "_get_ei_url", return_value=url)
        self.address_patch.start()
        self.addCleanup(self.address_patch.stop)

    def stop_runner(self):
        self.runner.shutdown()
        self.runner.server_close()
        self.runner_thread.join()

    def pipeline(self, mode):
        settings = service.Settings(mode=mode, data_dir=Path(self.temp.name))
        pipeline = service.Pipeline(settings)
        self.addCleanup(pipeline.close)
        return pipeline

    def sample(self, sequence, dx=10, dy=20, left=False):
        return service.Sample(sequence, sequence * 16.0, dx, dy, left)

    def test_collection_flushes_200_plus_partial_without_using_runner(self):
        with patch.object(service, "Detector", side_effect=AssertionError("collection loaded model")):
            pipeline = self.pipeline("collection")
        session = pipeline.start()
        for index in range(203):
            self.assertTrue(pipeline.submit(self.sample(index))[0])
        result = pipeline.stop(session)
        self.assertEqual(result["samples_written"], 203)
        self.assertEqual(result["windows_written"], 1)
        self.assertEqual(result["partial_samples_flushed"], 3)
        with open(result["csv_path"], newline="") as csv_file:
            self.assertEqual(len(list(csv.DictReader(csv_file))), 203)
        self.assertEqual(self.runner.features, [])

    def test_detection_uses_model_window_and_training_units(self):
        pipeline = self.pipeline("detection")
        session = pipeline.start()
        pipeline.submit(self.sample(0))
        pipeline.submit(self.sample(1, dx=-10, left=True))
        pipeline.submit(self.sample(2))
        result = pipeline.stop(session)
        self.assertEqual(self.runner.features, [[0.1, 0.2, 0.0, -0.1, 0.0, 0.2]])
        self.assertEqual(result["last_prediction"], "circle")
        self.assertEqual(result["last_confidence"], 0.95)
        self.assertEqual(result["detections"], 1)
        self.assertEqual(result["partial_samples_discarded"], 1)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        new_session = pipeline.start()
        pipeline.stop(session)  # A previous connection's finally cannot stop the new client.
        self.assertTrue(pipeline.status()["active"])
        pipeline.submit(self.sample(0))
        self.assertEqual(pipeline.stop(new_session)["detections"], 0)
        self.assertEqual(len(self.runner.features), 1)

    def test_runner_failure_does_not_kill_worker_or_hang_disconnect(self):
        pipeline = self.pipeline("detection")
        self.runner.fail = True
        session = pipeline.start()
        pipeline.submit(self.sample(0))
        pipeline.submit(self.sample(1))
        result = pipeline.stop(session)
        self.assertEqual(result["failed_samples"], 1)
        self.assertIn("no classification", result["last_error"])
        self.assertTrue(pipeline.worker.is_alive())
        self.runner.fail = False
        session = pipeline.start()
        pipeline.submit(self.sample(0))
        pipeline.submit(self.sample(1))
        self.assertEqual(pipeline.stop(session)["last_prediction"], "circle")

    def test_websocket_client_protocol_and_http_status(self):
        app = service.build_app(service.Settings(mode="detection"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = service.uvicorn.Server(service.uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    self.fail("WebSocket server did not start")
                time.sleep(0.01)
            with connect(f"ws://127.0.0.1:{port}/ws/sensor") as client:
                self.assertEqual(json.loads(client.recv())["type"], "session_started")
                for index in range(2):
                    client.send(json.dumps({"type": "sample", "sequence": index,
                                            "client_time_ms": index * 16, "dx": 0, "dy": 0,
                                            "left_button": False}))
                client.send(json.dumps({"type": "disconnect"}))
                result = json.loads(client.recv())
                self.assertEqual(result["type"], "session_saved")
                self.assertEqual(result["last_prediction"], "circle")
            with urlopen(f"http://127.0.0.1:{port}/v1/status") as response:
                status = json.load(response)
            self.assertFalse(status["active"])
            self.assertEqual(status["detections"], 1)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
