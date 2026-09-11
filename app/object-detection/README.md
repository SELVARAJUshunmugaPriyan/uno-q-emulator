# Object detection exercise

This MPU-only exercise runs an object-detection EIM model and provides a
browser interface through Arduino's `WebUI` brick. It supports image upload and
host-browser webcam capture.

## Run

```bash
make object-import-check
make object-up
make object-web-check
```

Open <http://127.0.0.1:7000/>. Choose **Use webcam**, allow permission, capture
a frame, and choose **Run Detection**. Drag-and-drop upload remains available.

## Data flow

```text
Browser upload/webcam -> Base64 JPEG over Socket.IO -> MPU WebUI callback
-> ObjectDetection brick -> EIM runner -> annotated image to browser
```

The browser camera is the host camera available to WSL; it is not a physical
UNO Q camera device.

## Files

- `python/main.py`: WebUI callback and model invocation.
- `assets/index.html`: page structure and controls.
- `assets/app.js`: upload, webcam, Socket.IO, and result handling.
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
