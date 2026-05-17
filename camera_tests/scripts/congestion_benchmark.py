import argparse
import json
import math
import os
from typing import Dict, List, Tuple

import cv2
import numpy as np

import vehicle_detection_test as vdt


def parse_weight_override(raw: str) -> Dict[str, float]:
    override = {}
    if not raw:
        return override

    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"Invalid weight pair: {pair}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if key not in vdt.WEIGHTS:
            raise ValueError(f"Unknown weight key: {key}. Allowed: {list(vdt.WEIGHTS.keys())}")
        override[key] = float(value.strip())
    return override


def ranks(values: List[float]) -> List[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    out = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[indexed[k][0]] = avg_rank
        i = j + 1
    return out


def spearman_corr(y_true: List[float], y_pred: List[float]) -> float:
    if len(y_true) < 2:
        return 0.0
    rt = np.array(ranks(y_true), dtype=np.float64)
    rp = np.array(ranks(y_pred), dtype=np.float64)
    rt -= rt.mean()
    rp -= rp.mean()
    denom = np.linalg.norm(rt) * np.linalg.norm(rp)
    if denom == 0:
        return 0.0
    return float(np.dot(rt, rp) / denom)


def to_bucket(score: float) -> str:
    if score < 34:
        return "low"
    if score < 67:
        return "medium"
    return "high"


def safe_detection(det: dict) -> dict:
    if "bbox_area" not in det:
        if "bbox" in det and len(det["bbox"]) == 4:
            x1, y1, x2, y2 = det["bbox"]
            det["bbox_area"] = max(0.0, float(x2 - x1) * float(y2 - y1))
        else:
            det["bbox_area"] = 0.0
    if "centroid" not in det:
        if "bbox" in det and len(det["bbox"]) == 4:
            x1, y1, x2, y2 = det["bbox"]
            det["centroid"] = [int((x1 + x2) / 2), int((y1 + y2) / 2)]
        else:
            det["centroid"] = [0, 0]
    det["class"] = vdt.normalize_class_name(det.get("class", "car"))
    return det


def run_trace(trace: dict, disable_ambulance: bool) -> List[dict]:
    road_id = int(trace.get("road_id", 1))
    fps = int(trace.get("fps", vdt.TARGET_FPS))
    road_area = float(trace.get("road_area", 180000.0))
    h = max(100, int(math.sqrt(road_area)))
    w = max(100, int(road_area / h))
    polygon = [[0, 0], [w, 0], [w, h], [0, h]]

    old_target_fps = vdt.TARGET_FPS
    vdt.TARGET_FPS = fps
    monitor = vdt.RoadMonitor(polygon, road_id=road_id)
    monitor.area = road_area
    monitor.max_capacity = max(5, int(road_area / 18000))

    rows: List[dict] = []
    blank = np.zeros((h, w, 3), dtype=np.uint8)

    for frame in trace.get("frames", []):
        detections = [safe_detection(dict(d)) for d in frame.get("detections", [])]
        score = monitor.compute_score(
            detections=detections,
            frame=None if disable_ambulance else blank,
            enable_ambulance=not disable_ambulance
        )
        gt_score = frame.get("ground_truth_score")
        gt_bucket = frame.get("ground_truth_bucket")
        rows.append({
            "pred_score": int(score),
            "gt_score": float(gt_score) if gt_score is not None else None,
            "gt_bucket": str(gt_bucket).strip().lower() if gt_bucket is not None else None
        })

    vdt.TARGET_FPS = old_target_fps
    return rows


def fit_linear_calibration(y_pred: List[float], y_true: List[float]) -> dict:
    if len(y_pred) < 2:
        return {"slope": 1.0, "intercept": 0.0}

    xp = np.array(y_pred, dtype=np.float64)
    yt = np.array(y_true, dtype=np.float64)
    x_mean = xp.mean()
    y_mean = yt.mean()
    denom = np.sum((xp - x_mean) ** 2)
    if denom == 0:
        return {"slope": 1.0, "intercept": float(y_mean - x_mean)}
    slope = float(np.sum((xp - x_mean) * (yt - y_mean)) / denom)
    intercept = float(y_mean - slope * x_mean)
    return {"slope": slope, "intercept": intercept}


def apply_linear_calibration(values: List[float], calibration: dict) -> List[float]:
    slope = float(calibration.get("slope", 1.0))
    intercept = float(calibration.get("intercept", 0.0))
    return [float(np.clip(slope * v + intercept, 0, 100)) for v in values]


def evaluate(dataset: dict, disable_ambulance: bool, fit_calibration: bool) -> dict:
    traces = dataset.get("traces", [])
    all_pred_scores: List[float] = []
    score_pairs: List[Tuple[float, float]] = []
    bucket_pairs: List[Tuple[str, str]] = []
    per_trace = []

    for trace in traces:
        rows = run_trace(trace, disable_ambulance)
        pred_scores = [float(r["pred_score"]) for r in rows]

        all_pred_scores.extend(pred_scores)

        for r in rows:
            if r["gt_score"] is not None:
                score_pairs.append((float(r["pred_score"]), float(r["gt_score"])))
            if r["gt_bucket"] is not None:
                bucket_pairs.append((to_bucket(float(r["pred_score"])), r["gt_bucket"]))

        per_trace.append({
            "name": trace.get("name", f"road_{trace.get('road_id', 1)}"),
            "frames": len(trace.get("frames", [])),
            "pred_mean": float(np.mean(pred_scores)) if pred_scores else 0.0,
            "pred_max": int(max(pred_scores)) if pred_scores else 0,
            "pred_min": int(min(pred_scores)) if pred_scores else 0
        })

    metrics = {
        "traces": len(traces),
        "scored_frames": len(all_pred_scores),
        "labeled_score_frames": len(score_pairs),
        "labeled_bucket_frames": len(bucket_pairs),
        "per_trace": per_trace
    }

    if score_pairs:
        y_pred = np.array([p[0] for p in score_pairs], dtype=np.float64)
        y_true = np.array([p[1] for p in score_pairs], dtype=np.float64)
        mae = np.mean(np.abs(y_true - y_pred))
        rmse = math.sqrt(np.mean((y_true - y_pred) ** 2))
        metrics["mae"] = float(mae)
        metrics["rmse"] = float(rmse)
        metrics["spearman_rank"] = float(spearman_corr(y_true.tolist(), y_pred.tolist()))

        if fit_calibration:
            calibration = fit_linear_calibration(y_pred.tolist(), y_true.tolist())
            y_pred_cal = np.array(
                apply_linear_calibration(y_pred.tolist(), calibration),
                dtype=np.float64
            )
            metrics["calibration"] = calibration
            metrics["calibrated_mae"] = float(np.mean(np.abs(y_true - y_pred_cal)))
            metrics["calibrated_rmse"] = float(math.sqrt(np.mean((y_true - y_pred_cal) ** 2)))

            if bucket_pairs:
                calibrated_bucket_pairs = [
                    (to_bucket(v), gt)
                    for v, (_, gt) in zip(y_pred_cal.tolist(), bucket_pairs)
                ]
                correct = sum(int(p == t) for p, t in calibrated_bucket_pairs)
                metrics["calibrated_bucket_accuracy"] = float(correct / len(calibrated_bucket_pairs))

    if bucket_pairs:
        correct = sum(int(pred == true) for pred, true in bucket_pairs)
        metrics["bucket_accuracy"] = float(correct / len(bucket_pairs))

    return metrics


def print_summary(metrics: dict):
    print("\n=== Congestion Benchmark Summary ===")
    print(f"Traces: {metrics['traces']}")
    print(f"Frames processed: {metrics['scored_frames']}")
    print(f"Labeled score frames: {metrics['labeled_score_frames']}")
    print(f"Labeled bucket frames: {metrics['labeled_bucket_frames']}")

    if "mae" in metrics:
        print(f"MAE: {metrics['mae']:.2f}")
        print(f"RMSE: {metrics['rmse']:.2f}")
        print(f"Spearman rank: {metrics['spearman_rank']:.3f}")
    if "bucket_accuracy" in metrics:
        print(f"Bucket accuracy: {metrics['bucket_accuracy'] * 100:.1f}%")
    if "calibration" in metrics:
        cal = metrics["calibration"]
        print("\nCalibration fit:")
        print(f"score_calibrated = clip({cal['slope']:.4f} * score + {cal['intercept']:.4f}, 0, 100)")
        print(f"Calibrated MAE: {metrics['calibrated_mae']:.2f}")
        print(f"Calibrated RMSE: {metrics['calibrated_rmse']:.2f}")
        if "calibrated_bucket_accuracy" in metrics:
            print(f"Calibrated bucket accuracy: {metrics['calibrated_bucket_accuracy'] * 100:.1f}%")

    print("\nPer trace:")
    for row in metrics["per_trace"]:
        print(
            f"- {row['name']}: frames={row['frames']}, "
            f"pred_mean={row['pred_mean']:.1f}, range=[{row['pred_min']}, {row['pred_max']}]"
        )


def parse_args():
    p = argparse.ArgumentParser("Congestion score benchmark runner")
    p.add_argument(
        "--dataset",
        required=True,
        help="Path to benchmark dataset JSON"
    )
    p.add_argument(
        "--weights",
        default="",
        help="Override weights, e.g. density=20,occupancy=40,stagnation=30,heavy_vehicle=10"
    )
    p.add_argument(
        "--disable-ambulance",
        action="store_true",
        help="Disable ambulance heuristic during benchmark replay"
    )
    p.add_argument(
        "--fit-calibration",
        action="store_true",
        help="Fit a linear calibration score'=a*score+b against labeled score frames"
    )
    p.add_argument(
        "--out",
        default="",
        help="Optional output JSON report path"
    )
    p.add_argument(
        "--save-calibration",
        default="",
        help="Optional path to save fitted calibration JSON"
    )
    return p.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.dataset):
        raise FileNotFoundError(f"Dataset not found: {args.dataset}")

    with open(args.dataset, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    override = parse_weight_override(args.weights)
    if override:
        vdt.WEIGHTS.update(override)
        print(f"[INFO] Using overridden weights: {vdt.WEIGHTS}")
    else:
        print(f"[INFO] Using default weights: {vdt.WEIGHTS}")

    metrics = evaluate(
        dataset,
        disable_ambulance=args.disable_ambulance,
        fit_calibration=args.fit_calibration
    )
    print_summary(metrics)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        print(f"\n[INFO] Saved report: {args.out}")

    if args.save_calibration:
        if "calibration" not in metrics:
            print("\n[WARN] Calibration was not fitted (use --fit-calibration and labeled score frames).")
        else:
            payload = {
                "method": "linear_affine",
                "slope": metrics["calibration"]["slope"],
                "intercept": metrics["calibration"]["intercept"],
                "clip_min": 0,
                "clip_max": 100,
                "labeled_score_frames": metrics.get("labeled_score_frames", 0)
            }
            with open(args.save_calibration, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            print(f"[INFO] Saved calibration: {args.save_calibration}")


if __name__ == "__main__":
    main()
