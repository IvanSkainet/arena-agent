"""Operator autonomy controls (v4.97 YOLO + v4.102 posture cubes + runner).

Re-exports the YOLO switch (``is_yolo``/``set_yolo``/``yolo_status``) so the
existing ``from arena.autonomy import is_yolo`` imports keep working after this
module became a package, plus the posture model and the fail-closed runner.
"""
from arena.autonomy import posture, runner
from arena.autonomy.yolo import (
    YOLO_ACK_TOKEN, is_yolo, set_yolo, yolo_status,
)

__all__ = [
    "posture", "runner",
    "YOLO_ACK_TOKEN", "is_yolo", "set_yolo", "yolo_status",
]
