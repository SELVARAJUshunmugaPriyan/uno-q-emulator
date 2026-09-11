#!/usr/bin/env python3
"""MPU-side Bridge test app.

This deliberately tests the MPU -> Bridge -> MCU path without pretending to run
keyword inference. The real Arduino app-bricks application can replace this file
after the EIM runner and model have been validated.
"""
import json
import os
import sys
import urllib.request


def bridge_call(method, *args):
    endpoint = os.getenv("MCU_URL", "http://mcu:9000") + "/bridge/call"
    data = json.dumps({"method": method, "args": list(args)}).encode()
    request = urllib.request.Request(
        endpoint, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else os.getenv("KEYWORD_LABEL", "hey_dragon")
    print(json.dumps(bridge_call("keyword_detected", label), indent=2))
