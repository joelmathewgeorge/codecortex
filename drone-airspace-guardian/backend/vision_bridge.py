"""
YOLOv8n detector behind the aerial detection feed and the ground-risk monitor.

Loads the VisDrone fine-tune ml/weights/yolov8n_airspace.pt (person, car, van, truck, bus,
motor) when it exists, otherwise the COCO-pretrained ml/yolov8n.pt. Inference runs off the
simulation thread; the ground monitor calls `detect` for one camera frame at a time.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from config import ML_DIR

METRICS_FILE = ML_DIR / "weights" / "vision_metrics.json"
FINAL_WEIGHTS = ML_DIR / "weights" / "yolov8n_airspace.pt"
PRETRAINED = ML_DIR / "yolov8n.pt"


class Detector:
    def __init__(self) -> None:
        self.model = None
        self.name = "none"
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            self.error = f"ultralytics unavailable: {exc}"
            print(f"[vision] {self.error}; ground risk will use dataset labels")
            return
        for path, name in ((FINAL_WEIGHTS, "yolov8n-airspace"), (PRETRAINED, "yolov8n")):
            if not path.exists():
                continue
            try:
                self.model = YOLO(str(path))
                self.name = name
                print(f"[vision] loaded {path.name}")
                return
            except Exception as exc:
                self.error = str(exc)
        print("[vision] no YOLO weights found; ground risk will use dataset labels")

    def detect(self, path: Path, conf: float = 0.2, imgsz: int = 640) -> list[dict]:
        if self.model is None:
            return []
        with self._lock:
            result = self.model.predict(str(path), imgsz=imgsz, conf=conf, verbose=False)[0]
        names = result.names
        boxes = result.boxes
        out: list[dict] = []
        if boxes is None:
            return out
        for i in range(len(boxes)):
            label = str(names.get(int(boxes.cls[i]), int(boxes.cls[i])))
            out.append(
                {
                    "label": label,
                    "conf": round(float(boxes.conf[i]), 3),
                    "xyxy": [round(float(v), 1) for v in boxes.xyxy[i].tolist()],
                }
            )
        return out

    def metrics(self) -> dict | None:
        if not METRICS_FILE.exists():
            return None
        try:
            data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return {
            "model": data.get("model", self.name),
            "mAP50": data.get("mAP50"),
            "epochs": data.get("epochs"),
            "images": data.get("images"),
        }
