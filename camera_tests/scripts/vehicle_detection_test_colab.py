import argparse
import os
import threading
import time
from datetime import datetime

import cv2
from ultralytics import YOLO

import vehicle_detection_test as core

try:
    from google.colab.patches import cv2_imshow
    from IPython.display import clear_output
    HAS_COLAB_PREVIEW = True
except Exception:
    HAS_COLAB_PREVIEW = False

DEFAULT_VIDEO_DIR = os.path.join(core.BASE_DIR, "footage")
DEFAULT_OUTPUT_DIR = os.path.join(core.BASE_DIR, "outputs")


def parse_args():
    p = argparse.ArgumentParser("Colab-Friendly Traffic Congestion Detector")
    p.add_argument("--video", required=True, help="Video path (absolute) or filename under footage/")
    p.add_argument("--model", default="yolov8s.pt")
    p.add_argument("--conf", type=float, default=0.18)
    p.add_argument("--device", default="cpu", help="Use 0 for GPU in Colab")
    p.add_argument("--imgsz", type=int, default=896)
    p.add_argument("--night-mode", choices=["off", "on"], default="on")
    p.add_argument("--gamma", type=float, default=1.35)
    p.add_argument("--clahe-clip", type=float, default=2.5)
    p.add_argument("--augment", action="store_true", help="Enable test-time augmentation (slower)")

    p.add_argument("--junction-id", type=int, default=None, help="Skip interactive prompt and force this ID")
    p.add_argument("--roads-file", default=core.ROADS_FILE, help="Path to roads json")
    p.add_argument("--auto-full-frame-road", action="store_true", help="Create one full-frame road if roads file missing")

    p.add_argument("--output", default="", help="Output video path (.mp4)")
    p.add_argument("--preview-every", type=int, default=0, help="Show every Nth frame in notebook")
    p.add_argument("--max-frames", type=int, default=0, help="Stop after N frames (0 = all)")

    p.add_argument("--send-api", action="store_true", help="Enable sending payloads to API")
    p.add_argument("--api-interval", type=int, default=20, help="API send interval in seconds")
    p.add_argument(
        "--dataset_create",
        "--dataset-create",
        action="store_true",
        dest="dataset_create",
        help="Enable dataset capture mode and save payload JSON to a local file",
    )
    p.add_argument(
        "--dataset-file",
        default=os.path.join(core.BASE_DIR, "dataset"),
        help="Output directory for dataset capture mode (one JSON file per payload)",
    )
    p.add_argument(
        "--dataset-interval",
        type=float,
        default=3.0,
        help="Dataset capture interval in seconds",
    )
    return p.parse_args()


def resolve_model_path(model_path):
    if not os.path.isabs(model_path):
        model_path = os.path.abspath(os.path.join(core.BASE_DIR, model_path))
    return model_path


def resolve_video_path(video_path):
    if video_path == "0":
        return 0
    if os.path.isabs(video_path):
        return video_path
    return os.path.join(DEFAULT_VIDEO_DIR, video_path)


def resolve_output_path(video_path, output_arg):
    if output_arg:
        return output_arg

    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    base = "webcam" if video_path == 0 else os.path.splitext(os.path.basename(str(video_path)))[0]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(DEFAULT_OUTPUT_DIR, f"{base}_processed_{stamp}.mp4")


def ensure_junction_id(forced_id):
    if forced_id is not None:
        core.JUNCTION_ID = int(forced_id)
        core.save_junction_id(core.JUNCTION_ID)
        return

    loaded = core.load_junction_id()
    if loaded is not None:
        core.JUNCTION_ID = loaded
        return

    core.JUNCTION_ID = 1
    core.save_junction_id(core.JUNCTION_ID)


def load_roads_for_colab(roads_file, frame_shape, auto_full_frame):
    core.ROADS_FILE = roads_file
    core.ROADS_DIR = os.path.dirname(roads_file)
    core.ROADS = []

    loaded = core.load_roads_from_file()
    if loaded and len(core.ROADS) > 0:
        return

    if auto_full_frame:
        h, w = frame_shape[:2]
        core.ROADS = [[(0, 0), (w - 1, 0), (w - 1, h - 1), (0, h - 1)]]
        print("[INFO] roads file missing; using 1 full-frame auto road")
        return

    raise RuntimeError(
        f"No roads found at {roads_file}. Create roads.json first or use --auto-full-frame-road"
    )


def maybe_show_preview(frame, preview_every, frame_idx):
    if preview_every <= 0:
        return
    if frame_idx % preview_every != 0:
        return

    if HAS_COLAB_PREVIEW:
        clear_output(wait=True)
        cv2_imshow(frame)
    else:
        print("[INFO] preview requested but Colab preview utilities are unavailable")


