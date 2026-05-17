# GreenWave

GreenWave is an intelligent traffic optimization platform developed as a term project.  
It combines traffic simulation, camera-based vehicle analysis, backend services, and a web interface to support data-driven traffic signal planning and monitoring.

The main goal of GreenWave is to explore how adaptive traffic control can reduce congestion by:

- Detecting and estimating traffic flow from camera feeds
- Running simulation scenarios with SUMO-based workflows
- Serving processed data through backend APIs
- Presenting insights and controls through a frontend dashboard
  
## Term Project Team

This project is the term project of:

- Müslüm Türker Kırtız 
- Yaren Atılgan
- Münevver Zeynep Çorumluoğlu
- Tuana Korkmazyurek

## Project Modules

- `algorithm_sumo`  
Contains traffic control logic, simulation experiments, and SUMO-related integration scripts.

- `camera_tests`  
Includes vehicle detection tests, calibration files, benchmark utilities, and camera-oriented experimentation code.

- `GreenWaveAPI`  
Provides .NET-based API services and backend domain/application layers for traffic-related operations.

- `greenwave_site`  
Contains web-facing components:
  - `backend_greenwave`: Python backend and simulation-related utilities
  - `frontend_greenwave`: Frontend dashboard and UI pages
  - `database_api`: Database-oriented API utilities

## Repository Structure

```text
GreenWave/
├── algorithm_sumo/
├── camera_tests/
├── GreenWaveAPI/
├── greenwave_site/
├── fake_API.py
├── requirements-all-modules.txt
└── README.md
```

## Technologies

- Python (simulation scripts, camera tests, backend utilities)
- SUMO (traffic simulation workflows)
- .NET (API project in `GreenWaveAPI`)
- JavaScript/React tooling (frontend in `greenwave_site/frontend_greenwave`)

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd GreenWave
```

### 2. Install dependencies

Depending on which module you want to run:

- Python modules:
```bash
pip install -r requirements-all-modules.txt
```

- Frontend:
```bash
cd greenwave_site/frontend_greenwave
npm install
```

- .NET API:
```bash
cd GreenWaveAPI
dotnet restore
```

## Running Modules (Examples)

- Camera test script:
```bash
python camera_tests/scripts/vehicle_detection_test.py
```

- Python backend (example):
```bash
python greenwave_site/backend_greenwave/app.py
```

- .NET API (example):
```bash
dotnet run --project GreenWaveAPI/GreewnWaveAPI/GreenWaveAPI.csproj
```

## Notes

- This repository includes experimental and development-oriented modules.
- Some workflows rely on local tools and assets (for example SUMO, model files, or camera input data).
- Large generated/runtime artifacts are intentionally excluded via `.gitignore` to keep the repository code-focused.
