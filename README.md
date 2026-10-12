# UNO Q exercises emulator for WSL

This repository provides three independent Docker profiles for WSL 2:

- **Keyword detection**: Windows microphone → MPU HTTP app → ARM64 EIM runner → simulated MCU/Bridge. Offline WAV tests are also supported.
- **Object detection**: ARM64 EIM runner → MPU Python/WebUI app → browser UI.
- **Gesture recognition**: Windows mouse WebSocket client → MPU Python app → ARM64 EIM runner, or CSV collection.

Run one profile at a time. The runner executes the real Arduino `ei-models-runner`
image under ARM64 emulation; the remaining hardware boundaries are simulated.
See [INFO.md](INFO.md) for fidelity and limitations.

## Prerequisites

Use WSL 2 with Docker Desktop WSL integration enabled. Keep the repository in
the Linux filesystem, for example `~/uno-q-emulator`, rather than `/mnt/c`.

```bash
sudo apt update
sudo apt install -y make curl openssh-client
docker version
docker compose version
```

Initialize and diagnose the environment:

```bash
make init
make doctor
```

## Keyword detection

Put models in `models/keyword-detection/`. The first `.eim` is selected by
default; override it with `KEYWORD_MODEL`.

```bash
make keyword-up
make keyword-logs
make keyword-info
make keyword-test-wav WAV='sample/hey_dragon.65d472ba.s2.wav'
make keyword-bridge-test
make keyword-down
```

The keyword runner is exposed at `127.0.0.1:1340`, the simulated MCU at
`127.0.0.1:9000`, and MPU SSH at `127.0.0.1:2222` (development password:
`arduino`).

For live microphone input, leave the keyword services running and open
Windows PowerShell in the repository:

```powershell
py -3.11 -m pip install sounddevice
py -3.11 scripts/windows_microphone_client.py --endpoint http://<WSL-IP>:9200
```

Press `s` to start, `d` to stop, and `q` to quit. The microphone is inactive
until `s` is pressed. `make keyword-health` and `make keyword-status` query the
MPU HTTP service. See [keyword instructions](app/keyword-detection/README.md)
for device selection, model settings, and the HTTP contract.

## Object detection

Put models in `models/object-detection/`. Build and start the object profile:

```bash
make object-import-check
make object-build
make object-up
make object-web-check
make object-logs
```

Open <http://127.0.0.1:7000/>. Select **Use webcam**, allow browser permission,
then **Start live detection** for continuous inference. **Stop live detection**
pauses inference; **Stop webcam** also releases the camera. Single-frame capture
and uploaded images remain supported. The browser posts Base64 images to
`/api/detect`; the MPU returns annotated images. Only one frame is sent at a
time so slow inference does not build up a queue. Stop the profile with
`make object-down`.

The object runner API is exposed at `127.0.0.1:1340` and the WebUI/Socket.IO
endpoint at `127.0.0.1:7000`.

## Gesture recognition

Place the `.eim` in `models/gesture-recognition/`. Detection uses the same
runner image and healthy-runner startup dependency as object detection:

```bash
make gesture-up GESTURE_MODE=detection GESTURE_BUILD=--build
make gesture-model-info
make gesture-status
make gesture-logs
```

The Windows client continues to connect to `ws://<WSL-IP>:9100/ws/sensor`.
Use `make gesture-up GESTURE_MODE=collection GESTURE_LABEL=idle` for CSV
collection without starting a runner. Omit `GESTURE_BUILD=--build` when the
Python code and image dependencies have not changed.

See [the gesture instructions](app/gesture-recognition/README.md) for modes,
model selection, session handling, and verification.

## Model selection

Preserve the original `.eim` filename and place it in the matching exercise
directory:

```bash
KEYWORD_MODEL='models/keyword-detection/my-model.eim' make keyword-up
OBJECT_MODEL='models/object-detection/my-model.eim' make object-up
```

Inspect labels and input parameters with `make keyword-info` or
`make object-model-info`. Use the exact label returned by `/api/info`; filenames
do not determine labels.

## Cleanup and persistence

The `*-down` targets remove containers and networks. Runner state remains under
`runtime/arduino-keyword/` or `runtime/arduino-object/`; models remain under
`models/`.

See [DEPLOYMENT.md](DEPLOYMENT.md) for source/model changes and [INFO.md](INFO.md)
for the emulation boundary.
