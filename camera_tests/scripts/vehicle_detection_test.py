import argparse
import cv2
import time
import json
import requests
import os
import threading
import numpy as np
from collections import Counter, deque
from ultralytics import YOLO
from datetime import datetime
from scipy.spatial import distance as dist

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROADS_DIR = os.path.join(BASE_DIR, "roads_folder")
ROADS_FILE = os.path.join(ROADS_DIR, "roads.json")
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
DEFAULT_MODEL_PATH = os.path.join(
    PROJECT_ROOT,
    "YOLO_BDD_PROJECT",
    "runs",
    "night_subset_6k_yolov8s_e20",
    "weights",
    "best.pt"
)

VIDEO_DIR = r"C:\Users\Administrator\Documents\GreenWave\camera_tests\scripts\footage"

# =========================
# Configuration
# =========================
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "motor", "bike", "bicycle"}
CLASS_NAME_MAP = {
    "motor": "motorcycle",
    "bike": "bicycle"
}
DISPLAY_SCALE = 0.7
TARGET_FPS = 8
FRAME_TIME = 1.0 / TARGET_FPS
MAX_ROADS = 8
WINDOW_SECONDS = 30
WINDOW_SIZE = WINDOW_SECONDS * TARGET_FPS
JUNCTION_ID_FILE = os.path.join(BASE_DIR, "junction_id.json")
JUNCTION_ID = None
API_URL = "http://localhost:5185/api/traffic"

MAX_ROAD_POINTS = 10
MIN_ROAD_POINTS = 3

# Scoring weights
WEIGHTS = {
    'density': 25,
    'occupancy': 35,
    'stagnation': 30,
    'heavy_vehicle': 10
}


class LinearScoreCalibrator:
    def __init__(self, slope=1.0, intercept=0.0, clip_min=0, clip_max=100):
        self.slope = float(slope)
        self.intercept = float(intercept)
        self.clip_min = float(clip_min)
        self.clip_max = float(clip_max)

    @classmethod
    def from_file(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        obj = cls(
            slope=data.get("slope", 1.0),
            intercept=data.get("intercept", 0.0),
            clip_min=data.get("clip_min", 0),
            clip_max=data.get("clip_max", 100)
        )
        obj.meta = data
        return obj

    def apply(self, score):
        value = self.slope * float(score) + self.intercept
        return int(np.clip(value, self.clip_min, self.clip_max))
# =========================
# ROI Globals
# =========================
ROADS = []
CURRENT_ROAD = []
LUT_CACHE = {}
CLAHE_CACHE = {}
NIGHT_MODE_ENABLED = True
NIGHT_ON_BTN = (10, 10, 120, 36)   # x, y, w, h in display coordinates
NIGHT_OFF_BTN = (140, 10, 120, 36) # x, y, w, h in display coordinates


def normalize_class_name(name):
    cls = str(name).strip().lower()
    return CLASS_NAME_MAP.get(cls, cls)


def get_vehicle_class_ids(model_names):
    if isinstance(model_names, dict):
        items = model_names.items()
    else:
        items = enumerate(model_names)

    ids = []
    for idx, name in items:
        if normalize_class_name(name) in VEHICLE_CLASSES:
            ids.append(int(idx))
    return sorted(set(ids))

# =========================
# ID HELPERS
# =========================
def load_junction_id():
    if os.path.exists(JUNCTION_ID_FILE):
        try:
            with open(JUNCTION_ID_FILE, "r") as f:
                return int(json.load(f)["junction_id"])
        except:
            pass
    return None

def save_junction_id(junction_id):
    with open(JUNCTION_ID_FILE, "w") as f:
        json.dump({"junction_id": junction_id}, f)

def prompt_junction_id(cap):
    global JUNCTION_ID

    current_input = ""
    loaded_id = load_junction_id()
    JUNCTION_ID = loaded_id

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], 140), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        if loaded_id is not None:
            cv2.putText(
                frame,
                f"Current Junction ID: {loaded_id}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 0),
                2
            )
            cv2.putText(
                frame,
                "Press I to change or ENTER to continue",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )
        else:
            cv2.putText(
                frame,
                "Enter Junction ID (numbers only):",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 255),
                2
            )

        if current_input:
            cv2.putText(
                frame,
                current_input,
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                2
            )

        cv2.imshow("Traffic Congestion Predictor", frame)

        key = cv2.waitKey(1) & 0xFF

        # ENTER → confirm
        if key == 13 and current_input:
            JUNCTION_ID = int(current_input)
            save_junction_id(JUNCTION_ID)
            break

        # ENTER with existing ID
        if key == 13 and loaded_id is not None and not current_input:
            break

        # I → force change
        if key in (ord('i'), ord('I')):
            current_input = ""
            loaded_id = None

        # Numbers
        if 48 <= key <= 57:
            current_input += chr(key)

        # Backspace
        if key == 8:
            current_input = current_input[:-1]


    cv2.destroyWindow("Traffic Congestion Predictor")

