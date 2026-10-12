# Object detection exercise

This MPU-only exercise runs an object-detection EIM model and provides a
browser interface through Arduino's `WebUI` brick. It supports image upload and
host-browser webcam capture, including continuous live detection.

## Run

```bash
make object-import-check
make object-build
make object-up
make object-web-check
```

Open <http://127.0.0.1:7000/> in Windows. Choose **Use webcam**, allow permission,
then **Start live detection**. Each completed result schedules the next frame;
there is no fixed FPS promise. Live frames are resized to at most 640 pixels
wide and encoded as JPEG. **Stop live detection** stops sending frames and
ignores late results; **Stop webcam** also releases the camera. An in-flight
request may finish on the server after stopping. Restart is available once
that request finishes (or the 30-second client timeout expires).

Single-frame capture with **Capture frame** / **Run Detection** and
drag-and-drop upload remain available. Use localhost for browser camera access.

## Data flow

```text
Browser upload/webcam -> Base64 image HTTP POST /api/detect -> MPU WebUI API
-> ObjectDetection brick -> EIM runner -> annotated image to browser
```

The browser camera is the host camera available to WSL; it is not a physical
UNO Q camera device.

## HTTP API

`POST http://127.0.0.1:7000/api/detect` accepts JSON:

```json
{"image": "<base64 JPEG or PNG without a data-URL prefix>", "confidence": 0.5}
```

It returns `success`, `result_image` (Base64 PNG), `detection_count`, and
`processing_time`. Invalid images return HTTP 400, invalid fields return 422,
and a busy detector returns 429. The old Socket.IO `detect_objects` event is
still supported; its response is addressed to the requesting client.

## Files

- `python/main.py`: WebUI callback and model invocation.
- `assets/index.html`: page structure and controls.
- `assets/app.js`: upload, webcam, live HTTP detection, and result handling.
- `assets/style.css`: layout and camera styling.
- `app.yaml`: App Lab metadata and brick declarations.

`main.py` must point WebUI at the mounted assets directory:

```python
ui = WebUI(
    addr="0.0.0.0",
    port=7000,
    assets_dir_path="/opt/uno-q/app/object-detection/assets",
)
```

Use [DEPLOYMENT.md](../../DEPLOYMENT.md) for deployment and [INFO.md](../../INFO.md)
for the emulator boundary.
