#!/usr/bin/env python3
"""Run one or more 16 kHz mono PCM WAV files through the EIM runner."""
import json
import os
import sys
import urllib.request
import wave
from pathlib import Path

RUNNER = "http://127.0.0.1:1340/api/features"
MCU = os.getenv("MCU_HOST_URL", "http://127.0.0.1:9000") + "/bridge/call"
KEYWORD = os.getenv("KEYWORD_LABEL", "hey_dragon")
THRESHOLD = float(os.getenv("KEYWORD_THRESHOLD", "0.5"))


def classify(path: Path):
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if (channels, rate, width) != (1, 16000, 2):
        raise ValueError(
            f"{path}: expected mono/16000Hz/16-bit PCM, "
            f"got channels={channels}, rate={rate}, width={width * 8}-bit"
        )
    values = [int.from_bytes(frames[i:i + 2], "little", signed=True)
              for i in range(0, len(frames), 2)]
    if len(values) != 16000:
        raise ValueError(f"{path}: expected 16000 samples, got {len(values)}")

    payload = json.dumps({"features": values}).encode()
    request = urllib.request.Request(
        RUNNER, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    print(f"\n{path.name}")
    print(json.dumps(result.get("result", result), indent=2))

    classification = result.get("result", {}).get("classification", {})
    score = float(classification.get(KEYWORD, 0))
    if score >= THRESHOLD:
        bridge_payload = json.dumps({
            "method": "keyword_detected", "args": [KEYWORD]
        }).encode()
        bridge_request = urllib.request.Request(
            MCU, data=bridge_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(bridge_request, timeout=5) as response:
            bridge_result = json.load(response)
        print(f"Bridge triggered ({KEYWORD}={score:.4f} >= {THRESHOLD:.2f})")
        print(json.dumps(bridge_result, indent=2))
    else:
        print(f"Bridge not triggered ({KEYWORD}={score:.4f} < {THRESHOLD:.2f})")
    return result


if __name__ == "__main__":
    paths = [Path(arg) for arg in sys.argv[1:]]
    if not paths:
        print("Usage: scripts/test-wav.py sample/*.wav", file=sys.stderr)
        raise SystemExit(2)
    try:
        for path in paths:
            classify(path)
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