# =========================
# Vehicle Tracker
# =========================
class VehicleTracker:
    def __init__(self, max_disappeared=8, max_distance=50):
        self.next_id = 0
        self.objects = {}
        self.disappeared = {}
        self.positions_history = {}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance


    
    def register(self, centroid):
        self.objects[self.next_id] = centroid
        self.disappeared[self.next_id] = 0
        self.positions_history[self.next_id] = deque(maxlen=10)
        self.positions_history[self.next_id].append(centroid)
        self.next_id += 1
    
    def deregister(self, object_id):
        del self.objects[object_id]
        del self.disappeared[object_id]
        del self.positions_history[object_id]
    
    def update(self, centroids):
        if len(centroids) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            return self.objects
        
        if len(self.objects) == 0:
            for centroid in centroids:
                self.register(centroid)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())
            
            D = dist.cdist(np.array(object_centroids), centroids)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            
            used_rows = set()
            used_cols = set()
            
            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                if D[row, col] > self.max_distance:
                    continue
                
                object_id = object_ids[row]
                self.objects[object_id] = centroids[col]
                self.disappeared[object_id] = 0
                self.positions_history[object_id].append(centroids[col])
                
                used_rows.add(row)
                used_cols.add(col)
            
            for row in set(range(D.shape[0])) - used_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            
            for col in set(range(D.shape[1])) - used_cols:
                self.register(centroids[col])
        
        return self.objects
    
    def get_stagnation_ratio(self, road_area):
        if len(self.positions_history) == 0:
            return 0
        
        stagnant = 0
        total = 0
        adaptive_thresh = max(5, 0.015 * np.sqrt(road_area))
        
        for positions in self.positions_history.values():
            if len(positions) < 3:
                continue
            
            total += 1
            movement = np.linalg.norm(np.array(positions[-1]) - np.array(positions[0]))
            if movement < adaptive_thresh:
                stagnant += 1
        
        return stagnant / max(total, 1)
    
    def get_speed(self, object_id):
        positions = self.positions_history.get(object_id, [])
        if len(positions) < 2:
            return 0.0

        # distance over history
        dist_px = np.linalg.norm(
            np.array(positions[-1]) - np.array(positions[0])
        )

        # assume TARGET_FPS
        time_sec = len(positions) / TARGET_FPS
        return dist_px / max(time_sec, 1e-6)


# =========================
# Traffic Predictor
# =========================
class TrafficPredictor:
    def __init__(self, history_length=60):
        self.score_history = deque(maxlen=history_length)
        self.ema_score = 0
        self.alpha = 0.25
    
    def update(self, instant_score):
        if len(self.score_history) == 0:
            self.ema_score = instant_score
        else:
            self.ema_score = self.alpha * instant_score + (1 - self.alpha) * self.ema_score
        
        self.score_history.append(instant_score)
        return int(self.ema_score)
    
    def get_trend(self):
        if len(self.score_history) < 20:
            return 0
        
        recent = np.mean(list(self.score_history)[-10:])
        older = np.mean(list(self.score_history)[-30:-10])
        return (recent - older) / (10 / TARGET_FPS)
    
    def get_predicted_score(self, horizon_seconds=30):
        trend = self.get_trend()
        predicted = self.ema_score + trend * horizon_seconds * 0.4
        return int(np.clip(predicted, 0, 100))
    
    def get_volatility(self):
        if len(self.score_history) < 10:
            return 0
        return np.std(list(self.score_history)[-30:])
    
# =========================
# Traffic Averager
# =========================    

class FactorAverager:
    def __init__(self, window_size):
        self.values = deque(maxlen=window_size)

    def update(self, value):
        self.values.append(value)
        return self.get_avg()

    def get_avg(self):
        if not self.values:
            return 0.0
        return float(np.mean(self.values))

    def is_full(self):
        return len(self.values) == self.values.maxlen


