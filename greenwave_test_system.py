import argparse
import json
import os
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "runtime_assets" / "transaction_configs"
GREENWAVE_API_DIR = ROOT / "GreenWaveAPI" / "GreewnWaveAPI"
CAMERA_TESTS_DIR = ROOT / "camera_tests"
ALGORITHM_SUMO_DIR = ROOT / "algorithm_sumo"


def _load_config(transaction_id):
    path = CONFIG_DIR / f"{int(transaction_id)}.json"
    if not path.exists():
        raise FileNotFoundError(f"transaction config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_camera_video_from_config(cfg):
    configured = str(cfg.get("camera_video", "0")).strip()
    if configured and configured != "0":
        return configured

    camera_cfg_path = cfg.get("camera_config_path")
    if not camera_cfg_path:
        return "0"
    p = Path(str(camera_cfg_path))
    if not p.exists():
        return "0"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cameras = data.get("cameras") or []
        if not cameras:
            return "0"
        first = cameras[0] or {}
        src = str(first.get("source", "")).strip()
        src_type = str(first.get("sourceType", "file")).strip().lower()
        if not src:
            return "0"
        if src_type == "url":
            return src
        return src
    except Exception:
        return "0"


def _sync_camera_config_from_editor_state(cfg):
    camera_cfg_path = str(cfg.get("camera_config_path", "")).strip()
    editor_state_path = str(cfg.get("editor_state_path", "")).strip()
    if not camera_cfg_path or not editor_state_path:
        return

    cam_path = Path(camera_cfg_path)
    editor_path = Path(editor_state_path)
    if not cam_path.exists() or not editor_path.exists():
        return

    try:
        camera_cfg = json.loads(cam_path.read_text(encoding="utf-8"))
        editor_state = json.loads(editor_path.read_text(encoding="utf-8"))
    except Exception:
        return

    editor_cameras = (
        (editor_state.get("cameraSetup") or {}).get("cameras")
        if isinstance(editor_state, dict)
        else None
    )
    if not isinstance(editor_cameras, list) or not editor_cameras:
        return

    src_cam = editor_cameras[0] if isinstance(editor_cameras[0], dict) else {}
    dst_cameras = camera_cfg.get("cameras")
    if not isinstance(dst_cameras, list) or not dst_cameras:
        camera_cfg["cameras"] = [{}]
        dst_cameras = camera_cfg["cameras"]
    dst_cam = dst_cameras[0]

    road_drawings = src_cam.get("roadDrawings")
    if isinstance(road_drawings, dict) and road_drawings:
        dst_cam["roadDrawings"] = road_drawings
        dst_cam["roads"] = list(road_drawings.values())
        dst_cam["linkedRoads"] = list(road_drawings.keys())
    road_drawings_normalized = src_cam.get("roadDrawingsNormalized")
    if isinstance(road_drawings_normalized, dict) and road_drawings_normalized:
        dst_cam["roadDrawingsNormalized"] = road_drawings_normalized
    frame_width = src_cam.get("frameWidth")
    frame_height = src_cam.get("frameHeight")
    if frame_width or frame_height:
        dst_cam["frameSize"] = {"width": frame_width, "height": frame_height}

    source_value = str(src_cam.get("sourceValue", "")).strip()
    if source_value:
        dst_cam["sourceType"] = str(src_cam.get("sourceType", "file")).strip() or "file"
        dst_cam["source"] = source_value

    if isinstance(dst_cam, dict):
        dst_cameras[0] = dst_cam
    camera_cfg["cameras"] = dst_cameras
    cam_path.write_text(json.dumps(camera_cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _save_config(transaction_id, payload):
    path = CONFIG_DIR / f"{int(transaction_id)}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _find_runtime_sumo_cfg(transaction_id):
    base = ROOT / "runtime_assets" / "transactions" / str(int(transaction_id)) / "sumo"
    if not base.exists():
        return None
    direct = base / "scenario.sumocfg"
    if direct.exists():
        return direct
    candidates = sorted(base.rglob("scenario.sumocfg"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _detect_tls_id_from_net(sumo_cfg_path):
    cfg_path = Path(sumo_cfg_path)
    try:
        tree = ET.parse(cfg_path)
        root = tree.getroot()
        net_node = root.find("./input/net-file")
        if net_node is None:
            return None
        rel_net = net_node.attrib.get("value")
        if not rel_net:
            return None
        net_path = (cfg_path.parent / rel_net).resolve()
        if not net_path.exists():
            return None

        net_tree = ET.parse(net_path)
        net_root = net_tree.getroot()
        tl_nodes = net_root.findall("tlLogic")
        if tl_nodes:
            return tl_nodes[0].attrib.get("id")
        return None
    except Exception:
        return None


def _start_process(command, cwd):
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def _is_http_up(url, timeout=1.5):
    try:
        if "://" in url:
            host_port = url.split("://", 1)[1].split("/", 1)[0]
        else:
            host_port = url
        if ":" in host_port:
            host, port_text = host_port.split(":", 1)
            port = int(port_text)
        else:
            host = host_port
            port = 80
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def main():
    parser = argparse.ArgumentParser(description="Run full GreenWave stack per transaction.")
    parser.add_argument("--transaction_id", required=True, type=int)
    args = parser.parse_args()

    cfg = _load_config(args.transaction_id)
    _sync_camera_config_from_editor_state(cfg)
    junction_id = str(cfg.get("junction_id", args.transaction_id))
    camera_video = _resolve_camera_video_from_config(cfg)
    camera_model = str(cfg.get("camera_model", "yolov8s.pt"))
    camera_config_path = str(cfg.get("camera_config_path", "")).strip()
    sumo_cfg_path = str(cfg.get("sumo_cfg_path", ""))
    api_template = str(cfg.get("vision_api_url_template", "http://localhost:5185/api/Sumo/traffic/{junction_id}"))
    tls_id = cfg.get("tl_id")

    if not sumo_cfg_path:
        fallback = _find_runtime_sumo_cfg(args.transaction_id)
        if fallback is not None and fallback.exists():
            sumo_cfg_path = str(fallback)
            cfg["sumo_cfg_path"] = sumo_cfg_path
            cfg["status"] = "ready"
            cfg.pop("reason", None)
            _save_config(args.transaction_id, cfg)
        else:
            raise RuntimeError(
                "sumo_cfg_path is missing in transaction config and fallback scenario.sumocfg was not found. "
                "Open editor for this transaction and Save again until SUMO export succeeds."
            )
    if not Path(sumo_cfg_path).exists():
        fallback = _find_runtime_sumo_cfg(args.transaction_id)
        if fallback is not None and fallback.exists():
            sumo_cfg_path = str(fallback)
            cfg["sumo_cfg_path"] = sumo_cfg_path
            cfg["status"] = "ready"
            cfg.pop("reason", None)
            _save_config(args.transaction_id, cfg)
        else:
            raise FileNotFoundError(f"sumo cfg not found: {sumo_cfg_path}")

    if not tls_id:
        tls_id = _detect_tls_id_from_net(sumo_cfg_path)
        if tls_id:
            cfg["tl_id"] = tls_id
            _save_config(args.transaction_id, cfg)

    procs = []
    try:
        api_url = "http://127.0.0.1:5185"
        if not _is_http_up(api_url):
            env = os.environ.copy()
            env["ASPNETCORE_URLS"] = "http://0.0.0.0:5185"
            procs.append(
                subprocess.Popen(
                    ["dotnet", "run", "--no-launch-profile"],
                    cwd=str(GREENWAVE_API_DIR),
                    env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
            )
            time.sleep(3)

            if not _is_http_up(api_url):
                raise RuntimeError("GreenWaveAPI failed to start on http://127.0.0.1:5185")

        procs.append(
            _start_process(
                [
                    sys.executable,
                    "scripts/vehicle_detection_test.py",
                    "--video",
                    camera_video,
                    "--model",
                    camera_model,
                    "--junction-id",
                    junction_id,
                    "--camera-config",
                    camera_config_path,
                ],
                CAMERA_TESTS_DIR,
            )
        )
        time.sleep(2)
        procs.append(
            _start_process(
                [
                    sys.executable,
                    "main.py",
                    "--mode",
                    "adaptive",
       
                    "--use-vision",
                    "--vision-source",
                    "api",
                    "--vision-api-url-template",
                    api_template,
                    "--junction-id",
                    junction_id,
                    "--sumocfg",
                    sumo_cfg_path,
                    "--tl-id",
                    str(tls_id or "clusterJ0_J1_J11_J2_#4more"),
                    "--experiment-id",
                    str(args.transaction_id),
                ],
                ALGORITHM_SUMO_DIR,
            )
        )

        print(f"GreenWave transaction runner started for transaction_id={args.transaction_id}")
        while True:
            if any(p.poll() is not None for p in procs):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            _stop_process(p)


if __name__ == "__main__":
    main()
