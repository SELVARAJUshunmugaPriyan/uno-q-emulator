# Gesture recognition exercise

The gesture application starts from `python/main.py` in both modes. Its
Python 3.13 base image and Arduino brick dependency match the other exercises.
Detection uses the `runner` service inherited from `compose.yaml`, including
the same ARM64 `ei-models-runner` image, `/models/custom` mount, HTTP health
check, and host port `127.0.0.1:1340` used by keyword/object detection.
Run one exercise at a time to avoid competing for that port.

The runner has the network alias `ei-motion-detection-runner`, which is the
address expected by the installed Arduino `MotionDetection` brick. The
gesture application waits for a healthy runner before starting in detection
mode. Setting a model-file environment variable on the Python service alone
does not start a runner.

## Detection

Place the model in `models/gesture-recognition/`, then run from the repository:

```bash
make gesture-up GESTURE_MODE=detection GESTURE_BUILD=--build
make gesture-model-info
make gesture-health
make gesture-status
make gesture-logs
```

`gesture-up` selects the first `.eim`. Override it with a repository-relative
path, for example `GESTURE_MODEL='models/gesture-recognition/my-model.eim'`.
Make translates that path into the runner's `/models/custom` path via
`EIM_MODEL`, following the other exercises. Quote filenames containing `#`.
No rebuild is needed just to select another model or mode. `gesture-runner`
can start the runner alone using the shared `scripts/run-model.sh` helper.

The Python worker maps mouse deltas using the same scales as CSV collection,
then sends complete input windows using the Arduino brick's public
`infer_from_features()` API. The model's metadata determines the window size;
the CSV setting of 200 samples does not control inference. The worker invokes
inference directly, so it does not need the separate `App.run()` loop used by
`accumulate_samples()`. Complete queued windows finish before disconnect is
acknowledged; incomplete detection windows are discarded and never reused by
the next session.

Prediction logs and `/v1/status` report the predicted label, confidence in
the range 0–1, full classification, inference count, and runner URL. Results
below `GESTURE_CONFIDENCE` (default `0.1`) report no predicted label. The model
must have three axes and a 16 ms sample interval to match this Windows client.
Keep `GESTURE_DETECTION_SCALE=1.0` for models trained on the collected CSVs;
the input units and scaling must match training.

## Collection

```bash
make gesture-up GESTURE_MODE=collection GESTURE_LABEL=idle
```

Make uses Compose's `--no-deps` for collection, so no model or runner is
required. An already-running runner is not stopped by changing modes. CSVs
are written in complete 200-sample windows plus the final partial window on
disconnect. Their host directory is `app/gesture-recognition/python/data`.

## Windows client and shutdown

The client and its protocol are unchanged:

```powershell
py -3.11 windows_mouse_client.py --endpoint ws://<WSL-IP>:9100/ws/sensor
```

Use `s` to connect, `d` to disconnect, and `q` to quit. The existing automatic
60-second session limit applies in both modes. For compatibility, the final
message is still `session_saved`, including in detection mode where no CSV
is written.

`make gesture-down` stops the gesture project, including its runner. Model
files and the bind-mounted CSV directory are preserved.

## Regression checks

The tests use the installed Arduino brick with a local fake runner HTTP API,
and exercise a real WebSocket connection. They do not run the `.eim` model:

```bash
docker run --rm --platform linux/arm64 --network none \
  -v "$PWD:/workspace:ro" --entrypoint python uno-q-gesture-gesture \
  /workspace/tests/test_gesture_service.py
```