# =========================
# Road Monitor
# =========================
class RoadMonitor:
    def __init__(self, road_polygon, road_id):
        self.polygon = road_polygon
        self.polygon_np = np.array(self.polygon, dtype=np.int32)
        self.area = abs(cv2.contourArea(self.polygon_np))
        self.bbox = cv2.boundingRect(self.polygon_np)
        self.road_id = road_id
        
        self.tracker = VehicleTracker()
        self.max_capacity = max(5, int(self.area / 18000))

        self.density_avg = FactorAverager(WINDOW_SIZE)
        self.occupancy_avg = FactorAverager(WINDOW_SIZE)
        self.stagnation_avg = FactorAverager(WINDOW_SIZE)
        self.heavy_avg = FactorAverager(WINDOW_SIZE)
        
        self.current_count = 0
        self.vehicle_types = Counter()
        self.raw_score = 0
        self.final_score = 0
        self.last_log_time = 0
        self.has_ambulance = False
        self.last_ambulance_time = 0
        self.ambulance_candidate_since = None
        self.ambulance_object_id = None
        self.AMBULANCE_CONFIRM_SECONDS = 0.5
        self.MIN_AMBULANCE_SPEED = 0.0  # pixels per second


    def compute_score(self, detections, frame, enable_ambulance=True):
        # =========================
        # Tracking
        # =========================
        centroids = np.array(
            [d['centroid'] for d in detections]).reshape(-1, 2) if detections else np.empty((0, 2))
        self.tracker.update(centroids)

        self.vehicle_types.clear()

        for d in detections:
            self.vehicle_types[d['class']] += 1
        
        self.current_count = len(detections)

        current_time = time.time()
        candidate_found = False

        if enable_ambulance and frame is not None:
            for d in detections:
                if not is_likely_ambulance(frame, d):
                    continue

                # find closest tracked object
                for obj_id, centroid in self.tracker.objects.items():
                    if np.linalg.norm(np.array(centroid) - np.array(d['centroid'])) < 30:
                        speed = self.tracker.get_speed(obj_id)

                        if speed >= self.MIN_AMBULANCE_SPEED:
                            candidate_found = True

                            if self.ambulance_object_id != obj_id:
                                self.ambulance_object_id = obj_id
                                self.ambulance_candidate_since = current_time   
                            break

            if candidate_found and self.ambulance_candidate_since:
                elapsed = current_time - self.ambulance_candidate_since

                if elapsed >= self.AMBULANCE_CONFIRM_SECONDS:
                    self.has_ambulance = True
                    self.last_ambulance_time = current_time
            if not candidate_found:
                if self.ambulance_candidate_since and \
                current_time - self.ambulance_candidate_since < 1.0:
                    pass  # tolerate 1 second
                else:
                    self.ambulance_candidate_since = None
                    self.ambulance_object_id = None

            # Decay ONLY confirmed ambulance
            if self.has_ambulance:
                if current_time - self.last_ambulance_time > 3:
                    self.has_ambulance = False
        else:
            self.has_ambulance = False



        # =========================
        # Scoring
        # =========================
        density_ratio = min(self.current_count / self.max_capacity, 1.5)
        density_norm = min(density_ratio / 1.5, 1.0)

        total_vehicle_area = sum(d['bbox_area'] for d in detections)
        occupancy_norm = min(total_vehicle_area / self.area, 1.0)

        stagnation_norm = self.tracker.get_stagnation_ratio(self.area)

        heavy_count = (
            self.vehicle_types.get("truck", 0) +
            self.vehicle_types.get("bus", 0)
        )
        heavy_norm = heavy_count / max(self.current_count, 1)

        d_avg = self.density_avg.update(density_norm)
        o_avg = self.occupancy_avg.update(occupancy_norm)
        s_avg = self.stagnation_avg.update(stagnation_norm)
        h_avg = self.heavy_avg.update(heavy_norm)

        self.raw_score = int(min(100, (
            d_avg * WEIGHTS['density'] +
            o_avg * WEIGHTS['occupancy'] +
            s_avg * WEIGHTS['stagnation'] +
            h_avg * WEIGHTS['heavy_vehicle']
        )))
        self.final_score = self.raw_score

        return self.final_score

        

    def get_ambulance_debug_state(self):
        if self.has_ambulance:
            return "YES"

        if self.ambulance_candidate_since:
            elapsed = time.time() - self.ambulance_candidate_since
            if elapsed < self.AMBULANCE_CONFIRM_SECONDS:
                return f"MAYBE ({elapsed:.1f}s)"

        return "NO"

    def get_status_text(self, confidence):
        stable = all([
            self.density_avg.is_full(),
            self.occupancy_avg.is_full(),
            self.stagnation_avg.is_full(),
            self.heavy_avg.is_full()
        ])

        return [
            f"Road {self.road_id}: {self.final_score}/100",
            f"Confidence: {confidence}%",
            f"Window: {'STABLE' if stable else 'COLLECTING'}",
            f"Vehicles: {self.current_count}",
            f"Stopped(avg): {int(self.stagnation_avg.get_avg() * 100)}%",
            f"Ambulance {'YES' if self.has_ambulance else 'NO'}"
        ]
    
    def log_to_console(self, interval=5):
        now = time.time()
        if now - self.last_log_time < interval:
            return
        
        self.last_log_time = now
        
        print(
            f"[ROAD {self.road_id}] "
            f"Score(avg): {self.final_score}/100 | "
            f"Vehicles: {self.current_count} | "
            f"Ambulance {self.get_ambulance_debug_state()} | "
            f"Density(avg): {self.density_avg.get_avg():.2f} | "
            f"Occupancy(avg): {self.occupancy_avg.get_avg():.2f} | "
            f"Stagnation(avg): {self.stagnation_avg.get_avg():.2f}"
            f"\n-------------------------------------------------------"
        )

    def get_confidence(self, fps_ratio=1.0):
        # Window completion
        window_score = (
            int(self.density_avg.is_full()) +
            int(self.occupancy_avg.is_full()) +
            int(self.stagnation_avg.is_full()) +
            int(self.heavy_avg.is_full())
        ) / 4.0  # 0.0 → 1.0

        # Vehicle presence (no vehicles = low trust)
        vehicle_score = min(self.current_count / max(self.max_capacity, 1), 1.0)

        # FPS quality (passed from main loop)
        fps_score = min(max(fps_ratio, 0.0), 1.0)

        confidence = (
            0.5 * window_score +
            0.3 * vehicle_score +
            0.2 * fps_score
        ) * 100

        return int(confidence)

