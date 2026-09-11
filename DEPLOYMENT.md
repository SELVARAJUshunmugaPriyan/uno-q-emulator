# Deployment and exercise workflow

This guide covers the two profile-based exercises in `uno-q-emulator`. The
emulator is a development/preflight environment; final validation belongs on
the Arduino UNO Q.

## Initialize

```bash
cd ~/uno-q-emulator
make init
make doctor
```

Keep keyword models in `models/keyword-detection/` and object models in
`models/object-detection/`. Select a specific model with `KEYWORD_MODEL` or
`OBJECT_MODEL` when more than one is present.

## Keyword exercise

After editing the course source in `~/app-bricks-examples`, copy its Python
entry point into `app/keyword-detection/python/main.py`:

```bash
cp ~/app-bricks-examples/inspirational/common/keyword-spotting/python/main.py \
   app/keyword-detection/python/main.py
make keyword-down
make keyword-up
make keyword-test-wav WAV='sample/hey_dragon.65d472ba.s2.wav'
```

Use `make keyword-info` to read the model labels and keep the Python label
exactly matched. The simulated MCU contract is `keyword_detected`.

## Object exercise

The object application runs on the MPU and serves its browser assets through
the Python `WebUI` brick:

```bash
make object-down
make object-import-check
make object-build
make object-up
make object-web-check
```

Open <http://127.0.0.1:7000/>. The browser can upload an image or capture a host
webcam frame with `getUserMedia()`. A Base64 JPEG is sent over Socket.IO and
processed by `ObjectDetection`. `main.py` must use:

```python
WebUI(assets_dir_path="/opt/uno-q/app/object-detection/assets")
```

## Deploying a model

```bash
cp ~/Downloads/my-model.eim models/object-detection/
OBJECT_MODEL='models/object-detection/my-model.eim' make object-up
```

Use the corresponding keyword directory and variable for keyword detection.
Inspect `/api/info` before changing labels, dimensions, thresholds, or sensor
assumptions.

## Release checklist

```bash
make doctor
make object-import-check
make object-web-check
make object-model-info
make keyword-info
make keyword-test-wav WAV='sample/hey_dragon.65d472ba.s2.wav'
```

Before board deployment, repeat testing with App Lab's runtime, physical
camera/microphone, Bridge transport, and STM32/LED hardware.
