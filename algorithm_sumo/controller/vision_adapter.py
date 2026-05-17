"""
Utilities for adapting vision/dataset JSON files to phase pressure input.
"""

import json
from pathlib import Path


# Map each road id to a traffic-light phase.
ROAD_TO_PHASE = {
    1: 0,  # E1
    2: 0,
    3: 1,  # E0.2
    4: 1,
    5: 2,  # E10
    6: 3,  # E11.1
}


class VisionDatasetReader:
    """
    Reads JSON files from a dataset directory in deterministic order.

    The class is intentionally tolerant to key naming differences in files.
    """

    def __init__(self, dataset_dir, loop=True):
        self.dataset_dir = Path(dataset_dir)
        self.loop = loop
        self.files = sorted(self.dataset_dir.glob("*.json"))
        self.index = 0

        if not self.dataset_dir.exists():
            raise FileNotFoundError(f"Dataset directory not found: {self.dataset_dir}")
        if not self.files:
            raise FileNotFoundError(f"No JSON files found in: {self.dataset_dir}")

    def next_sample(self):
        if not self.files:
            return None

        if self.index >= len(self.files):
            if not self.loop:
                return None
            self.index = 0

        file_path = self.files[self.index]
        self.index += 1

        with file_path.open("r", encoding="utf-8") as f:
            return json.load(f)


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _to_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_road_item(raw_road):
    road_id = raw_road.get("road_id", raw_road.get("roadId"))
    if road_id is None:
        return None

    try:
        road_id = int(road_id)
    except (TypeError, ValueError):
        return None

    congestion = raw_road.get("congestion_score", raw_road.get("congestionScore", 0))
    has_ambulance = raw_road.get("has_ambulance", raw_road.get("ambulance", False))

    return {
        "road_id": road_id,
        "congestion_score": _to_number(congestion, default=0),
        "has_ambulance": _to_bool(has_ambulance),
    }


def normalize_vision_json(raw_json):
    """
    Converts different JSON naming styles into a canonical structure:
    {
      "roads": [
        {"road_id": int, "congestion_score": float, "has_ambulance": bool}
      ]
    }
    """
    roads = raw_json.get("roads", [])
    normalized_roads = []

    for raw_road in roads:
        if not isinstance(raw_road, dict):
            continue
        item = _normalize_road_item(raw_road)
        if item is not None:
            normalized_roads.append(item)

    return {"roads": normalized_roads}


def compute_phase_pressure(vision_json):
    """
    Converts vision JSON into phase pressure dict.

    Returns:
        phase_pressure: {0: x, 1: y, 2: z, 3: t}
        emergency_phase: int | None
    """
    normalized = normalize_vision_json(vision_json)

    phase_pressure = {0: 0, 1: 0, 2: 0, 3: 0}
    emergency_phase = None

    for road in normalized["roads"]:
        road_id = road["road_id"]
        congestion = road["congestion_score"]
        has_ambulance = road["has_ambulance"]

        if road_id not in ROAD_TO_PHASE:
            continue

        phase = ROAD_TO_PHASE[road_id]
        weight = 2.5 if has_ambulance else 1.0
        phase_pressure[phase] += congestion * weight

        if has_ambulance:
            emergency_phase = phase

    return phase_pressure, emergency_phase
