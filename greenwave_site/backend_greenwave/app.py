import time
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import traceback
import xml.etree.ElementTree as ET
import zipfile
from werkzeug.utils import secure_filename

import requests
import sumolib
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from db import (
    get_connection,
    save_region,
    upsert_region,
    delete_region,
    create_table,
    get_transaction_dashboard_cards,
)


BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "osm_cache.json"
LAST_MODS_FILE = BASE_DIR / "last_mods.json"
OSM_SOURCE_DIR = BASE_DIR / "osm_sources"
SUMO_HOME = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo"))
RANDOM_TRIPS = SUMO_HOME / "tools" / "randomTrips.py"
PROJECT_ROOT = BASE_DIR.parent.parent
RUNTIME_ASSETS_ROOT = PROJECT_ROOT / "runtime_assets"
SUMO_EXPORTS_DIR = RUNTIME_ASSETS_ROOT / "sumo_exports"
LAST_EXPORT_FILE = RUNTIME_ASSETS_ROOT / "last_sumo_export.json"
LAST_PROJECT_ARCHIVE = RUNTIME_ASSETS_ROOT / "last_sumo_project.zip"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
]


for directory in (OSM_SOURCE_DIR, SUMO_EXPORTS_DIR):
    directory.mkdir(exist_ok=True)


def load_json(path, fallback):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return fallback


CACHE = load_json(CACHE_FILE, {})

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)
create_table()

