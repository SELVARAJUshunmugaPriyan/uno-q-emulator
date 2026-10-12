# Live keyword detection

The Windows microphone client sends mono signed PCM16 audio to the MPU's HTTP
service. The MPU sends each complete input window to the same EIM runner used
by the other exercises. If the configured keyword reaches its threshold,
the MPU calls `keyword_detected` on the MCU simulator. No inference runs on
Windows, and live audio is not written to disk.

## Start the containers

From WSL, stop any other exercise using runner port 1340, then run:

```bash
make keyword-up
make keyword-info
make keyword-health
make keyword-status
make keyword-logs
```

`keyword-up` builds the MPU image, starts the runner and MCU, and waits for
their health checks before starting the Python service. The MPU image uses
Python 3.13 on Debian Bookworm, with Supervisor running both SSH and the HTTP
service. The entrypoint is `app/keyword-detection/python/main.py`.

The first model in `models/keyword-detection/` is selected by default. Set
`KEYWORD_MODEL='models/keyword-detection/my-model.eim'` to choose another.
`KEYWORD_LABEL` must exactly match a label from `make keyword-info` (default:
`hey_dragon`). `KEYWORD_THRESHOLD` defaults to `0.5`; the MCU notification
cooldown `KEYWORD_COOLDOWN_SECONDS` defaults to `2`.

## Windows microphone

In Windows PowerShell, from the repository root:

```powershell
py -3.11 -m pip install sounddevice
py -3.11 scripts/windows_microphone_client.py --list-devices
py -3.11 scripts/windows_microphone_client.py --endpoint http://<WSL-IP>:9200
```

Replace `<WSL-IP>` with the current WSL address. If localhost forwarding is
working, `http://127.0.0.1:9200` can also be used. Use `--device 1` (substitute
your device index) to select a microphone. Allow desktop microphone access in
Windows privacy settings. The device must support mono PCM16 at the model's
sample rate; unsupported formats produce a startup error rather than silently
changing the audio's timing.

- `s`: create a server session and start the microphone.
- `d`: stop the microphone, finish the current request, and close the session.
- `q` or Ctrl+C: stop and quit.

Sessions run until stopped by default. Add `--duration-seconds 60` for automatic
stop after approximately one minute; an in-flight HTTP request can take longer
to finish. Sampling rate and window length come from the model metadata.
Windows uses 50% overlapping windows to reduce boundary effects. At most two
complete windows wait for transmission; if inference falls behind, the oldest
pending window is dropped and counted. Audio discontinuities reset the input
buffer. Unsent and partial audio is discarded on disconnect.

The client prints predictions and MCU notification results. HTTP failures end
the session; press `s` to reconnect. One microphone client is accepted at a time.
After a crashed client, a new session can reclaim the service once 90 seconds
have passed without audio activity.

## HTTP contract

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service availability and audio format |
| GET | `/v1/status` | Active session, window count, last classification |
| POST | `/v1/sessions` | Start session; receive ID, rate, input window size |
| POST | `/v1/audio` | Classify one complete PCM window |
| DELETE | `/v1/sessions/{session_id}` | Close session and return summary |

An audio request contains `session_id`, monotonically increasing `sequence`,
integer `sample_rate`, and `features` (signed 16-bit integers). The feature
count must equal the model's input window length. Duplicate sequences return
409; invalid PCM/rates/window lengths return 422; concurrent inference returns
429; runner failure returns 502. No automatic inference-request retry is made.

The server listens on port 9200 (host override: `KEYWORD_PORT`). Runner and MCU
ports remain 1340 and 9000. Run one exercise at a time.

## Offline tests remain available

```bash
make keyword-test-wav WAV='sample/hey_dragon.65d472ba.s2.wav'
make keyword-test-samples
make keyword-bridge-test
```

These intentionally retain the original direct-to-runner WAV test path.
They do not exercise the live microphone service.
