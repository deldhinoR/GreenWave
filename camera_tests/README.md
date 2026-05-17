# GreenWave Camera Detection Scripts

This project contains Python scripts for vehicle detection and basic congestion analysis using YOLO.

## What is included

- `scripts/vehicle_detection_test.py`: Main local detection script.
- `scripts/vehicle_detection_test_colab.py`: Colab-friendly variant.
- `scripts/congestion_benchmark.py`: Benchmark/analysis helper.
- `scripts/*.json`: Configuration and template files.

## Quick setup

1. Install Python 3.10 or newer.
2. Install dependencies:

```bash
pip install ultralytics opencv-python numpy
```

3. Keep model weights locally (for example `yolov8s.pt`).
4. Run scripts from the `camera_tests` folder.

## Basic usage

```bash
python scripts/vehicle_detection_test.py --model yolov8s.pt
```

If needed, pass your input source argument (webcam index or video path) based on your script options.

## Typical workflow

1. Prepare your camera or video input.
2. Run detection with the selected model.
3. Review detections and metrics.
4. Adjust thresholds/config JSON files.
5. Re-run and compare results.

## Repository notes

- YOLO model files (`*.pt`) are ignored.
- `scripts/footage/` is ignored.
- `scripts/dataset/` is ignored.
- `scripts/__pycache__/` is ignored.

