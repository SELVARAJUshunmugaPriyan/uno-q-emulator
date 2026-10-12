# Deployment and exercise workflow

This guide covers the profile-based exercises in `uno-q-emulator`. The
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

The keyword MPU runs the live HTTP service in
`app/keyword-detection/python/main.py`. Keep this entrypoint when using the
Windows microphone client:

```bash
make keyword-down
make keyword-up
make keyword-health
make keyword-test-wav WAV='sample/hey_dragon.65d472ba.s2.wav'
```

Use `make keyword-info` to read the model labels and keep the Python label
exactly matched. The simulated MCU contract is `keyword_detected`.

In Windows PowerShell, from the repository root:

```powershell
py -3.11 -m pip install sounddevice
py -3.11 scripts/windows_microphone_client.py --endpoint http://<WSL-IP>:9200
```

Press `s` to start capturing, `d` to disconnect, and `q` to quit. If the model
uses a different keyword label, set `KEYWORD_LABEL` when starting the services.
Both runner and MCU must be healthy before the keyword MPU starts.

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

Open <http://127.0.0.1:7000/> in the Windows browser. Choose **Use webcam** and
**Start live detection**. The browser sends successive Base64 JPEGs via HTTP
`POST /api/detect`, waiting for each result before sending another frame.
Single-frame capture and image upload are also available. `ObjectDetection`
performs inference via the runner. `main.py` must use:

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
