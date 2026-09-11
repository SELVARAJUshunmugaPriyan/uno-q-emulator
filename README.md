# UNO Q exercises emulator for WSL

This repository provides two independent Docker profiles for WSL 2:

- **Keyword detection**: ARM64 EIM runner → MPU Python app → simulated MCU/Bridge.
- **Object detection**: ARM64 EIM runner → MPU Python/WebUI app → browser UI.

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
capture a frame, and select **Run Detection**. Uploaded images remain supported.
The browser sends a Base64 image over Socket.IO; the MPU performs inference and
returns an annotated image. Stop the profile with `make object-down`.

The object runner API is exposed at `127.0.0.1:1340` and the WebUI/Socket.IO
endpoint at `127.0.0.1:7000`.

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