# =========================
# API HELPER
# =========================
def send_traffic_data(junction_id, road_monitors):
    payload = build_traffic_payload(junction_id, road_monitors)
    send_traffic_payload(payload)


def build_traffic_payload(junction_id, road_monitors):
    payload = {
        "received_time": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "junction_id": junction_id,
        "roads": []
    }

    for monitor in road_monitors:
        payload["roads"].append({
            "road_id": monitor.road_id,
            "congestion_score": monitor.final_score,
            "raw_congestion_score": monitor.raw_score,
            "ambulance": monitor.has_ambulance
        })
    return payload


def send_traffic_payload(payload):
    try:
        response = requests.post(API_URL, json=payload, timeout=5)
        if response.status_code != 200:
            print("[API ERROR]", response.status_code, response.text)
    except Exception as e:
        print("[API CONNECTION ERROR]", e)


def _resolve_dataset_output_dir(output_path):
    path = os.path.normpath(output_path)
    is_dir_hint = output_path.endswith(("\\", "/"))
    _, ext = os.path.splitext(path)

    # Backward compatibility: if a file path is provided, use its parent directory.
    if ext.lower() in (".json", ".jsonl") and not is_dir_hint:
        path = os.path.dirname(path) or "."

    os.makedirs(path, exist_ok=True)
    return path


def append_dataset_payload(payload, output_path):
    out_dir = _resolve_dataset_output_dir(output_path)
    received_time = str(payload.get("received_time", "")).strip()
    if not received_time:
        received_time = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"

    safe_name = "".join(
        ch if ch.isalnum() or ch in ("-", "_", "T", "Z") else "_"
        for ch in received_time
    )
    if not safe_name:
        safe_name = "payload"
    file_path = os.path.join(out_dir, f"{safe_name}.json")

    suffix = 1
    while os.path.exists(file_path):
        file_path = os.path.join(out_dir, f"{safe_name}_{suffix}.json")
        suffix += 1

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return file_path


# =========================
# Mouse callback
# =========================
def _inside_rect(px, py, rect):
    rx, ry, rw, rh = rect
    return rx <= px <= (rx + rw) and ry <= py <= (ry + rh)


def handle_ui_click(display_x, display_y):
    global NIGHT_MODE_ENABLED
    if _inside_rect(display_x, display_y, NIGHT_ON_BTN):
        NIGHT_MODE_ENABLED = True
        return True
    if _inside_rect(display_x, display_y, NIGHT_OFF_BTN):
        NIGHT_MODE_ENABLED = False
        return True
    return False


def mouse_callback(event, x, y, flags, param):
    global ROADS, CURRENT_ROAD

    if event == cv2.EVENT_LBUTTONDOWN:
        # UI buttons are drawn on the displayed (scaled) frame.
        if handle_ui_click(x, y):
            return

        x = int(x / DISPLAY_SCALE)
        y = int(y / DISPLAY_SCALE)

        if len(CURRENT_ROAD) >= MAX_ROAD_POINTS:
            return

        CURRENT_ROAD.append((x, y))

    if event == cv2.EVENT_RBUTTONDOWN:
        CURRENT_ROAD.clear()


# =========================
# Utils
# =========================
def point_in_roi(point, roi_polygon):
    roi_np = roi_polygon if isinstance(roi_polygon, np.ndarray) else np.array(roi_polygon, dtype=np.int32)
    return cv2.pointPolygonTest(roi_np, point, False) >= 0


def point_in_monitor_roi(point, monitor):
    x, y, w, h = monitor.bbox
    px, py = point
    if px < x or py < y or px > (x + w) or py > (y + h):
        return False
    return point_in_roi(point, monitor.polygon_np)