def process_frame(frame, model, args, road_monitors, vehicle_class_ids):
    if core.NIGHT_MODE_ENABLED:
        inference_frame = core.preprocess_for_night(frame, gamma=args.gamma, clahe_clip=args.clahe_clip)
    else:
        inference_frame = frame

    results = model.predict(
        source=inference_frame,
        conf=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        classes=vehicle_class_ids if vehicle_class_ids else None,
        augment=args.augment,
        verbose=False,
    )

    all_detections = core.parse_detections(results[0], core.VEHICLE_CLASSES)

    detections_by_road = [[] for _ in road_monitors]
    outside_detections = []

    for det in all_detections:
        matched = False
        for idx, monitor in enumerate(road_monitors):
            if core.point_in_monitor_roi(det["centroid"], monitor):
                detections_by_road[idx].append(det)
                matched = True
        if not matched:
            outside_detections.append(det)

    for idx, monitor in enumerate(road_monitors):
        detections_in_roi = detections_by_road[idx]
        monitor.compute_score(detections_in_roi, frame)
        monitor.log_to_console(interval=5)

        for det in detections_in_roi:
            x1, y1, x2, y2 = det["bbox"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.circle(frame, det["centroid"], 4, (0, 255, 0), -1)

    for det in outside_detections:
        x1, y1, x2, y2 = det["bbox"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

    return frame


def main():
    args = parse_args()
    core.NIGHT_MODE_ENABLED = args.night_mode == "on"

    model_path = resolve_model_path(args.model)
    if not os.path.exists(model_path):
        print("ERROR: model file not found:", model_path)
        return

    print("Loading model:", model_path)
    model = YOLO(model_path)
    vehicle_class_ids = core.get_vehicle_class_ids(model.names)
    if vehicle_class_ids:
        print(f"[INFO] Inference class filter active: {vehicle_class_ids}")
    else:
        print("[INFO] Inference class filter disabled (using all classes)")

    video_source = resolve_video_path(args.video)
    if video_source == 0:
        print("[WARN] Webcam mode is usually not available in Colab")

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print("ERROR: cannot open video source", video_source)
        return

    ret, first_frame = cap.read()
    if not ret:
        print("ERROR: could not read first frame")
        cap.release()
        return

    try:
        load_roads_for_colab(args.roads_file, first_frame.shape, args.auto_full_frame_road)
    except RuntimeError as e:
        print("ERROR:", e)
        cap.release()
        return

    ensure_junction_id(args.junction_id)
    print(f"[INFO] Using Junction ID: {core.JUNCTION_ID}")
    if args.dataset_create:
        print(
            f"[DATASET] Enabled | interval={args.dataset_interval:.1f}s | file={args.dataset_file}"
        )

    road_monitors = [core.RoadMonitor(road, i + 1) for i, road in enumerate(core.ROADS)]

    out_path = resolve_output_path(video_source, args.output)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    in_fps = cap.get(cv2.CAP_PROP_FPS)
    out_fps = in_fps if in_fps and in_fps > 1 else core.TARGET_FPS
    h, w = first_frame.shape[:2]

    writer = cv2.VideoWriter(
        out_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        out_fps,
        (w, h),
    )

    last_api_send = 0.0
    last_dataset_save = 0.0
    dataset_write_error = False
    dataset_output_announced = False
    api_thread = None
    frames = 0
    start_time = time.time()

    frame = first_frame

    while True:
        loop_start = time.time()

        processed = process_frame(frame, model, args, road_monitors, vehicle_class_ids)

        fps = 1.0 / max(time.time() - loop_start, 1e-6)
        fps_ratio = fps / core.TARGET_FPS

        core.draw_ui(processed, road_monitors, fps_ratio)
        cv2.putText(
            processed,
            f"FPS: {fps:.2f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 255),
            2,
        )

        writer.write(processed)
        frames += 1

        maybe_show_preview(processed, args.preview_every, frames)

        if args.send_api:
            now = time.time()
            if now - last_api_send >= args.api_interval:
                if api_thread is None or not api_thread.is_alive():
                    payload = core.build_traffic_payload(core.JUNCTION_ID, road_monitors)
                    api_thread = threading.Thread(
                        target=core.send_traffic_payload,
                        args=(payload,),
                        daemon=True,
                    )
                    api_thread.start()
                else:
                    print("[API INFO] Previous send still in progress, skipping this interval")
                last_api_send = now

        if args.dataset_create:
            now = time.time()
            if now - last_dataset_save >= args.dataset_interval:
                payload = core.build_traffic_payload(core.JUNCTION_ID, road_monitors)
                try:
                    saved_to = core.append_dataset_payload(payload, args.dataset_file)
                    if not dataset_output_announced:
                        print(f"[DATASET] Saving files under: {os.path.dirname(saved_to)}")
                        dataset_output_announced = True
                except Exception as e:
                    if not dataset_write_error:
                        print(f"[DATASET ERROR] Failed to write dataset payload: {e}")
                        print("[DATASET ERROR] Disabling dataset capture for this session.")
                        dataset_write_error = True
                    args.dataset_create = False
                last_dataset_save = now

        if args.max_frames > 0 and frames >= args.max_frames:
            print(f"[INFO] Reached --max-frames={args.max_frames}")
            break

        ret, next_frame = cap.read()
        if not ret:
            break
        frame = next_frame

    cap.release()
    writer.release()

    elapsed = time.time() - start_time
    print("\n=== SESSION SUMMARY ===")
    print(f"Frames processed: {frames}")
    if elapsed > 0:
        print(f"Average FPS: {frames / elapsed:.2f}")
    else:
        print("Average FPS: N/A")
    print(f"Output saved to: {out_path}")

    for monitor in road_monitors:
        print(f"Road {monitor.road_id} Final Score: {monitor.final_score}/100")


if __name__ == "__main__":
    main()
