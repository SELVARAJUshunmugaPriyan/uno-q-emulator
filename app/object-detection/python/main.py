# SPDX-FileCopyrightText: Copyright (C) Arduino s.r.l. and/or its affiliated companies
#
# SPDX-License-Identifier: MPL-2.0

# Example app to perform object detection on an image sent from the UI, and send back the results with bounding boxes drawn on the image.

from arduino.app_utils import *
from arduino.app_bricks.web_ui import WebUI
from arduino.app_bricks.object_detection import ObjectDetection
from PIL import Image
import io
import base64
import time
import threading
from fastapi import HTTPException
from pydantic import BaseModel, Field

object_detection = ObjectDetection()
inference_lock = threading.Lock()


class DetectionRequest(BaseModel):
    image: str = Field(min_length=1, max_length=3_000_000)
    confidence: float = Field(default=0.5, ge=0, le=1)


def detect_image(data: DetectionRequest):
    """Shared REST/Socket.IO inference path. Bound concurrent model requests."""
    try:
        image_bytes = base64.b64decode(data.image, validate=True)
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width * source.height > 16_000_000:
                raise ValueError("Image exceeds 16 megapixels")
            pil_image = source.convert("RGB")
    except Exception as exc:
        raise HTTPException(400, "Invalid image or image too large") from exc
    if not inference_lock.acquire(blocking=False):
        raise HTTPException(429, "Detector busy; wait for the previous result")
    try:
        start = time.monotonic()
        results = object_detection.detect(pil_image, confidence=data.confidence)
        if results is None:
            raise HTTPException(502, "Model runner returned no result")
        annotated = object_detection.draw_bounding_boxes(pil_image, results)
        output = io.BytesIO()
        (annotated if annotated is not None else pil_image).save(output, format="PNG")
        return {
            "success": True,
            "result_image": base64.b64encode(output.getvalue()).decode("ascii"),
            "detection_count": len(results.get("detection", [])),
            "processing_time": f"{(time.monotonic() - start) * 1000:.2f} ms",
        }
    finally:
        inference_lock.release()

# Define a callback function to handle object detection requests from the UI.
def on_detect_objects(client_id, data):
    """Callback function to handle object detection requests."""
    try:
        response = detect_image(DetectionRequest(**data))
        ui.send_message('detection_result', response, room=client_id)

    except Exception as e:
        ui.send_message('detection_error', {'error': str(e)}, room=client_id)

ui = WebUI(
    addr="0.0.0.0",
    port=7000,
    assets_dir_path="/opt/uno-q/app/object-detection/assets",
)

ui.on_message('detect_objects', on_detect_objects)
ui.expose_api("POST", "/api/detect", detect_image)

if __name__ == "__main__":
    App.run()