def parse_detections(result, vehicle_classes):
    """Extract vehicle detections with all needed info"""
    detections = []
    
    if result.boxes is not None:
        for i in range(len(result.boxes)):
            x1, y1, x2, y2 = result.boxes.xyxy[i].cpu().numpy()
            cls_idx = int(result.boxes.cls[i].item())
            cls_name = result.names.get(cls_idx, str(cls_idx))
            cls_name = normalize_class_name(cls_name)
            
            if cls_name not in vehicle_classes:
                continue
            
            detections.append({
                'bbox': (int(x1), int(y1), int(x2), int(y2)),
                'bbox_area': (x2 - x1) * (y2 - y1),
                'centroid': (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                'class': cls_name
            })
    
    return detections

def is_likely_ambulance(frame, det):
    """
    Heuristic ambulance detection:
    - must be car or truck
    - large enough
    - contains red + white color
    """
    if det['class'] not in {"car", "truck"}:
        return False

    x1, y1, x2, y2 = det['bbox']

    # Size check (filters normal cars)
    w = x2 - x1
    h = y2 - y1
    if w < 50 or h < 50:
        return False
    
    roi = frame[y1:y2, x1:x2]

    h, w = roi.shape[:2]
    pad_x = int(w * 0.15)
    pad_y = int(h * 0.15)
    roi = roi[pad_y:h-pad_y, pad_x:w-pad_x]

    if roi.size == 0:
        return False

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Red color mask (ambulance stripes / text)
    red1 = cv2.inRange(hsv, (0, 70, 50), (10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 70, 50), (180, 255, 255))
    red_mask = cv2.bitwise_or(red1, red2)

    # White color mask (ambulance body)
    white_mask = cv2.inRange(hsv, (0, 0, 200), (180, 40, 255))

    red_pixels = cv2.countNonZero(red_mask)
    white_pixels = cv2.countNonZero(white_mask)

    area = roi.shape[0] * roi.shape[1]

    # thresholds (tuned for traffic cams)
    if red_pixels / area > 0.003 and white_pixels / area > 0.05:
        return True

    return False


def draw_ui(frame, road_monitors, fps_ratio):
    """Draw all UI elements"""
    # Draw completed roads
    for monitor in road_monitors:

        # 🚑 Ambulance overrides color
        if monitor.has_ambulance:
            road_color = (255, 255, 255)   # white
            text_color = (255, 255, 255)
        else:
            road_color = (255, 0, 0)       # blue
            confidence = monitor.get_confidence(fps_ratio)
            if confidence >= 75:
                text_color = (0, 255, 0)
            elif confidence >= 40:
                text_color = (0, 255, 255)
            else:
                text_color = (0, 0, 255)

        # Draw road polygon
        cv2.polylines(frame, [monitor.polygon_np], True, road_color, 2)

        # Status text
        confidence = monitor.get_confidence(fps_ratio)
        status_lines = monitor.get_status_text(confidence)

        x, y = monitor.polygon[0]
        y_offset = -15

        for line in status_lines:
            cv2.putText(
                frame,
                line,
                (x, y + y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                text_color,
                2
            )
            y_offset -= 20

    # Draw unfinished road
    if len(CURRENT_ROAD) > 0:
        tmp = np.array(CURRENT_ROAD, dtype=np.int32)
        cv2.polylines(frame, [tmp], False, (0, 0, 255), 2)
        for (x, y) in CURRENT_ROAD:
            cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)


def draw_mode_buttons(display_frame, gamma, clahe_clip):
    on_color = (0, 170, 0) if NIGHT_MODE_ENABLED else (60, 60, 60)
    off_color = (0, 0, 180) if not NIGHT_MODE_ENABLED else (60, 60, 60)
    text_color = (255, 255, 255)

    for rect, color, label in (
        (NIGHT_ON_BTN, on_color, "Night ON"),
        (NIGHT_OFF_BTN, off_color, "Night OFF"),
    ):
        x, y, w, h = rect
        cv2.rectangle(display_frame, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(display_frame, (x, y), (x + w, y + h), (220, 220, 220), 1)
        cv2.putText(
            display_frame,
            label,
            (x + 12, y + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            text_color,
            2
        )

    status = f"Gamma {gamma:.2f} | CLAHE {clahe_clip:.1f}" if NIGHT_MODE_ENABLED else "Enhancement disabled"
    cv2.putText(
        display_frame,
        status,
        (10, NIGHT_ON_BTN[1] + NIGHT_ON_BTN[3] + 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 255) if NIGHT_MODE_ENABLED else (180, 180, 180),
        2
    )


def draw_controls_overlay(display_frame):
    lines = [
        "Controls",
        "LMB: add road point",
        "RMB: clear current points",
        "ENTER: save current road",
        "S: save roads to disk",
        "C: delete saved roads file",
        "c: clear roads from memory",
        "ESC: exit",
    ]

    x = 10
    line_h = 20
    panel_w = 250
    panel_h = 12 + line_h * len(lines) + 8
    y = max(10, display_frame.shape[0] - panel_h - 10)

    overlay = display_frame.copy()
    cv2.rectangle(overlay, (x, y), (x + panel_w, y + panel_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, display_frame, 0.45, 0, display_frame)
    cv2.rectangle(display_frame, (x, y), (x + panel_w, y + panel_h), (200, 200, 200), 1)

    for i, line in enumerate(lines):
        color = (0, 255, 255) if i == 0 else (230, 230, 230)
        cv2.putText(
            display_frame,
            line,
            (x + 10, y + 24 + i * line_h),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1
        )

def parse_args():
    p = argparse.ArgumentParser("Enhanced Traffic Congestion Detector")
    p.add_argument("--video", required=True, help="Video path or 0 for webcam")
    p.add_argument("--model", default="yolov8s.pt")
    p.add_argument("--conf", type=float, default=0.18)
    p.add_argument("--device", default="cpu")
    p.add_argument("--imgsz", type=int, default=896)
    p.add_argument("--night-mode", choices=["off", "on"], default="on")
    p.add_argument("--gamma", type=float, default=1.35)
    p.add_argument("--clahe-clip", type=float, default=2.5)
    p.add_argument("--augment", action="store_true", help="Enable test-time augmentation (slower)")
    p.add_argument("--calibration-file", default="", help="Optional JSON with linear score calibration")
    p.add_argument(
        "--min-calibration-samples",
        type=int,
        default=200,
        help="Minimum labeled frames required in calibration file to enable it"
    )
    p.add_argument(
        "--allow-weak-calibration",
        action="store_true",
        help="Allow calibration even when fitted on too few labeled frames"
    )
    p.add_argument(
        "--dataset_create",
        "--dataset-create",
        action="store_true",
        dest="dataset_create",
        help="Enable dataset capture mode and save payload JSON to a local file"
    )
    p.add_argument(
        "--dataset-file",
        default=os.path.join(BASE_DIR, "dataset"),
        help="Output directory for dataset capture mode (one JSON file per payload)"
    )
    p.add_argument(
        "--dataset-interval",
        type=float,
        default=3.0,
        help="Dataset capture interval in seconds"
    )
    p.add_argument(
        "--junction-id",
        type=int,
        default=None,
        help="Junction/transaction id to use directly (skips interactive ID prompt).",
    )
    p.add_argument(
        "--camera-config",
        default="",
        help="Path to website-generated camera_config.json (preferred road source).",
    )
    return p.parse_args()


def get_lut_for_gamma(gamma):
    key = round(float(gamma), 2)
    if key not in LUT_CACHE:
        gamma = max(key, 0.1)
        LUT_CACHE[key] = np.array(
            [((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)],
            dtype=np.uint8
        )
    return LUT_CACHE[key]


def get_clahe(clip_limit):
    key = round(float(clip_limit), 1)
    if key not in CLAHE_CACHE:
        CLAHE_CACHE[key] = cv2.createCLAHE(clipLimit=max(key, 0.1), tileGridSize=(8, 8))
    return CLAHE_CACHE[key]


def preprocess_for_night(frame, gamma=1.35, clahe_clip=2.5):
    """
    Improve visibility in low-light frames before YOLO inference.
    Keeps geometry unchanged, so boxes still map to original frame.
    """
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = get_clahe(clahe_clip)
    l_eq = clahe.apply(l)

    enhanced = cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)

    lut = get_lut_for_gamma(gamma)
    enhanced = cv2.LUT(enhanced, lut)
    return enhanced

# =========================
# Road Selection Saver
# =========================

def save_roads_to_file():
    os.makedirs(ROADS_DIR, exist_ok=True)
    with open(ROADS_FILE, "w", encoding="utf-8") as f:
        json.dump(ROADS, f)


def load_roads_from_file():
    global ROADS
    if not os.path.exists(ROADS_FILE):
        return False

    try:
        with open(ROADS_FILE, "r") as f:
            ROADS = json.load(f)
        print(f"[INFO] Loaded {len(ROADS)} roads from {ROADS_FILE}")
        return True
    except Exception as e:
        print("[ERROR] Failed to load roads:", e)
        ROADS = []
        return False


def _normalize_polygon(points):
    polygon = []
    for item in points or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x = int(float(item[0]))
            y = int(float(item[1]))
        except Exception:
            continue
        polygon.append((x, y))
    if len(polygon) < MIN_ROAD_POINTS:
        return None
    return polygon


def _normalize_polygon_float(points):
    polygon = []
    for item in points or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x = float(item[0])
            y = float(item[1])
        except Exception:
            continue
        polygon.append((x, y))
    if len(polygon) < MIN_ROAD_POINTS:
        return None
    return polygon


def _scale_polygon(points, sx, sy):
    scaled = []
    for x, y in points:
        scaled.append((int(round(float(x) * sx)), int(round(float(y) * sy))))
    return scaled if len(scaled) >= MIN_ROAD_POINTS else None


def load_roads_from_camera_config(camera_config_path, frame_width=None, frame_height=None):
    global ROADS
    if not camera_config_path:
        return False
    if not os.path.exists(camera_config_path):
        return False

    try:
        with open(camera_config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print("[ERROR] Failed to read camera config:", e)
        return False

    cameras = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(cameras, list) or not cameras:
        return False

    camera = cameras[0] if isinstance(cameras[0], dict) else {}
    road_polygons = []

    fw = float(frame_width) if frame_width else None
    fh = float(frame_height) if frame_height else None

    road_drawings_norm = camera.get("roadDrawingsNormalized")
    if isinstance(road_drawings_norm, dict) and fw and fh:
        for _road_id, points in sorted(road_drawings_norm.items()):
            polygon_norm = _normalize_polygon_float(points)
            if not polygon_norm:
                continue
            polygon = _scale_polygon(polygon_norm, fw, fh)
            if polygon:
                road_polygons.append(polygon)

    if not road_polygons:
        road_drawings = camera.get("roadDrawings")
        frame_size = camera.get("frameSize") if isinstance(camera.get("frameSize"), dict) else {}
        export_w = float(frame_size.get("width") or 0)
        export_h = float(frame_size.get("height") or 0)
        if isinstance(road_drawings, dict):
            for _road_id, points in sorted(road_drawings.items()):
                polygon = _normalize_polygon(points)
                if not polygon:
                    continue
                if fw and fh and export_w > 0 and export_h > 0:
                    sx = fw / export_w
                    sy = fh / export_h
                    polygon = _scale_polygon(polygon, sx, sy)
                if polygon:
                    road_polygons.append(polygon)

    if not road_polygons:
        roads = camera.get("roads")
        if isinstance(roads, list):
            for points in roads:
                polygon = _normalize_polygon(points)
                if polygon:
                    road_polygons.append(polygon)

    if not road_polygons:
        return False

    ROADS = road_polygons[:MAX_ROADS]
    print(f"[INFO] Loaded {len(ROADS)} roads from camera config: {camera_config_path}")
    return True

# =========================
# Main
# =========================
def main():
    global NIGHT_MODE_ENABLED
    global JUNCTION_ID
    args = parse_args()
    NIGHT_MODE_ENABLED = args.night_mode == "on"
    calibrator = None
    if args.calibration_file:
        try:
            calibration_path = args.calibration_file
            if not os.path.isabs(calibration_path):
                calibration_path = os.path.abspath(os.path.join(BASE_DIR, calibration_path))
            calibrator = LinearScoreCalibrator.from_file(calibration_path)
            labeled_frames = int(getattr(calibrator, "meta", {}).get("labeled_score_frames", 0))
            if labeled_frames < args.min_calibration_samples and not args.allow_weak_calibration:
                print(
                    "[WARN] Calibration disabled:",
                    f"only {labeled_frames} labeled frames (min={args.min_calibration_samples})."
                )
                print("[WARN] Use --allow-weak-calibration to force it, but this may saturate scores.")
                calibrator = None
            print(
                "[INFO] Calibration enabled:",
                f"slope={calibrator.slope:.4f}, intercept={calibrator.intercept:.4f}"
            ) if calibrator is not None else None
        except Exception as e:
            print("[WARN] Failed to load calibration file:", e)
            calibrator = None

    model_path = args.model
    if not os.path.isabs(model_path):
        model_path = os.path.abspath(os.path.join(BASE_DIR, model_path))
    if not os.path.exists(model_path):
        print("ERROR: model file not found:", model_path)
        return

    print("Loading model:", model_path)
    model = YOLO(model_path)
    vehicle_class_ids = get_vehicle_class_ids(model.names)
    if vehicle_class_ids:
        print(f"[INFO] Inference class filter active: {vehicle_class_ids}")
    else:
        print("[INFO] Inference class filter disabled (using all classes)")
    print(f"Night mode: {'ON' if NIGHT_MODE_ENABLED else 'OFF'} | conf={args.conf} | imgsz={args.imgsz}")
    
    if args.video == "0":
        video_source = 0
    else:
        raw_video = str(args.video).strip()
        video_source = raw_video
        if not os.path.isabs(video_source):
            candidate_paths = [
                os.path.abspath(video_source),
                os.path.abspath(os.path.join(BASE_DIR, video_source)),
                os.path.abspath(os.path.join(PROJECT_ROOT, video_source)),
                os.path.abspath(os.path.join(VIDEO_DIR, video_source)),
                os.path.abspath(os.path.join(VIDEO_DIR, os.path.basename(video_source))),
            ]
            existing = next((p for p in candidate_paths if os.path.exists(p)), None)
            video_source = existing if existing else os.path.join(VIDEO_DIR, os.path.basename(video_source))

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
            print("ERROR: cannot open video source")
            return
    
    if args.junction_id is not None:
        JUNCTION_ID = int(args.junction_id)
        save_junction_id(JUNCTION_ID)
    else:
        prompt_junction_id(cap)

    print(f"[INFO] Using Junction ID: {JUNCTION_ID}")
    
    window_name = "Traffic Congestion Predictor"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    frame_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    frame_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    loaded_from_camera_config = load_roads_from_camera_config(
        args.camera_config,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    if not loaded_from_camera_config:
        load_roads_from_file()

    # =========================
    # API / TEST SEND TIMING
    # =========================
    last_api_send = 0
    API_INTERVAL = 20  # seconds
    api_thread = None
    last_dataset_save = 0
    dataset_write_error = False
    dataset_output_announced = False
    
    road_monitors = []
    frames = 0
    start_time = datetime.now()
    
    print("\n=== CONTROLS ===")
    print("Left click: Add road corner (4 corners per road)")
    print("Right click: Clear all roads")
    print("UI buttons: Toggle Night ON/OFF")
    print("ESC: Exit")
    print("================\n")
    if args.dataset_create:
        print(
            f"[DATASET] Enabled | interval={args.dataset_interval:.1f}s | file={args.dataset_file}"
        )
    
    while True:
        loop_start = time.time()
        
        ret, frame = cap.read()
        if not ret:
            break
        
        frames += 1
        
        # Initialize monitors when roads are defined
        if len(ROADS) != len(road_monitors):
            road_monitors = [RoadMonitor(road, i+1) for i, road in enumerate(ROADS)]
        
        # Run detection
        if NIGHT_MODE_ENABLED:
            inference_frame = preprocess_for_night(
                frame, gamma=args.gamma, clahe_clip=args.clahe_clip
            )
            gamma_used = args.gamma
            clahe_used = args.clahe_clip
        else:
            inference_frame = frame
            gamma_used = 1.0
            clahe_used = 0.0

        results = model.predict(
            source=inference_frame,
            conf=args.conf,
            imgsz=args.imgsz,
            device=args.device,
            classes=vehicle_class_ids if vehicle_class_ids else None,
            augment=args.augment,
            verbose=False
        )
        
        # Parse all detections
        all_detections = parse_detections(results[0], VEHICLE_CLASSES)
        
        detections_by_road = [[] for _ in road_monitors]
        outside_detections = []
        for det in all_detections:
            matched = False
            for idx, monitor in enumerate(road_monitors):
                if point_in_monitor_roi(det['centroid'], monitor):
                    detections_by_road[idx].append(det)
                    matched = True
            if not matched:
                outside_detections.append(det)

        # Process each road
        for idx, monitor in enumerate(road_monitors):
            detections_in_roi = detections_by_road[idx]

            # Print to cmd
            raw_score = monitor.compute_score(detections_in_roi, frame)
            if calibrator is not None:
                monitor.final_score = calibrator.apply(raw_score)
            monitor.log_to_console(interval=5)
            
            # Draw detections
            for det in detections_in_roi:
                x1, y1, x2, y2 = det['bbox']
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.circle(frame, det['centroid'], 4, (0, 255, 0), -1)
        
        # Draw detections outside ROIs in red
        for det in outside_detections:
            x1, y1, x2, y2 = det['bbox']
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        
        # FPS counter
        fps = 1.0 / max(time.time() - loop_start, 1e-6)
        fps_ratio = fps / TARGET_FPS

        # Draw UI
        draw_ui(frame, road_monitors,fps_ratio)
        # Display
        frame_show = cv2.resize(frame, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE)
        draw_mode_buttons(frame_show, gamma_used, clahe_used)
        draw_controls_overlay(frame_show)
        cv2.imshow(window_name, frame_show)
        
        # Frame rate limiting
        elapsed = time.time() - loop_start
        if FRAME_TIME > elapsed:
            time.sleep(FRAME_TIME - elapsed)
        
        key = cv2.waitKey(1) & 0xFF

        # ENTER → finalize road 
        if key == 13:
            if MIN_ROAD_POINTS <= len(CURRENT_ROAD) <= MAX_ROAD_POINTS:
                if len(ROADS) < MAX_ROADS:
                    ROADS.append(CURRENT_ROAD.copy())
                    CURRENT_ROAD.clear()
                    print(f"Road {len(ROADS)} added")
                else:
                    print("Max road limit reached")
            else:
                print("Road must have at least 3 points")

        # Shift + S → save roads to disk
        elif key == ord('S'):
            save_roads_to_file()
            print("Road selection saved")

        # Shift + C → delete saved roads from disk
        elif key == ord('C'):
            if os.path.exists(ROADS_FILE):
                os.remove(ROADS_FILE)
                print("Saved road selection deleted from disk")
            else:
                print("No saved road file to delete")

        # c → clear roads from memory only
        elif key == ord('c'):
            ROADS.clear()
            CURRENT_ROAD.clear()
            print("Roads cleared from memory")

        # ESC → exit
        elif key == 27:
            break

        # =========================
        # Send road data (every x seconds)
        # =========================
        now = time.time()
        if now - last_api_send >= API_INTERVAL:
            if api_thread is None or not api_thread.is_alive():
                payload = build_traffic_payload(JUNCTION_ID, road_monitors)
                api_thread = threading.Thread(
                    target=send_traffic_payload, args=(payload,), daemon=True
                )
                api_thread.start()
            else:
                print("[API INFO] Previous send still in progress, skipping this interval")
            last_api_send = now

        if args.dataset_create and now - last_dataset_save >= args.dataset_interval:
            payload = build_traffic_payload(JUNCTION_ID, road_monitors)
            try:
                saved_to = append_dataset_payload(payload, args.dataset_file)
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


    
    cap.release()
    cv2.destroyAllWindows()
    
    # Final stats
    elapsed = (datetime.now() - start_time).total_seconds()
    print("\n=== SESSION SUMMARY ===")
    print(f"Frames processed: {frames}")
    print(f"Average FPS: {frames / elapsed:.2f}" if elapsed > 0 else "N/A")
    
    for monitor in road_monitors:
        print(f"\nRoad {monitor.road_id} Final Stats:")
        print(f"  Final Score: {monitor.final_score}/100")

if __name__ == "__main__":
    main()