PROCESS_LOCK = threading.Lock()
SYSTEM_PROCESSES = {
    "transaction_runner": None,
}
ACTIVE_REGION_ID = None
GREENWAVE_API_DIR = PROJECT_ROOT / "GreenWaveAPI" / "GreewnWaveAPI"
CAMERA_TESTS_DIR = PROJECT_ROOT / "camera_tests"
ALGORITHM_SUMO_DIR = PROJECT_ROOT / "algorithm_sumo"
TRANSACTION_ASSETS_DIR = PROJECT_ROOT / "runtime_assets" / "transactions"
TRANSACTION_CONFIG_DIR = PROJECT_ROOT / "runtime_assets" / "transaction_configs"
for directory in (RUNTIME_ASSETS_ROOT, SUMO_EXPORTS_DIR, TRANSACTION_ASSETS_DIR, TRANSACTION_CONFIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _is_running(proc):
    return proc is not None and proc.poll() is None


def _start_process(name, command, cwd):
    with PROCESS_LOCK:
        existing = SYSTEM_PROCESSES.get(name)
        if _is_running(existing):
            return False, f"{name} is already running"
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        SYSTEM_PROCESSES[name] = proc
        return True, f"{name} started (pid={proc.pid})"


def _stop_process(name):
    with PROCESS_LOCK:
        proc = SYSTEM_PROCESSES.get(name)
        if not _is_running(proc):
            SYSTEM_PROCESSES[name] = None
            return False, f"{name} is not running"
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        SYSTEM_PROCESSES[name] = None
        return True, f"{name} stopped"


def _process_status():
    global ACTIVE_REGION_ID
    with PROCESS_LOCK:
        status = {}
        for name, proc in SYSTEM_PROCESSES.items():
            running = _is_running(proc)
            status[name] = {
                "running": running,
                "pid": proc.pid if running else None,
            }
        runner_running = status.get("transaction_runner", {}).get("running", False)
        status["greenwave_api"] = {"running": runner_running, "pid": None}
        status["camera_detection"] = {"running": runner_running, "pid": None}
        status["algorithm_sumo"] = {"running": runner_running, "pid": None}
        status["active_region_id"] = ACTIVE_REGION_ID
        return status


def _transaction_paths(region_id):
    rid = str(int(region_id))
    return {
        "root": TRANSACTION_ASSETS_DIR / rid,
        "sumo": TRANSACTION_ASSETS_DIR / rid / "sumo",
        "camera": TRANSACTION_ASSETS_DIR / rid / "camera",
        "config": TRANSACTION_CONFIG_DIR / f"{rid}.json",
    }


def _find_sumocfg_path(sumo_root: Path):
    direct = sumo_root / "scenario.sumocfg"
    if direct.exists():
        return direct
    matches = sorted(sumo_root.rglob("*.sumocfg"))
    return matches[0] if matches else direct


def _camera_config_from_editor_state(editor_state, region_id, region_name, region_address, bounds):
    cameras = []
    setup = (editor_state or {}).get("cameraSetup") if isinstance(editor_state, dict) else None
    raw_cameras = (setup or {}).get("cameras") if isinstance(setup, dict) else None
    if isinstance(raw_cameras, list):
        for cam in raw_cameras:
            if not isinstance(cam, dict):
                continue
            cameras.append(
                {
                    "id": cam.get("id"),
                    "name": cam.get("name") or f"Camera {len(cameras) + 1}",
                    "sourceType": cam.get("sourceType") or "file",
                    "source": cam.get("sourceValue") or cam.get("source") or "",
                    "linkedRoads": cam.get("linkedRoads") or [],
                    "frameSize": {
                        "width": cam.get("frameWidth"),
                        "height": cam.get("frameHeight"),
                    },
                    "roadDrawings": cam.get("roadDrawings") or {},
                    "roadDrawingsNormalized": cam.get("roadDrawingsNormalized") or {},
                    "roads": list((cam.get("roadDrawings") or {}).values()),
                    "roads_json_format": list((cam.get("roadDrawings") or {}).values()),
                }
            )
    return {
        "region_id": int(region_id),
        "region_name": region_name or f"Region {region_id}",
        "region_address": region_address or "",
        "bounds": bounds,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "cameras": cameras,
        "notes": "Generated from editor state.",
    }


def _write_transaction_config(region_id, project, bounds, region_name, region_address, editor_state=None):
    paths = _transaction_paths(region_id)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["sumo"].mkdir(parents=True, exist_ok=True)
    paths["camera"].mkdir(parents=True, exist_ok=True)

    project_dir = Path(project["projectDir"])
    if paths["sumo"].exists():
        shutil.rmtree(paths["sumo"])
    shutil.copytree(project_dir, paths["sumo"])

    camera_config = _camera_config_from_editor_state(
        editor_state, region_id, region_name, region_address, bounds
    )
    save_json(paths["camera"] / "camera_config.json", camera_config)
    sumocfg_path = _find_sumocfg_path(paths["sumo"])

    config = {
        "transaction_id": int(region_id),
        "region_name": region_name or f"Region {region_id}",
        "sumo_cfg_path": str(sumocfg_path),
        "camera_config_path": str(paths["camera"] / "camera_config.json"),
        "editor_state_path": str(paths["root"] / "editor_state.json"),
        "camera_video": "0",
        "camera_model": "yolov8s.pt",
        "junction_id": str(region_id),
        "vision_api_url_template": "http://localhost:5185/api/Sumo/traffic/{junction_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(paths["config"], config)
    return config


def _write_transaction_stub_config(region_id, bounds, region_name, region_address, reason, editor_state=None):
    paths = _transaction_paths(region_id)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["sumo"].mkdir(parents=True, exist_ok=True)
    paths["camera"].mkdir(parents=True, exist_ok=True)

    camera_config = _camera_config_from_editor_state(
        editor_state, region_id, region_name, region_address, bounds
    )
    camera_config["notes"] = "SUMO export failed for this transaction. Camera config is still saved."
    save_json(paths["camera"] / "camera_config.json", camera_config)

    config = {
        "transaction_id": int(region_id),
        "region_name": region_name or f"Region {region_id}",
        "sumo_cfg_path": "",
        "camera_config_path": str(paths["camera"] / "camera_config.json"),
        "editor_state_path": str(paths["root"] / "editor_state.json"),
        "camera_video": "0",
        "camera_model": "yolov8s.pt",
        "junction_id": str(region_id),
        "vision_api_url_template": "http://localhost:5185/api/Sumo/traffic/{junction_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete",
        "reason": str(reason),
    }
    save_json(paths["config"], config)
    return config


def _build_transaction_bundle(region_id):
    rid = int(region_id)
    paths = _transaction_paths(rid)
    bundle_dir = PROJECT_ROOT / "runtime_assets"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"transaction_{rid}.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if paths["root"].exists():
            for file_path in paths["root"].rglob("*"):
                if file_path.is_file():
                    arc = Path(str(rid)) / file_path.relative_to(paths["root"])
                    zf.write(file_path, arcname=str(arc))
        if paths["config"].exists():
            zf.write(paths["config"], arcname=str(Path(str(rid)) / "transaction_config.json"))
    return bundle_path


def _save_editor_state(region_id, editor_state):
    paths = _transaction_paths(region_id)
    paths["root"].mkdir(parents=True, exist_ok=True)
    save_json(paths["root"] / "editor_state.json", editor_state or {})


def _load_editor_state(region_id):
    paths = _transaction_paths(region_id)
    state_path = paths["root"] / "editor_state.json"
    if not state_path.exists():
        return None
    return load_json(state_path, None)

def make_key(min_lat, min_lon, max_lat, max_lon):
    return f"{round(min_lat, 5)}_{round(min_lon, 5)}_{round(max_lat, 5)}_{round(max_lon, 5)}"


def save_json(path, payload):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def parse_experiment_id(intersection_id):
    digits = "".join(ch for ch in str(intersection_id) if ch.isdigit())
    if not digits:
        raise ValueError("intersection_id must include numeric digits (example: INT-003)")
    return int(digits)


def _find_existing_region_id_by_bounds(bounds):
    if not isinstance(bounds, dict):
        return None
    try:
        min_lat = float(bounds["min_lat"])
        min_lon = float(bounds["min_lon"])
        max_lat = float(bounds["max_lat"])
        max_lon = float(bounds["max_lon"])
    except Exception:
        return None

    eps = 1e-7
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id
            FROM regions
            WHERE ABS(min_lat - %s) <= %s
              AND ABS(min_lon - %s) <= %s
              AND ABS(max_lat - %s) <= %s
              AND ABS(max_lon - %s) <= %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (min_lat, eps, min_lon, eps, max_lat, eps, max_lon, eps),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _resolve_region_display_name(region_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        identity_table = "region_identity"
        try:
            cursor.execute("SELECT to_regclass('public.regions_identity')")
            has_plural_identity = cursor.fetchone()[0] is not None
            if has_plural_identity:
                identity_table = "regions_identity"
        except Exception:
            identity_table = "region_identity"

        cursor.execute(
            f"""
            SELECT COALESCE(ri.name, r.name, %s)
            FROM regions r
            LEFT JOIN {identity_table} ri ON ri.region_id = r.id
            WHERE r.id = %s
            LIMIT 1
            """,
            (f"Region {int(region_id)}", int(region_id)),
        )
        row = cursor.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    finally:
        conn.close()
    return f"Region {int(region_id)}"


def _density_bias(level):
    lv = str(level or "").upper()
    if lv == "LOW":
        return 0.20
    if lv == "MEDIUM":
        return 0.55
    if lv == "HIGH":
        return 0.85
    return 0.50


def _congestion_score_0_100(queue_length, waiting_like_value, density_level):
    """
    Normalize mixed runtime metrics to a stable 0..100 congestion score.
    queue_length and waiting_like_value can be in different raw scales across runs,
    so we clamp each contribution before blending.
    """
    q = max(0.0, float(queue_length or 0.0))
    w = max(0.0, float(waiting_like_value or 0.0))
    q_norm = min(1.0, q / 40.0)
    w_norm = min(1.0, w / 60.0)
    d_norm = _density_bias(density_level)
    score = (0.60 * q_norm + 0.25 * w_norm + 0.15 * d_norm) * 100.0
    return max(0.0, min(100.0, score))


def _latest_vision_avg_congestion(junction_id):
    """
    Read latest GreenWaveAPI traffic log for this junction and return
    average congestion score in 0..100. Returns None if unavailable.
    """
    try:
        jid = int(junction_id)
    except Exception:
        return None

    traffic_dir = GREENWAVE_API_DIR / "TrafficLogs" / f"Junction_{jid}"
    if not traffic_dir.exists():
        return None

    files = [p for p in traffic_dir.glob("*.json") if p.is_file()]
    if not files:
        return None

    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None

    roads = payload.get("Roads") if isinstance(payload, dict) else None
    if not isinstance(roads, list) or not roads:
        return None

    scores = []
    for row in roads:
        if not isinstance(row, dict):
            continue
        try:
            val = float(row.get("CongestionScore", 0))
        except Exception:
            continue
        scores.append(max(0.0, min(100.0, val)))

    if not scores:
        return None
    return sum(scores) / len(scores)


def _upsert_congestion_minute(junction_id: int, avg_congestion: float, road_sample_count: int):
    """
    Persist minute-level congestion aggregates into camera_congestion_hourly table.
    Note: We intentionally use minute buckets (DATE_TRUNC('minute')) so dashboard
    can show near-real-time history while keeping one row per minute.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO camera_congestion_hourly
                    (
                        junction_id,
                        hour_ts,
                        avg_congestion,
                        min_congestion,
                        max_congestion,
                        sample_count,
                        road_sample_count,
                        updated_at
                    )
                    VALUES
                    (
                        %s,
                        DATE_TRUNC('minute', NOW()),
                        %s,
                        %s,
                        %s,
                        1,
                        %s,
                        NOW()
                    )
                    ON CONFLICT (junction_id, hour_ts) DO UPDATE SET
                        avg_congestion =
                            (
                                (camera_congestion_hourly.avg_congestion * camera_congestion_hourly.sample_count)
                                + EXCLUDED.avg_congestion
                            ) / (camera_congestion_hourly.sample_count + 1),
                        min_congestion = LEAST(camera_congestion_hourly.min_congestion, EXCLUDED.min_congestion),
                        max_congestion = GREATEST(camera_congestion_hourly.max_congestion, EXCLUDED.max_congestion),
                        sample_count = camera_congestion_hourly.sample_count + 1,
                        road_sample_count = GREATEST(camera_congestion_hourly.road_sample_count, EXCLUDED.road_sample_count),
                        updated_at = NOW()
                    """,
                    (
                        int(junction_id),
                        float(avg_congestion),
                        float(avg_congestion),
                        float(avg_congestion),
                        int(max(0, road_sample_count)),
                    ),
                )
    except Exception:
        # Non-fatal: live dashboard should continue even if aggregation write fails.
        pass


def _get_latest_camera_avg_from_db(junction_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT avg_congestion
                    FROM camera_congestion_hourly
                    WHERE junction_id = %s
                    ORDER BY hour_ts DESC
                    LIMIT 1
                    """,
                    (int(junction_id),),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return float(row[0])
    except Exception:
        return None
    return None


def _get_live_camera_improvement_percent(junction_id: int):
    """
    Compute live improvement from camera DB only:
    baseline = earliest minute in the recent window
    current  = latest minute in the recent window
    improvement% = (baseline - current) / baseline * 100
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT hour_ts, avg_congestion
                    FROM camera_congestion_hourly
                    WHERE junction_id = %s
                      AND hour_ts >= NOW() - INTERVAL '30 minute'
                    ORDER BY hour_ts ASC
                    """,
                    (int(junction_id),),
                )
                rows = cursor.fetchall()
                if not rows or len(rows) < 2:
                    return None
                baseline = float(rows[0][1] or 0.0)
                current = float(rows[-1][1] or 0.0)
                if baseline <= 0:
                    return None
                value = ((baseline - current) / baseline) * 100.0
                return max(-100.0, min(100.0, value))
    except Exception:
        return None
    return None


def _get_today_camera_avg(junction_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT AVG(avg_congestion)::float
                    FROM camera_congestion_hourly
                    WHERE junction_id = %s
                      AND DATE(hour_ts) = CURRENT_DATE
                    """,
                    (int(junction_id),),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return float(row[0])
    except Exception:
        return None
    return None


def resolve_address_from_bounds(bounds):
    center_lat = (float(bounds["min_lat"]) + float(bounds["max_lat"])) / 2.0
    center_lon = (float(bounds["min_lon"]) + float(bounds["max_lon"])) / 2.0
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": center_lat, "lon": center_lon},
            headers={"User-Agent": "Greenwave-TrafficProject/1.0 (contact: zcorumluoglu3@gmail.com)"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        address = payload.get("display_name")
        if address:
            return address
    except Exception:
        pass
    return "Address not found"


def run_command(command, cwd=None):
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(map(str, command))}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def build_overpass_query(min_lat, min_lon, max_lat, max_lon):
    return f"""
    [out:xml][timeout:60];
    (
        way["highway"~"primary|secondary|tertiary|residential"]({min_lat},{min_lon},{max_lat},{max_lon});    );
    (._;>;);
    out body;
    """


def fetch_osm_xml(min_lat, min_lon, max_lat, max_lon):

    query = build_overpass_query(min_lat, min_lon, max_lat, max_lon)

    for url in OVERPASS_URLS:
        for i in range(3):  # retry per URL
            try:
                response = requests.post(
                    url,
                    data={"data": query},   # ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ KRÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°TÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°K FIX BURASI
                    headers={
                        "User-Agent": "Greenwave-TrafficProject/1.0 (contact: zcorumluoglu3@gmail.com)"
                    },
                    timeout=120
                )

                response.raise_for_status()

                if len(response.text) > 500:
                    return response.text

            except Exception as exc:
                print(f"OVERPASS ERROR {url} attempt {i+1}:", exc)
                time.sleep(2)

    return None


def osm_source_path(cache_key):
    return OSM_SOURCE_DIR / f"{cache_key}.osm.xml"


def ensure_osm_source(cache_key, bounds):
    path = osm_source_path(cache_key)
    if path.exists():
        return path

    osm_xml = fetch_osm_xml(bounds["min_lat"], bounds["min_lon"], bounds["max_lat"], bounds["max_lon"])
    if not osm_xml:
        raise RuntimeError("OSM source could not be fetched.")

    path.write_text(osm_xml, encoding="utf-8")
    return path


def build_sumo_preview(osm_path):
    tmp_path = BASE_DIR / "_preview_build"
    tmp_path.mkdir(exist_ok=True)
    net_path = tmp_path / f"{osm_path.stem}.net.xml"

    run_command(["netconvert", "--osm-files", str(osm_path), "-o", str(net_path)])
    net = sumolib.net.readNet(str(net_path))
    net_tree = ET.parse(net_path)
    location = net_tree.getroot().find("location")

    lon_min, lat_min, lon_max, lat_max = map(float, location.get("origBoundary").split(","))
    x_min, y_min, x_max, y_max = map(float, location.get("convBoundary").split(","))

    def xy_to_latlon(x, y):
        lon_ratio = 0 if x_max == x_min else (x - x_min) / (x_max - x_min)
        lat_ratio = 0 if y_max == y_min else (y - y_min) / (y_max - y_min)
        lon = lon_min + lon_ratio * (lon_max - lon_min)
        lat = lat_min + lat_ratio * (lat_max - lat_min)
        return [lat, lon]

    links = []
    for edge in net.getEdges():
        if edge.getFunction():
            continue
        if not edge.allows("passenger"):
            continue

        shape = []
        for x, y in edge.getShape():
            shape.append(xy_to_latlon(x, y))

        if len(shape) < 2:
            continue

        links.append(
            {
                "id": edge.getID(),
                "coords": shape,
                "lanes": edge.getLaneNumber(),
                "name": edge.getName() or "",
                "highway": edge.getType() or "",
                "startNode": edge.getFromNode().getID(),
                "endNode": edge.getToNode().getID(),
            }
        )

    return links


def get_or_create_network(min_lat, min_lon, max_lat, max_lon):
    key = make_key(min_lat, min_lon, max_lat, max_lon)
    cached = CACHE.get(key)

    if isinstance(cached, dict) and cached.get("source") == "sumo-preview" and cached.get("links"):
        return cached, key

    bounds = {
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
    }
    osm_path = ensure_osm_source(key, bounds)
    links = build_sumo_preview(osm_path)

    network = {
        "links": links,
        "source": "sumo-preview",
        "bbox": bounds,
        "osmPath": str(osm_path),
    }
    CACHE[key] = network
    save_json(CACHE_FILE, CACHE)
    return network, key


def parse_shape(shape_text):
    return [tuple(map(float, pair.split(","))) for pair in shape_text.split()] if shape_text else []


def format_shape(points):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def point_distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def interpolate(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def slice_polyline(points, start_ratio, end_ratio):
    if len(points) < 2:
        return points

    total = sum(point_distance(points[i], points[i + 1]) for i in range(len(points) - 1))
    if total == 0:
        return points

    start_dist = total * start_ratio
    end_dist = total * end_ratio

    sliced = []
    traversed = 0.0

    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        seg_len = point_distance(p1, p2)
        seg_start = traversed
        seg_end = traversed + seg_len

        if seg_end < start_dist:
            traversed = seg_end
            continue
        if seg_start > end_dist:
            break

        if start_dist >= seg_start and start_dist <= seg_end:
            t = 0 if seg_len == 0 else (start_dist - seg_start) / seg_len
            sliced.append(interpolate(p1, p2, t))
        elif not sliced:
            sliced.append(p1)

        if end_dist >= seg_start and end_dist <= seg_end:
            t = 0 if seg_len == 0 else (end_dist - seg_start) / seg_len
            sliced.append(interpolate(p1, p2, t))
            break
        else:
            sliced.append(p2)

        traversed = seg_end

    if len(sliced) == 1:
        sliced.append(sliced[0])
    return sliced


def clamp_lane_attr(connection, attr_name, lane_count):
    if lane_count < 1:
        lane_count = 1
    value = connection.get(attr_name)
    if value is None:
        return
    try:
        number = int(value)
    except Exception:
        connection.attrib.pop(attr_name, None)
        return
    connection.set(attr_name, str(max(0, min(number, lane_count - 1))))


def edge_points(edge_element, node_map):
    shape = parse_shape(edge_element.get("shape", ""))
    if len(shape) >= 2:
        return shape
    return [
        node_map[edge_element.get("from")],
        node_map[edge_element.get("to")],
    ]


def lane_for_interval(default_lanes, segment_edits, start_ratio, end_ratio):
    midpoint = (start_ratio + end_ratio) / 2
    for segment in segment_edits:
        if segment["fromRatio"] <= midpoint <= segment["toRatio"]:
            return max(1, int(segment["lanes"]))
    return max(1, int(default_lanes))


def apply_modifications_to_plain(node_path, edge_path, connection_path, modifications, forced_traffic_lights=None):
    node_tree = ET.parse(node_path)
    edge_tree = ET.parse(edge_path)
    connection_tree = ET.parse(connection_path)

    node_root = node_tree.getroot()
    edge_root = edge_tree.getroot()
    connection_root = connection_tree.getroot()

    node_map = {
        node.get("id"): (float(node.get("x")), float(node.get("y")))
        for node in node_root.findall("node")
    }
    edge_elements = {edge.get("id"): edge for edge in edge_root.findall("edge")}
    modifications_by_id = {item["id"]: item for item in modifications}
    removed_edge_ids = {item["id"] for item in modifications if item.get("removed")}
    split_info = {}
    forced_tls_ids = set(forced_traffic_lights or [])

    for edge_id, edge_element in list(edge_elements.items()):
        modification = modifications_by_id.get(edge_id)
        if edge_id in removed_edge_ids:
            edge_root.remove(edge_element)
            continue

        if not modification:
            split_info[edge_id] = {"parts": [edge_id], "first": edge_id, "last": edge_id}
            continue

        default_lanes = int(modification.get("lanes") or edge_element.get("numLanes", "1"))

        trim = modification.get("trim") if isinstance(modification, dict) else None
        keep_from = 0.0
        keep_to = 1.0
        if isinstance(trim, dict):
            try:
                keep_from = max(0.0, min(1.0, float(trim.get("fromRatio", 0.0))))
                keep_to = max(0.0, min(1.0, float(trim.get("toRatio", 1.0))))
            except Exception:
                keep_from = 0.0
                keep_to = 1.0
            if keep_from > keep_to:
                keep_from, keep_to = keep_to, keep_from
            if abs(keep_to - keep_from) < 1e-6:
                keep_from = 0.0
                keep_to = 1.0

        segment_edits = sorted(
            [
                {
                    **segment,
                    "fromRatio": max(0.0, min(1.0, float(segment["fromRatio"]))),
                    "toRatio": max(0.0, min(1.0, float(segment["toRatio"]))),
                }
                for segment in modification.get("segmentEdits", [])
            ],
            key=lambda item: item["fromRatio"],
        )

        if not segment_edits and keep_from <= 1e-6 and keep_to >= 1.0 - 1e-6:
            edge_element.set("numLanes", str(max(1, default_lanes)))
            split_info[edge_id] = {"parts": [edge_id], "first": edge_id, "last": edge_id}
            continue

        boundaries = [0.0, 1.0, keep_from, keep_to]
        for segment in segment_edits:
            boundaries.extend([segment["fromRatio"], segment["toRatio"]])
        boundaries = sorted(boundaries)

        deduped = []
        for value in boundaries:
            if not deduped or abs(value - deduped[-1]) > 1e-6:
                deduped.append(value)

        if len(deduped) <= 2 and keep_from <= 1e-6 and keep_to >= 1.0 - 1e-6:
            edge_element.set("numLanes", str(max(1, default_lanes)))
            split_info[edge_id] = {"parts": [edge_id], "first": edge_id, "last": edge_id}
            continue

        points = edge_points(edge_element, node_map)
        new_node_ids = [edge_element.get("from")]
        edge_root.remove(edge_element)
        part_ids = []

        for boundary_index, ratio in enumerate(deduped[1:-1], start=1):
            point = slice_polyline(points, ratio, ratio)[0]
            node_id = f"{edge_id}__split_node_{boundary_index}"
            node_map[node_id] = point
            ET.SubElement(
                node_root,
                "node",
                {
                    "id": node_id,
                    "x": f"{point[0]:.2f}",
                    "y": f"{point[1]:.2f}",
                    "type": "priority",
                },
            )
            new_node_ids.append(node_id)

        new_node_ids.append(edge_element.get("to"))

        for part_index in range(len(deduped) - 1):
            start_ratio = deduped[part_index]
            end_ratio = deduped[part_index + 1]

            if end_ratio <= keep_from + 1e-9 or start_ratio >= keep_to - 1e-9:
                continue

            clipped_start = max(start_ratio, keep_from)
            clipped_end = min(end_ratio, keep_to)
            if clipped_end - clipped_start <= 1e-9:
                continue

            part_id = f"{edge_id}__part{part_index + 1}"
            part_points = slice_polyline(points, clipped_start, clipped_end)
            if len(part_points) < 2:
                continue

            part_attrs = dict(edge_element.attrib)
            part_attrs.update(
                {
                    "id": part_id,
                    "from": new_node_ids[part_index],
                    "to": new_node_ids[part_index + 1],
                    "numLanes": str(lane_for_interval(default_lanes, segment_edits, clipped_start, clipped_end)),
                    "shape": format_shape(part_points),
                }
            )
            ET.SubElement(edge_root, "edge", part_attrs)
            part_ids.append(part_id)

        if part_ids:
            split_info[edge_id] = {"parts": part_ids, "first": part_ids[0], "last": part_ids[-1]}
        else:
            split_info[edge_id] = {"parts": [], "first": edge_id, "last": edge_id}
            removed_edge_ids.add(edge_id)

    turn_rules = {
        item["id"]: item.get("turnRestrictions")
        for item in modifications
        if item.get("turnRestrictions")
    }

    for connection in list(connection_root.findall("connection")):
        original_from = connection.get("from")
        original_to = connection.get("to")
        if original_from in removed_edge_ids or original_to in removed_edge_ids:
            connection_root.remove(connection)
            continue

        turns = turn_rules.get(original_from)
        if turns:
            allowed = set(turns.get("allowedTargets", []))
            blocked = set(turns.get("blockedTargets", []))
            if allowed and original_to not in allowed:
                connection_root.remove(connection)
                continue
            if original_to in blocked:
                connection_root.remove(connection)
                continue

        mapped_from = split_info.get(original_from, {"last": original_from})["last"]
        mapped_to = split_info.get(original_to, {"first": original_to})["first"]

        if mapped_from in removed_edge_ids or mapped_to in removed_edge_ids:
            connection_root.remove(connection)
            continue

        connection.set("from", mapped_from)
        connection.set("to", mapped_to)

    for info in split_info.values():
        parts = info["parts"]
        if len(parts) < 2:
            continue
        for index in range(len(parts) - 1):
            ET.SubElement(connection_root, "connection", {"from": parts[index], "to": parts[index + 1]})

    lane_counts = {
        edge.get("id"): int(edge.get("numLanes", "1"))
        for edge in edge_root.findall("edge")
    }
    for connection in connection_root.findall("connection"):
        clamp_lane_attr(connection, "fromLane", lane_counts.get(connection.get("from"), 1))
        clamp_lane_attr(connection, "toLane", lane_counts.get(connection.get("to"), 1))


    for node in node_root.findall("node"):
        node_id = node.get("id")
        if node_id in forced_tls_ids:
            node.set("type", "traffic_light")
            node.set("tl", node_id)

    node_tree.write(node_path, encoding="utf-8", xml_declaration=True)
    edge_tree.write(edge_path, encoding="utf-8", xml_declaration=True)
    connection_tree.write(connection_path, encoding="utf-8", xml_declaration=True)


def sanitize_tll_connections(tll_path, edge_path):
    if not Path(tll_path).exists() or not Path(edge_path).exists():
        return

    edge_tree = ET.parse(edge_path)
    edge_ids = {edge.get("id") for edge in edge_tree.getroot().findall("edge")}

    tll_tree = ET.parse(tll_path)
    tll_root = tll_tree.getroot()

    used_tl_ids = set()
    for connection in list(tll_root.findall("connection")):
        from_edge = connection.get("from")
        to_edge = connection.get("to")
        if from_edge not in edge_ids or to_edge not in edge_ids:
            tll_root.remove(connection)
            continue
        tl_id = connection.get("tl")
        if tl_id:
            used_tl_ids.add(tl_id)

    for tl_logic in list(tll_root.findall("tlLogic")):
        if tl_logic.get("id") not in used_tl_ids:
            tll_root.remove(tl_logic)

    tll_tree.write(tll_path, encoding="utf-8", xml_declaration=True)


def create_sumocfg(path, net_file, route_file, begin=0, end=3600):
    config = ET.Element("configuration")
    input_el = ET.SubElement(config, "input")
    ET.SubElement(input_el, "net-file", {"value": net_file})
    ET.SubElement(input_el, "route-files", {"value": route_file})

    time_el = ET.SubElement(config, "time")
    ET.SubElement(time_el, "begin", {"value": str(begin)})
    ET.SubElement(time_el, "end", {"value": str(end)})

    report_el = ET.SubElement(config, "report")
    ET.SubElement(report_el, "verbose", {"value": "true"})
    ET.SubElement(report_el, "no-step-log", {"value": "true"})

    tree = ET.ElementTree(config)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def enforce_forced_tls_only(final_net_path, forced_traffic_lights):
    forced_ids = {str(item) for item in (forced_traffic_lights or []) if item is not None}

    tree = ET.parse(final_net_path)
    root = tree.getroot()

    junctions = root.findall("junction")

    def matches_forced(junction_id):
        if junction_id in forced_ids:
            return True
        # netconvert with --junctions.join may rename nodes to cluster_* ids.
        # Those IDs usually contain original node ids as parts.
        if junction_id and junction_id.startswith("cluster_"):
            for fid in forced_ids:
                if fid in junction_id:
                    return True
        return False

    selected_junction_ids = {j.get("id") for j in junctions if matches_forced(j.get("id"))}

    # Keep tlLogic only for selected (or matched cluster) junction ids.
    for tl_logic in list(root.findall("tlLogic")):
        if tl_logic.get("id") not in selected_junction_ids:
            root.remove(tl_logic)

    # Keep traffic_light type only on selected junctions.
    for junction in junctions:
        node_id = junction.get("id")
        j_type = junction.get("type") or ""

        if node_id in selected_junction_ids:
            if not j_type.startswith("traffic_light"):
                junction.set("type", "traffic_light")
            junction.set("tl", node_id)
        else:
            if j_type.startswith("traffic_light"):
                junction.set("type", "priority")
            junction.attrib.pop("tl", None)

    # Keep connection tl/linkIndex only for selected tls ids.
    for connection in root.findall("connection"):
        tl_id = connection.get("tl")
        if tl_id and tl_id in selected_junction_ids:
            continue
        connection.attrib.pop("tl", None)
        connection.attrib.pop("linkIndex", None)

    tree.write(final_net_path, encoding="utf-8", xml_declaration=True)



def build_turn_summary(modifications):
    return [
        {
            "edgeId": item["id"],
            "alias": item.get("alias", ""),
            "allowedTargets": item["turnRestrictions"].get("allowedTargets", []),
            "blockedTargets": item["turnRestrictions"].get("blockedTargets", []),
            "allowedAliases": item["turnRestrictions"].get("allowedAliases", []),
            "blockedAliases": item["turnRestrictions"].get("blockedAliases", []),
        }
        for item in modifications
        if item.get("turnRestrictions")
    ]



def build_segment_summary(modifications):
    changes = []
    for item in modifications:
        for segment in item.get("segmentEdits", []):
            changes.append(
                {
                    "edgeId": item["id"],
                    "alias": item.get("alias", ""),
                    "segmentId": segment["segmentId"],
                    "lanes": segment["lanes"],
                    "fromRatio": segment["fromRatio"],
                    "toRatio": segment["toRatio"],
                    "startCoord": segment["startCoord"],
                    "endCoord": segment["endCoord"],
                }
            )
    return changes


def generate_sumo_project(cache_key, bounds, modifications, total_links, aliases, forced_traffic_lights=None, has_roundabout=False):
    osm_path = ensure_osm_source(cache_key, bounds)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir = SUMO_EXPORTS_DIR / f"{cache_key}_{stamp}"
    project_dir.mkdir(parents=True, exist_ok=True)

    source_copy = project_dir / "source.osm.xml"
    shutil.copyfile(osm_path, source_copy)

    base_net_path = project_dir / "base.net.xml"
    run_command(["netconvert", "--osm-files", str(source_copy), "-o", str(base_net_path)])

    plain_prefix = project_dir / "plain"
    run_command(["netconvert", "--sumo-net-file", str(base_net_path), "--plain-output-prefix", str(plain_prefix)])

    node_path = project_dir / "plain.nod.xml"
    edge_path = project_dir / "plain.edg.xml"
    connection_path = project_dir / "plain.con.xml"
    tll_path = project_dir / "plain.tll.xml"

    apply_modifications_to_plain(node_path, edge_path, connection_path, modifications, forced_traffic_lights=forced_traffic_lights)
    sanitize_tll_connections(tll_path, edge_path)

    final_net_path = project_dir / "scenario.net.xml"
    netconvert_cmd = [
        "netconvert",
        "--node-files",
        str(node_path),
        "--edge-files",
        str(edge_path),
        "--connection-files",
        str(connection_path),
    ]

    # If there is no roundabout in area, simplify/merge aggressively.
    if not has_roundabout:
        netconvert_cmd.extend([
            "--geometry.remove",
            "true",
            "--junctions.join",
            "true",
            "--junctions.join-dist",
            "30",
            "--roundabouts.guess",
            "false",
            "--no-internal-links",
            "true",
        ])

    netconvert_cmd.extend([
        "-o",
        str(final_net_path),
    ])
    if tll_path.exists():
        netconvert_cmd.extend(["--tllogic-files", str(tll_path)])
    run_command(netconvert_cmd)
    enforce_forced_tls_only(final_net_path, forced_traffic_lights)
    trips_path = project_dir / "scenario.trips.xml"
    routes_path = project_dir / "scenario.rou.xml"
    run_command(
        [
            sys.executable,
            str(RANDOM_TRIPS),
            "-n",
            str(final_net_path),
            "-o",
            str(trips_path),
            "-r",
            str(routes_path),
            "-e",
            "3600",
            "-p",
            "2.5",
            "--seed",
            "42",
            "--validate",
        ]
    )

    sumocfg_path = project_dir / "scenario.sumocfg"
    create_sumocfg(sumocfg_path, final_net_path.name, routes_path.name)

    manifest = {
        "format": "sumo-project-manifest/v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "cacheKey": cache_key,
        "bounds": bounds,
        "networkSummary": {
            "totalLinks": total_links,
            "editedLinks": len(modifications),
            "segmentLaneChanges": len(build_segment_summary(modifications)),
            "turnRestrictionChanges": len(build_turn_summary(modifications)),
        },
        "files": {
            "osmSource": source_copy.name,
            "baseNet": base_net_path.name,
            "finalNet": final_net_path.name,
            "trips": trips_path.name,
            "routes": routes_path.name,
            "sumocfg": sumocfg_path.name,
        },
        "modifications": modifications,
        "aliases": aliases,
    }
    manifest_path = project_dir / "manifest.json"
    save_json(manifest_path, manifest)

    archive_base = project_dir.parent / project_dir.name
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", project_dir))
    shutil.copyfile(archive_path, LAST_PROJECT_ARCHIVE)
    save_json(LAST_EXPORT_FILE, manifest)
    save_json(LAST_MODS_FILE, modifications)

    return {
        "projectDir": str(project_dir),
        "archivePath": str(archive_path),
        "sumocfgPath": str(sumocfg_path),
        "manifest": manifest,
    }


@app.route("/")
def root():
    return app.send_static_file("index.html")


@app.route("/get_network", methods=["POST"])
@app.route("/get_sumo_network", methods=["POST"])
def get_network():
    data = request.get_json(force=True)
    min_lat = data["min_lat"]
    min_lon = data["min_lon"]
    max_lat = data["max_lat"]
    max_lon = data["max_lon"]

    try:
        network, key = get_or_create_network(min_lat, min_lon, max_lat, max_lon)
        return jsonify({"cacheKey": key, **network})

    except Exception as exc:
        print("GET_NETWORK ERROR:", exc)

        return jsonify({
            "error": str(exc),
            "links": []
        }), 200   # ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ 500 yerine 200


@app.route("/update_network", methods=["POST"])
def update_network():
    data = request.get_json(force=True)
    modifications = data.get("modifications", [])
    bounds = data.get("bounds")
    cache_key = data.get("cacheKey")
    aliases = data.get("aliases", {})
    total_links = data.get("networkSummary", {}).get("totalLinks", 0)
    forced_traffic_lights = data.get("forcedTrafficLights", [])
    has_roundabout = bool(data.get("hasRoundabout", False))
    region_name = (data.get("regionName") or "").strip()
    region_address = (data.get("regionAddress") or "").strip()
    region_id_from_client = data.get("regionId")
    editor_state = data.get("editorState")

    if not bounds or not cache_key:
        return jsonify({"error": "bounds and cacheKey are required"}), 400

    # Always persist region metadata first so Save action writes DB even if SUMO export fails.
    network_summary = data.get("networkSummary", {})
    car_count = network_summary.get("carCount", network_summary.get("totalCars", total_links))
    target_region_id = int(region_id_from_client) if region_id_from_client is not None else None
    if target_region_id is None:
        target_region_id = _find_existing_region_id_by_bounds(bounds)
    try:
        if target_region_id is not None:
            saved_region_id = upsert_region(
                target_region_id,
                cache_key,
                bounds["min_lat"],
                bounds["min_lon"],
                bounds["max_lat"],
                bounds["max_lon"],
                car_count=car_count,
                display_name=region_name or cache_key,
                address=region_address or resolve_address_from_bounds(bounds),
            )
        else:
            saved_region_id = save_region(
                cache_key,
                bounds["min_lat"],
                bounds["min_lon"],
                bounds["max_lat"],
                bounds["max_lon"],
                car_count=car_count,
                display_name=region_name or cache_key,
                address=region_address or resolve_address_from_bounds(bounds),
            )
            target_region_id = int(saved_region_id)
    except Exception as exc:
        return jsonify({"error": f"DB save failed: {exc}"}), 500

    try:
        _save_editor_state(target_region_id, editor_state or {})
    except Exception as exc:
        print("EDITOR STATE SAVE ERROR:", exc)

    try:
        project = generate_sumo_project(cache_key, bounds, modifications, total_links, aliases, forced_traffic_lights=forced_traffic_lights, has_roundabout=has_roundabout)
    except Exception as exc:
        print("UPDATE_NETWORK EXPORT ERROR:", exc)
        traceback.print_exc()
        stub = _write_transaction_stub_config(
            target_region_id,
            bounds,
            region_name or cache_key,
            region_address or resolve_address_from_bounds(bounds),
            exc,
            editor_state=editor_state or {},
        )
        bundle_path = _build_transaction_bundle(target_region_id)
        return jsonify(
            {
                "status": "saved_only",
                "regionId": target_region_id,
                "warning": f"Region saved to DB, but SUMO export failed: {exc}",
                "transactionConfig": stub,
                "bundleDownloadUrl": f"/transactions/{target_region_id}/bundle",
                "bundlePath": str(bundle_path),
            }
        ), 200

    transaction_config = _write_transaction_config(
        target_region_id,
        project,
        bounds,
        region_name or cache_key,
        region_address or resolve_address_from_bounds(bounds),
        editor_state=editor_state or {},
    )
    bundle_path = _build_transaction_bundle(target_region_id)
    return jsonify(
        {
            "status": "ok",
            "downloadUrl": "/download_export",
            "exportPath": project["archivePath"],
            "sumocfgPath": project["sumocfgPath"],
            "summary": project["manifest"]["networkSummary"],
            "regionId": target_region_id,
            "transactionConfig": transaction_config,
            "bundleDownloadUrl": f"/transactions/{target_region_id}/bundle",
            "bundlePath": str(bundle_path),
        }
    )


@app.route("/download_export", methods=["GET"])
def download_export():
    if not LAST_PROJECT_ARCHIVE.exists():
        return jsonify({"error": "No export created yet."}), 404
    return send_file(LAST_PROJECT_ARCHIVE, as_attachment=True, download_name=LAST_PROJECT_ARCHIVE.name)


@app.route("/transactions/<int:region_id>/bundle", methods=["GET"])
def download_transaction_bundle(region_id):
    paths = _transaction_paths(region_id)
    if not paths["root"].exists() and not paths["config"].exists():
        return jsonify({"error": f"No runtime assets found for transaction {region_id}"}), 404
    bundle_path = _build_transaction_bundle(region_id)
    return send_file(
        bundle_path,
        as_attachment=True,
        download_name=f"transaction_{int(region_id)}.zip",
    )


@app.route("/media", methods=["GET"])
def serve_media():
    rel = (request.args.get("path") or "").strip()
    if not rel:
        return jsonify({"error": "path query param is required"}), 400

    raw_path = Path(rel)
    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(PROJECT_ROOT / raw_path)
        # Legacy/simplified values can be just filename (e.g., testvid3.mp4).
        # Try common runtime locations.
        name_only = raw_path.name
        if name_only:
            candidates.append(PROJECT_ROOT / "camera_tests" / "footage" / name_only)
            for tx_dir in (PROJECT_ROOT / "runtime_assets" / "transactions").glob("*"):
                candidates.append(tx_dir / "camera" / "media" / name_only)

    root_resolved = PROJECT_ROOT.resolve()
    target = None
    for cand in candidates:
        try:
            resolved = cand.resolve()
            resolved.relative_to(root_resolved)
        except Exception:
            continue
        if resolved.exists() and resolved.is_file():
            target = resolved
            break

    if target is None:
        return jsonify({"error": f"file not found: {rel}"}), 404

    return send_file(target, as_attachment=False)


@app.route("/transactions/<int:region_id>/camera/upload", methods=["POST"])
def upload_camera_media(region_id):
    if "file" not in request.files:
        return jsonify({"error": "file is required"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty filename"}), 400

    safe_name = secure_filename(file.filename) or "camera_source.mp4"
    paths = _transaction_paths(region_id)
    media_dir = paths["camera"] / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / safe_name
    file.save(target)

    rel = target.relative_to(PROJECT_ROOT)
    return jsonify(
        {
            "ok": True,
            "savedPath": str(rel).replace("\\", "/"),
            "previewUrl": f"/media?path={str(rel).replace(chr(92), '/')}",
        }
    ), 200


@app.route("/reverse_geocode", methods=["GET"])
def reverse_geocode():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon query params are required"}), 400
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon},
            headers={"User-Agent": "Greenwave-TrafficProject/1.0 (contact: zcorumluoglu3@gmail.com)"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return jsonify({"address": payload.get("display_name") or "Address not found"})
    except Exception as exc:
        return jsonify({"address": "Address not found", "detail": str(exc)}), 200

@app.route("/test-db")
def test_db():
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT version();")
    version = cur.fetchone()
    
    cur.close()
    conn.close()

    return {"db_version": version}

@app.route("/intersections", methods=["POST"])
def add_intersection():
    data = request.json

    name = data.get("name")
    lat = data.get("latitude")
    lng = data.get("longitude")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO intersections (name, latitude, longitude)
        VALUES (%s, %s, %s)
    """, (name, lat, lng))

    conn.commit()
    conn.close()

    return jsonify({"message": "Intersection added"})

@app.route("/regions", methods=["GET"])
def get_regions():
    """VeritabanÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±nda kaydedilen tÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼m bÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶lgeleri dÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶ndÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼r"""
    conn = get_connection()
    cursor = conn.cursor()
    
    identity_table = "region_identity"
    try:
        cursor.execute("SELECT to_regclass('public.regions_identity')")
        has_plural_identity = cursor.fetchone()[0] is not None
        if has_plural_identity:
            identity_table = "regions_identity"
    except Exception:
        identity_table = "region_identity"

    cursor.execute(f"""
    SELECT r.id, COALESCE(ri.name, r.name), r.min_lat, r.min_lon, r.max_lat, r.max_lon, r.car_count, r.created_at, ri.address
    FROM regions r
    LEFT JOIN {identity_table} ri ON ri.region_id = r.id
    ORDER BY created_at DESC
    """)
    
    regions = []
    for row in cursor.fetchall():
        regions.append({
            "id": row[0],
            "name": row[1],
            "min_lat": row[2],
            "min_lon": row[3],
            "max_lat": row[4],
            "max_lon": row[5],
            "carCount": row[6] if row[6] is not None else 0,
            "createdAt": row[7],
            "address": row[8],
        })
    
    conn.close()
    return jsonify({"regions": regions})

@app.route("/regions/<int:region_id>", methods=["DELETE"])
def delete_region_endpoint(region_id):
    """Belirtilen ID'ye sahip bÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬ÂÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¶lgeyi sil"""
    try:
        delete_region(region_id)
        return jsonify({"message": "Region deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/regions/<int:region_id>/stats", methods=["GET"])
def get_region_stats(region_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, car_count
        FROM regions
        WHERE id = %s
        """,
        (region_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Region not found"}), 404

    return jsonify(
        {
            "regionId": row[0],
            "name": row[1],
            "carCount": row[2] if row[2] is not None else 0,
        }
    )


@app.route("/editor_state/<int:region_id>", methods=["GET"])
def get_editor_state(region_id):
    state = _load_editor_state(region_id)
    if state is None:
        return jsonify({"regionId": region_id, "state": None}), 200
    return jsonify({"regionId": region_id, "state": state}), 200


@app.route("/editor_state/<int:region_id>", methods=["POST"])
def save_editor_state(region_id):
    payload = request.get_json(silent=True) or {}
    state = payload.get("state", payload)
    _save_editor_state(region_id, state or {})
    return jsonify({"ok": True, "regionId": region_id}), 200


@app.route("/transactions/<transaction_id>/dashboard-cards", methods=["GET"])
def get_dashboard_cards(transaction_id):
    row = get_transaction_dashboard_cards(transaction_id)
    if not row:
        return jsonify({"error": "Dashboard cards not found for transaction"}), 404
    payload = {
        "transactionId": row[0],
        "congestionImprovement": float(row[1]),
        "avgCongestion": int(row[2]),
        "signalTimes": {
            "junction": "R1",
            "greenSeconds": int(row[3]),
            "redSeconds": int(row[4]),
        },
        "source": "db",
    }
    return jsonify(payload)


@app.route("/intersections/live", methods=["GET"])
def list_live_intersections():
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT experiment_id
                    FROM simulation_logs
                    WHERE experiment_id IS NOT NULL
                    ORDER BY experiment_id
                    """
                )
                rows = cursor.fetchall()
    except Exception as exc:
        return jsonify({"error": f"SUMO database unavailable: {exc}"}), 503

    intersections = []
    for row in rows:
        exp_id = int(row[0])
        intersections.append(
            {
                "intersectionId": f"INT-{exp_id:03d}",
                "name": _resolve_region_display_name(exp_id),
                "location": "SUMO Simulation",
                "isActive": True,
                "createdAt": None,
            }
        )
    return jsonify({"intersections": intersections})


@app.route("/intersections/<intersection_id>/live-dashboard", methods=["GET"])
def intersection_live_dashboard(intersection_id):
    try:
        experiment_id = parse_experiment_id(intersection_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    region_name = _resolve_region_display_name(experiment_id)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT queue_length, average_waiting_time, density_level, created_at
                    FROM simulation_logs
                    WHERE experiment_id = %s
                    ORDER BY step DESC
                    LIMIT 8
                    """,
                    (experiment_id,),
                )
                sim_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT selected_phase, green_duration
                    FROM decision_logs
                    WHERE experiment_id = %s
                    ORDER BY step DESC
                    LIMIT 8
                    """,
                    (experiment_id,),
                )
                decision_rows = cursor.fetchall()
    except Exception as exc:
        return jsonify({"error": f"SUMO database unavailable: {exc}"}), 503

    if not sim_rows:
        return jsonify(
            {
                "intersection": {
                    "intersectionId": intersection_id,
                    "name": region_name,
                    "location": "SUMO Simulation",
                },
                "cards": {
                    "liveCongestionImprovement": 0.0,
                    "avgCongestion": 0.0,
                },
                "cycle": {
                    "cycleNo": 0,
                    "updatedAt": None,
                },
                "roads": [],
                "signalPlan": [],
                "status": "waiting_for_runtime_data",
            }
        ), 200

    # Strict source policy: average congestion comes only from camera DB aggregates.
    avg_congestion = _get_latest_camera_avg_from_db(experiment_id)
    if avg_congestion is None:
        avg_congestion = 0.0
    # Prefer algorithm-produced runtime KPI for improvement.
    # Fallback to derived score only if KPI row is unavailable.
    congestion_improvement = None
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT congestion_improvement
                    FROM experiment_runtime_kpis
                    WHERE experiment_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (experiment_id,),
                )
                kpi_row = cursor.fetchone()
                if kpi_row is not None and kpi_row[0] is not None:
                    congestion_improvement = float(kpi_row[0])
    except Exception:
        congestion_improvement = None

    if congestion_improvement is None:
        live_camera_improvement = _get_live_camera_improvement_percent(experiment_id)
        congestion_improvement = float(live_camera_improvement) if live_camera_improvement is not None else 0.0
    today_avg_congestion = _get_today_camera_avg(experiment_id)

    roads = []
    for idx, row in enumerate(sim_rows, start=1):
        roads.append(
            {
                "roadCode": f"R{idx}",
                "vehicleCount": int(row[0] or 0),
                "queueLength": int(row[0] or 0),
                "avgWaitingSeconds": float(round(row[1] or 0.0, 2)),
                "densityLevel": row[2] or "UNKNOWN",
            }
        )

    signal_plan = []
    for row in decision_rows:
        signal_plan.append(
            {
                "phaseCode": f"P{int(row[0] or 0)}",
                "greenSeconds": int(row[1] or 0),
                "redSeconds": max(0, 60 - int(row[1] or 0)),
            }
        )

    return jsonify(
        {
            "intersection": {
                "intersectionId": intersection_id,
                "name": region_name,
                "location": "SUMO Simulation",
            },
            "cards": {
                "liveCongestionImprovement": float(round(congestion_improvement, 1)),
                "avgCongestion": float(round(avg_congestion, 1)),
                "todayAvgCongestion": float(round(today_avg_congestion, 1)) if today_avg_congestion is not None else 0.0,
                "avgCongestionSource": "db",
            },
            "cycle": {
                "cycleNo": 1,
                "updatedAt": sim_rows[0][3],
            },
            "roads": roads,
            "signalPlan": signal_plan,
        }
    )


@app.route("/intersections/<intersection_id>/runtime-monitor", methods=["GET"])
def intersection_runtime_monitor(intersection_id):
    limit = request.args.get("limit", default=20, type=int)
    if limit < 5:
        limit = 5
    if limit > 100:
        limit = 100

    try:
        experiment_id = parse_experiment_id(intersection_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    region_name = _resolve_region_display_name(experiment_id)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT step, queue_length, average_waiting_time, density_level, created_at
                    FROM simulation_logs
                    WHERE experiment_id = %s
                    ORDER BY step DESC
                    LIMIT %s
                    """,
                    (experiment_id, limit),
                )
                sim_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT step, selected_phase, green_duration, created_at
                    FROM decision_logs
                    WHERE experiment_id = %s
                    ORDER BY step DESC
                    LIMIT %s
                    """,
                    (experiment_id, limit),
                )
                dec_rows = cursor.fetchall()
    except Exception as exc:
        return jsonify({"error": f"SUMO database unavailable: {exc}"}), 503

    if not sim_rows:
        return jsonify(
            {
                "intersection": {
                    "intersectionId": intersection_id,
                    "name": region_name,
                },
                "latest": {
                    "step": 0,
                    "queueLength": 0.0,
                    "avgWaitingSeconds": 0.0,
                    "densityLevel": "UNKNOWN",
                    "updatedAt": None,
                    "selectedPhase": None,
                    "greenSeconds": None,
                },
                "recentSimulation": [],
                "recentDecisions": [],
                "status": "waiting_for_runtime_data",
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
        ), 200

    latest_sim = sim_rows[0]
    latest_dec = dec_rows[0] if dec_rows else None
    latest_score = _congestion_score_0_100(
        queue_length=latest_sim[1],
        waiting_like_value=latest_sim[2],
        density_level=latest_sim[3],
    )

    return jsonify(
        {
            "intersection": {
                "intersectionId": intersection_id,
                "name": region_name,
            },
            "latest": {
                "step": int(latest_sim[0] or 0),
                "queueLength": float(latest_sim[1] or 0),
                "avgWaitingSeconds": float(round(latest_sim[2] or 0, 2)),
                "densityLevel": latest_sim[3] or "UNKNOWN",
                "congestionScore": float(round(latest_score, 1)),
                "updatedAt": latest_sim[4],
                "selectedPhase": int(latest_dec[1] or 0) if latest_dec else None,
                "greenSeconds": int(latest_dec[2] or 0) if latest_dec else None,
            },
            "recentSimulation": [
                {
                    "step": int(row[0] or 0),
                    "queueLength": float(row[1] or 0),
                    "avgWaitingSeconds": float(round(row[2] or 0, 2)),
                    "densityLevel": row[3] or "UNKNOWN",
                    "congestionScore": float(
                        round(
                            _congestion_score_0_100(
                                queue_length=row[1],
                                waiting_like_value=row[2],
                                density_level=row[3],
                            ),
                            1,
                        )
                    ),
                    "createdAt": row[4],
                }
                for row in sim_rows
            ],
            "recentDecisions": [
                {
                    "step": int(row[0] or 0),
                    "selectedPhase": int(row[1] or 0),
                    "greenSeconds": int(row[2] or 0),
                    "redSeconds": max(0, 60 - int(row[2] or 0)),
                    "createdAt": row[3],
                }
                for row in dec_rows
            ],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/camera/congestion", methods=["POST"])
def camera_congestion_ingest():
    payload = request.get_json(silent=True) or {}
    try:
        junction_id = int(payload.get("junction_id"))
    except Exception:
        return jsonify({"error": "junction_id is required and must be int"}), 400

    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, list) or not raw_scores:
        return jsonify({"error": "scores must be a non-empty list"}), 400

    scores = []
    for s in raw_scores:
        try:
            scores.append(max(0.0, min(100.0, float(s))))
        except Exception:
            continue
    if not scores:
        return jsonify({"error": "scores list has no numeric values"}), 400

    avg_congestion = float(sum(scores) / len(scores))
    _upsert_congestion_minute(
        junction_id=junction_id,
        avg_congestion=avg_congestion,
        road_sample_count=len(scores),
    )
    return jsonify({"ok": True, "junctionId": junction_id, "avgCongestion": round(avg_congestion, 2)}), 200


@app.route("/intersections/<intersection_id>/analytics", methods=["GET"])
def intersection_analytics(intersection_id):
    range_key = request.args.get("range", "24h")
    if range_key not in {"24h", "7d", "30d"}:
        return jsonify({"error": "range must be one of: 24h, 7d, 30d"}), 400

    try:
        experiment_id = parse_experiment_id(intersection_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    region_name = _resolve_region_display_name(experiment_id)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                if range_key == "24h":
                    cursor.execute(
                        """
                        SELECT
                            DATE_TRUNC('hour', hour_ts) AS bucket,
                            AVG(avg_congestion)::float AS avg_congestion,
                            MAX(max_congestion)::float AS peak_congestion
                        FROM camera_congestion_hourly
                        WHERE junction_id = %s
                          AND hour_ts >= NOW() - INTERVAL '24 hour'
                        GROUP BY bucket
                        ORDER BY bucket ASC
                        """,
                        (experiment_id,),
                    )
                    hourly_rows = cursor.fetchall()
                else:
                    cursor.execute(
                        """
                        SELECT
                            day_date AS bucket,
                            avg_congestion::float AS avg_congestion,
                            max_congestion::float AS peak_congestion
                        FROM camera_congestion_daily
                        WHERE junction_id = %s
                          AND day_date >= CURRENT_DATE - INTERVAL '30 day'
                        ORDER BY bucket ASC
                        """,
                        (experiment_id,),
                    )
                    rows = cursor.fetchall()

                    if not rows:
                        cursor.execute(
                            """
                            SELECT
                                DATE(hour_ts) AS bucket,
                                AVG(avg_congestion)::float AS avg_congestion,
                                MAX(max_congestion)::float AS peak_congestion
                            FROM camera_congestion_hourly
                            WHERE junction_id = %s
                              AND hour_ts >= NOW() - INTERVAL '30 day'
                        GROUP BY bucket
                        ORDER BY bucket ASC
                        """,
                            (experiment_id,),
                        )
                        rows = cursor.fetchall()
    except Exception as exc:
        return jsonify({"error": f"SUMO database unavailable: {exc}"}), 503

    if range_key == "24h":
        def _fmt_hour_label(bucket):
            if hasattr(bucket, "strftime"):
                return bucket.strftime("%H:00")
            try:
                return datetime.fromisoformat(str(bucket)).strftime("%H:00")
            except Exception:
                return str(bucket)

        def _to_iso(bucket):
            if hasattr(bucket, "isoformat"):
                return bucket.isoformat()
            return str(bucket)

        points = [
            {
                "label": _fmt_hour_label(r[0]),
                "value": float(round(r[1] or 0.0, 1)),
                "timestamp": _to_iso(r[0]),
                "peakValue": float(round(r[2] or 0.0, 1)),
            }
            for r in hourly_rows
        ]
        average_value = sum(p["value"] for p in points) / len(points) if points else 0
        peak_value = max((p.get("peakValue", p["value"]) for p in points), default=0)
        return jsonify(
            {
                "intersection": {
                    "intersectionId": intersection_id,
                    "name": region_name,
                    "location": "SUMO Simulation",
                },
                "range": range_key,
                "unit": "congestion_index_0_100",
                "series": points,
                "summary": {
                    "average": float(round(average_value, 1)),
                    "peak": float(round(peak_value, 1)),
                },
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

    if range_key == "7d":
        rows = rows[-7:]

    points = [
        {
            "label": r[0].strftime("%d %b"),
            "value": float(round(r[1] or 0.0, 1)),
            "timestamp": r[0].isoformat(),
            "peakValue": float(round(r[2] or 0.0, 1)),
        }
        for r in rows
    ]
    average_value = sum(p["value"] for p in points) / len(points) if points else 0
    peak_value = max((p.get("peakValue", p["value"]) for p in points), default=0)

    return jsonify(
        {
            "intersection": {
                "intersectionId": intersection_id,
                "name": region_name,
                "location": "SUMO Simulation",
            },
            "range": range_key,
            "unit": "congestion_index_0_100",
            "series": points,
            "summary": {
                "average": float(round(average_value, 1)),
                "peak": float(round(peak_value, 1)),
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/intersections/<intersection_id>/analytics/day", methods=["GET"])
def intersection_analytics_day(intersection_id):
    day_date = request.args.get("date")
    if not day_date:
        return jsonify({"error": "date query param is required (YYYY-MM-DD)"}), 400

    try:
        parsed_date = datetime.strptime(day_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400

    try:
        experiment_id = parse_experiment_id(intersection_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    region_name = _resolve_region_display_name(experiment_id)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        DATE_TRUNC('hour', hour_ts) AS hour_bucket,
                        AVG(avg_congestion)::float AS avg_congestion
                    FROM camera_congestion_hourly
                    WHERE junction_id = %s
                      AND DATE(hour_ts) = %s
                    GROUP BY hour_bucket
                    ORDER BY hour_bucket ASC
                    """,
                    (experiment_id, parsed_date.isoformat()),
                )
                rows = cursor.fetchall()
    except Exception as exc:
        return jsonify({"error": f"SUMO database unavailable: {exc}"}), 503

    points = [
        {
            "label": r[0].strftime("%H:00"),
            "value": float(round(r[1] or 0.0, 1)),
            "timestamp": r[0].isoformat(),
        }
        for r in rows
    ]
    average_value = sum(p["value"] for p in points) / len(points) if points else 0
    peak_value = max((p["value"] for p in points), default=0)

    return jsonify(
        {
            "intersection": {
                "intersectionId": intersection_id,
                "name": region_name,
                "location": "SUMO Simulation",
            },
            "day": parsed_date.isoformat(),
            "unit": "congestion_index_0_100",
            "series": points,
            "summary": {
                "average": float(round(average_value, 1)),
                "peak": float(round(peak_value, 1)),
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/intersections/<intersection_id>/system-logs", methods=["GET"])
def intersection_system_logs(intersection_id):
    limit = request.args.get("limit", default=100, type=int)
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name
        FROM intersections_live
        WHERE intersection_id = %s
        """,
        (intersection_id,),
    )
    intersection_row = cursor.fetchone()
    if not intersection_row:
        conn.close()
        return jsonify({"error": "Intersection not found"}), 404

    cursor.execute(
        """
        SELECT event_time, issue_text, severity
        FROM system_logs
        WHERE intersection_id = %s
        ORDER BY event_time DESC
        LIMIT %s
        """,
        (intersection_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()

    return jsonify(
        {
            "intersection": {
                "intersectionId": intersection_id,
                "name": intersection_row[0],
            },
            "logs": [
                {
                    "eventTime": row[0],
                    "issue": row[1],
                    "severity": row[2],
                }
                for row in rows
            ],
        }
    )


@app.route("/system/start", methods=["POST"])
def start_system():
    global ACTIVE_REGION_ID
    payload = request.get_json(silent=True) or {}
    region_id = payload.get("region_id")
    if region_id is None:
        return jsonify({"ok": False, "error": "region_id is required"}), 400

    config_path = _transaction_paths(region_id)["config"]
    if not config_path.exists():
        return jsonify(
            {
                "ok": False,
                "error": f"No transaction config for region_id={region_id}. Save from editor first.",
            }
        ), 400

    runner_script = PROJECT_ROOT / "greenwave_test_system.py"
    if not runner_script.exists():
        return jsonify({"ok": False, "error": "Runner script not found: greenwave_test_system.py"}), 500

    started, message = _start_process(
        "transaction_runner",
        [sys.executable, str(runner_script), "--transaction_id", str(int(region_id))],
        PROJECT_ROOT,
    )
    if started:
        ACTIVE_REGION_ID = int(region_id)

    return jsonify(
        {
            "ok": started,
            "results": [{"service": "transaction_runner", "started": started, "message": message}],
            "status": _process_status(),
        }
    )


@app.route("/system/stop", methods=["POST"])
def stop_system():
    global ACTIVE_REGION_ID
    ok, msg = _stop_process("transaction_runner")
    stops = [{"service": "transaction_runner", "stopped": ok, "message": msg}]
    ACTIVE_REGION_ID = None
    return jsonify({"ok": True, "results": stops, "status": _process_status()})


@app.route("/system/status", methods=["GET"])
def system_status():
    return jsonify({"ok": True, "status": _process_status()})

if __name__ == "__main__":
    app.run(debug=True)




