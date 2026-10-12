# Emulation fidelity and limitations

This project is software-in-the-loop validation for keyword and object
detection exercises. It uses Arduino's ARM64 EIM runner to execute the supplied
model, but it is not a cycle-accurate UNO Q, STM32, camera, microphone, or LED
emulator.

| Component | Fidelity | Boundary |
|---|---|---|
| `.eim` loading/inference | High | Real Arduino runner and model artifact |
| Model metadata/labels | High | Runner `/api/info` response |
| Keyword WAV inference | High | Same PCM contract, offline input |
| Live keyword input | Medium | Windows microphone, overlapping PCM windows over HTTP |
| Object image inference | High | Same runner and image contract |
| ARM64 execution | Medium | Docker/QEMU, not board silicon |
| Python/App Bricks logic | Medium–High | Container runtime and application code |
| Browser/WebUI messaging | Medium–High | FastAPI REST; legacy Socket.IO also available |
| Browser webcam capture | Medium | Host browser camera, not UNO Q camera |
| MPU hardware/software stack | Low | Debian container replaces board image |
| Bridge/MCU transport | Low | HTTP simulator replaces Router Bridge/STM32 |
| LED matrix output | None | Log/text representation only |
| Real-time behavior | Low | No board scheduling or latency measurement |

## Keyword limitations

WAV tests bypass live ALSA/PipeWire capture, USB permissions, clock drift,
rolling windows, buffering, debounce, and callback scheduling. The separate
Windows microphone client adds host audio capture with 50% overlapping model
windows, a bounded queue, and start/stop controls. The MPU service applies a
configurable notification cooldown. This does not validate the UNO Q's audio
drivers or timing. The MCU endpoint and LED heart remain simulators; no STM32
sketch or physical LED library runs.

## Object limitations

The browser uploads or captures an image, sends it as Base64 via HTTP, and
the MPU returns an annotated image. Live mode repeatedly captures frames with
one inference request in flight. Webcam mode uses the Windows/WSL browser
camera. Frame rate depends on inference and network latency. It does not
validate UNO Q camera drivers, V4L2 discovery, exposure,
autofocus, USB bandwidth, or board-camera latency.

## Validated here

- ARM64 runner/model compatibility and model metadata.
- Keyword WAV classification and object image inference.
- Python-to-WebUI and Python-to-Bridge message contracts.
- Browser webcam-to-inference flow.
- Repeatable Compose profile startup.

Live-client regression tests use simulated inference responses and camera/audio
input. Actual Windows microphone/webcam behavior and model accuracy still need
hardware testing after deployment.

## Required on a real UNO Q

- App Lab's production Python runtime and service manager.
- Physical camera/microphone capture and permissions.
- Router Bridge, STM32 firmware, LED hardware, and timing.
- Boot, thermal, recovery, long-running, and deployment reliability.

Treat this emulator as a repeatable preflight tool, not a replacement for
board acceptance testing.
