import os
import argparse
import traci
import requests
import time

try:
    import serial
except ImportError:
    serial = None

from algorithm.algorithm import AdaptiveController
from db import (
    init_db,
    log_step,
    log_decision,
    create_experiment,
    log_light_status,
    log_alert,
    log_experiment_runtime_kpi,
)
from controller.vision_adapter import compute_phase_pressure, VisionDatasetReader


# PATH CONFIGURATION

SUMO_BINARY_HEADLESS = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
SUMO_BINARY_GUI = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
SIM_FOLDER = "simulation"
SUMO_CFG = os.path.join(SIM_FOLDER, "kolej.sumocfg")
VISION_API_URL_TEMPLATE = "http://localhost:5185/api/Sumo/traffic/{junction_id}"


# TRAFFIC LIGHT CONFIGURATION

TL_ID = "clusterJ0_J1_J11_J2_#4more"


class ArduinoPhaseBridge:
    def __init__(self, port, baudrate=9600, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.conn = None
        self.last_phase = None
        self.last_send_time = 0.0

    def connect(self):
        if serial is None:
            raise RuntimeError(
                "pyserial is not installed. Run: pip install pyserial"
            )
        self.conn = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        # Allow Arduino auto-reset to complete before first command.
        time.sleep(2)
        self.send_phase(-1, force=True)  # all-red safety state at startup

    def send_phase(self, phase, force=False):
        if self.conn is None:
            return
        now = time.time()
        if not force and phase == self.last_phase and (now - self.last_send_time) < 1.0:
            return
        self.conn.write(f"P:{phase}\n".encode("ascii"))
        self.last_phase = phase
        self.last_send_time = now

    def close(self):
        if self.conn is None:
            return
        try:
            self.send_phase(-1, force=True)  # fallback to all-red on shutdown
        finally:
            self.conn.close()
            self.conn = None

def build_dynamic_phase_config(tl_id):
    controlled_links = traci.trafficlight.getControlledLinks(tl_id)
    program_logics = traci.trafficlight.getAllProgramLogics(tl_id)

    if not program_logics:
        raise RuntimeError(f"No traffic light program found for TLS '{tl_id}'")

    logic = program_logics[0]
    phase_defs = []

    for tls_phase_idx, phase in enumerate(logic.phases):
        lanes = set()

        for signal_idx, signal_state in enumerate(phase.state):
            if signal_state not in ("G", "g"):
                continue

            if signal_idx >= len(controlled_links):
                continue

            for link in controlled_links[signal_idx]:
                if not link:
                    continue
                in_lane = link[0]
                if in_lane:
                    lanes.add(in_lane)

        # Skip non-green transition phases (yellow/all-red) for controller logic.
        if lanes:
            phase_defs.append({
                "tls_phase": tls_phase_idx,
                "lanes": sorted(lanes),
                "name": f"TLS phase {tls_phase_idx} - dynamic GREEN",
            })

    if not phase_defs:
        raise RuntimeError(f"No green phases with lanes found for TLS '{tl_id}'")

    return phase_defs


def get_logical_phase_from_tls(tls_phase, phase_defs, fallback=0):
    for logical_idx, phase_def in enumerate(phase_defs):
        if phase_def["tls_phase"] == tls_phase:
            return logical_idx
    return fallback


def get_lane_phase_pressure(phase_defs):
    lane_pressure = {phase: 0.0 for phase in range(len(phase_defs))}

    for phase, phase_def in enumerate(phase_defs):
        for lane in phase_def["lanes"]:
            lane_pressure[phase] += traci.lane.getLastStepHaltingNumber(lane)

    return lane_pressure


def blend_phase_pressure(vision_pressure, lane_pressure, vision_weight=0.7):
    wv = max(0.0, min(1.0, vision_weight))
    wl = 1.0 - wv

    return {
        phase: (wv * float(vision_pressure.get(phase, 0.0)))
        + (wl * float(lane_pressure.get(phase, 0.0)))
        for phase in lane_pressure.keys()
    }


def sanitize_vision_signal(vision_queues, emergency_phase, phase_count):
    valid_phases = set(range(phase_count))
    sanitized = {
        phase: float(value)
        for phase, value in vision_queues.items()
        if phase in valid_phases
    }
    for phase in valid_phases:
        sanitized.setdefault(phase, 0.0)

    safe_emergency = emergency_phase if emergency_phase in valid_phases else None
    return sanitized, safe_emergency


def collect_network_state():
    vehicle_ids = traci.vehicle.getIDList()

    if not vehicle_ids:
        return {
            "vehicle_count": 0,
            "sum_waiting_time": 0.0,
            "avg_speed": 0.0,
            "halting_count": 0,
        }

    sum_waiting_time = 0.0
    sum_speed = 0.0
    halting_count = 0

    for veh_id in vehicle_ids:
        speed = traci.vehicle.getSpeed(veh_id)
        waiting = traci.vehicle.getAccumulatedWaitingTime(veh_id)

        sum_speed += speed
        sum_waiting_time += waiting

        if speed < 0.1:
            halting_count += 1

    return {
        "vehicle_count": len(vehicle_ids),
        "sum_waiting_time": sum_waiting_time,
        "avg_speed": sum_speed / len(vehicle_ids),
        "halting_count": halting_count,
    }


def get_remaining_phase_time(tl_id):
    try:
        phase_duration = float(traci.trafficlight.getPhaseDuration(tl_id))
        spent_duration = float(traci.trafficlight.getSpentDuration(tl_id))
        return max(0, int(phase_duration - spent_duration))
    except Exception:
        # Fallback for controllers/programs where phase duration APIs are unavailable.
        return max(
            0,
            int(
                traci.trafficlight.getNextSwitch(tl_id)
                - traci.simulation.getTime()
            )
        )


def extract_vision_payload(response_json):
    if not isinstance(response_json, dict):
        return None

    if isinstance(response_json.get("roads"), list):
        return response_json

    for key in ("data", "payload", "result"):
        candidate = response_json.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("roads"), list):
            return candidate

    return None


def fetch_vision_sample(api_url_template, junction_id, timeout=5):
    url = api_url_template.format(junction_id=junction_id)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return extract_vision_payload(response.json())


def run_simulation(
    mode="adaptive",
    max_steps=None,
    use_vision=False,
    dataset_dir="dataset",
    vision_loop=True,
    use_gui=False,
    vision_weight=0.7,
    adaptive_min_switch_gap=12,
    vision_source="dataset",
    vision_api_url_template=VISION_API_URL_TEMPLATE,
    vision_junction_id="J0",
    sumo_cfg_path=SUMO_CFG,
    tl_id=TL_ID,
    arduino_port=None,
    arduino_baud=9600,
    realtime=False,
    seed=42,
    debug=False,
    debug_every=5,
    experiment_id_override=None,
):
    print(
        f"\nSimulation started | MODE = {mode.upper()} | "
        f"VISION = {use_vision} | DATASET = {dataset_dir} | "
        f"SUMO_GUI = {use_gui} | REALTIME = {realtime}"
    )
    if debug:
        print(f"Debug mode: ON (every {debug_every} steps)")

    init_db()
    experiment_id = create_experiment(preferred_id=experiment_id_override)
    print(f"Experiment ID: {experiment_id}")

    controller = None
    arduino_bridge = None

    if mode == "adaptive":
        controller = None

    elif mode == "fixed":
        controller = None

    else:
        raise ValueError("Invalid mode. Use 'adaptive' or 'fixed'.")

    sumo_binary = SUMO_BINARY_GUI if use_gui else SUMO_BINARY_HEADLESS

    sumo_cmd = [
        sumo_binary,
        "-c", sumo_cfg_path,
        "--start",
        "--quit-on-end",
        "--seed", str(seed),
    ]

    vision_reader = None

    if use_vision and vision_source == "dataset":
        try:
            vision_reader = VisionDatasetReader(dataset_dir=dataset_dir, loop=vision_loop)

            print(
                f"Vision dataset loaded: {len(vision_reader.files)} JSON file(s) "
                f"from '{os.path.abspath(dataset_dir)}'"
            )

            if max_steps is None and not vision_loop:
                max_steps = len(vision_reader.files)

                print(
                    f"Auto steps enabled (non-loop): max_steps={max_steps} "
                    f"(dataset file count)"
                )

        except FileNotFoundError as exc:
            print(f"Vision dataset error: {exc}")
            print("Falling back to SUMO lane counts.")
    elif use_vision and vision_source == "api":
        print(
            f"Vision API source enabled: "
            f"{vision_api_url_template.format(junction_id=vision_junction_id)}"
        )

    if max_steps is None:
        max_steps = 1000

    traci.start(sumo_cmd)

    if arduino_port:
        try:
            arduino_bridge = ArduinoPhaseBridge(
                port=arduino_port,
                baudrate=arduino_baud,
                timeout=1.0,
            )
            arduino_bridge.connect()
            print(f"Arduino bridge connected on {arduino_port} @ {arduino_baud}")
        except Exception as exc:
            print(f"Arduino bridge disabled: {exc}")
            arduino_bridge = None

    available_tls_ids = traci.trafficlight.getIDList()
    if not available_tls_ids:
        raise RuntimeError("No traffic lights found in loaded SUMO network.")

    print(f"Available TLS IDs: {', '.join(available_tls_ids)}")

    if tl_id not in available_tls_ids:
        raise RuntimeError(
            f"Configured TLS '{tl_id}' not found in this network. "
            f"Available TLS IDs: {', '.join(available_tls_ids)}"
        )

    phase_defs = build_dynamic_phase_config(tl_id)
    phase_count = len(phase_defs)
    print(f"Selected TLS ID: {tl_id}")
    print(f"Dynamic controllable phase count: {phase_count}")
    for idx, phase_def in enumerate(phase_defs):
        print(
            f"  Logical phase {idx} -> TLS phase {phase_def['tls_phase']} | "
            f"lanes={len(phase_def['lanes'])}: {', '.join(phase_def['lanes'])}"
        )

    if mode == "adaptive":
        controller = AdaptiveController(
            min_green=15,
            max_green=60,
            max_red_limit=90,
            phase_count=phase_count,
            alpha=1.5,
            beta=1.5,
            gamma=1.6,
            hysteresis_threshold=15,
            cooldown=6,
        )

        controller.max_red_observed = {
            p: 0 for p in range(controller.phase_count)
        }

    if mode == "adaptive":
        traci.trafficlight.setPhase(tl_id, phase_defs[0]["tls_phase"])

    step = 0
    last_switch_step = -10**9

    red_queue_history = []
    switch_count = 0
    # Prevent DB flood: log traffic light status on phase changes and sparse heartbeat.
    status_log_interval_steps = 10
    last_status_log_step = -status_log_interval_steps
    last_logged_phase = None
    net_wait_sum_history = []
    net_avg_speed_history = []
    halting_vehicle_history = []
    throughput_total = 0
    loop_started_at = time.perf_counter()
    prev_tls_phase = traci.trafficlight.getPhase(tl_id)

    try:
        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            try:
                traci.simulationStep()
            except traci.exceptions.FatalTraCIError:
                print("SUMO closed manually.")
                break

            step += 1
            current_tls_phase = traci.trafficlight.getPhase(tl_id)
            current_phase = get_logical_phase_from_tls(
                current_tls_phase,
                phase_defs,
            )

            if arduino_bridge is not None:
                arduino_bridge.send_phase(current_tls_phase)

            if realtime:
                target_elapsed = float(step)
                current_elapsed = time.perf_counter() - loop_started_at
                sleep_s = target_elapsed - current_elapsed
                if sleep_s > 0:
                    time.sleep(sleep_s)

            if use_vision:
                vision_json = None

                if vision_source == "dataset" and vision_reader is not None:
                    vision_json = vision_reader.next_sample()
                elif vision_source == "api":
                    try:
                        vision_json = fetch_vision_sample(
                            api_url_template=vision_api_url_template,
                            junction_id=vision_junction_id,
                        )
                    except requests.RequestException as exc:
                        print(f"Vision API request failed at step={step}: {exc}")
                    except ValueError as exc:
                        print(f"Vision API JSON parse failed at step={step}: {exc}")

                if vision_json is not None:
                    vision_queues, emergency_phase = compute_phase_pressure(vision_json)
                    vision_queues, emergency_phase = sanitize_vision_signal(
                        vision_queues,
                        emergency_phase,
                        phase_count,
                    )
                    lane_queues = get_lane_phase_pressure(phase_defs)

                    red_queues = blend_phase_pressure(
                        vision_queues,
                        lane_queues,
                        vision_weight=vision_weight,
                    )
                elif vision_source == "dataset" and vision_reader is not None and not vision_loop:
                    print(
                        f"Vision dataset exhausted at step={step}. "
                        "Stopping simulation to avoid zero-pressure tail."
                    )
                    break
                else:
                    lane_queues = get_lane_phase_pressure(phase_defs)
                    red_queues = lane_queues
                    emergency_phase = None

            else:
                red_queues = {p: 0 for p in range(phase_count)}
                emergency_phase = None

                for phase, phase_def in enumerate(phase_defs):
                    for lane in phase_def["lanes"]:
                        halting = traci.lane.getLastStepHaltingNumber(lane)
                        red_queues[phase] += halting

            total_q = sum(red_queues.values())
            red_queue_history.append(total_q)

            network_state = collect_network_state()

            net_wait_sum_history.append(network_state["sum_waiting_time"])
            net_avg_speed_history.append(network_state["avg_speed"])
            halting_vehicle_history.append(network_state["halting_count"])
            throughput_total += traci.simulation.getArrivedNumber()

            if mode == "adaptive":
                controller.update_red_times(current_phase)

                switch, reason = controller.should_switch(
                    current_phase,
                    red_queues,
                    emergency_phase
                )

                if debug and (step % debug_every == 0):
                    print(
                        f"[DEBUG] step={step} tls_phase={current_tls_phase} logical_phase={current_phase} "
                        f"remaining={get_remaining_phase_time(tl_id)}s totalQ={total_q:.2f} "
                        f"redQ={red_queues} emergency={emergency_phase} decision={reason} switch={switch}"
                    )

                if switch and (step - last_switch_step >= adaptive_min_switch_gap):
                    next_phase = controller.select_next_phase(
                        red_queues,
                        current_phase,
                        emergency_phase
                    )
                    if not (0 <= next_phase < phase_count):
                        print(
                            f"[WARN] Invalid next_phase={next_phase} for phase_count={phase_count}. "
                            f"Falling back to phase 0."
                        )
                        next_phase = 0

                    traci.trafficlight.setPhase(
                        tl_id,
                        phase_defs[next_phase]["tls_phase"]
                    )
                    if debug:
                        print(
                            f"[DEBUG] SWITCH applied at step={step}: logical {current_phase} -> {next_phase}, "
                            f"tls={phase_defs[next_phase]['tls_phase']}, reason={reason}"
                        )

                    switch_count += 1
                    last_switch_step = step

                    log_decision(
                        step,
                        "SWITCH",
                        reason,
                        total_q,
                        experiment_id,
                        selected_phase=next_phase,
                        green_duration=controller.min_green
                    )

            elif mode == "fixed":
                # In fixed mode, keep SUMO's own static TLS program/durations.
                if current_tls_phase != prev_tls_phase:
                    switch_count += 1
                    log_decision(
                        step,
                        "FIXED_SWITCH",
                        "SUMO static TLS phase transition",
                        total_q,
                        experiment_id,
                        selected_phase=current_tls_phase,
                        green_duration=get_remaining_phase_time(tl_id),
                    )

            log_step(
                step,
                current_phase,
                total_q,
                network_state["halting_count"],
                experiment_id
            )

            should_log_status = (
                last_logged_phase is None
                or current_phase != last_logged_phase
                or (step - last_status_log_step) >= status_log_interval_steps
            )
            if should_log_status:
                log_light_status(
                    experiment_id=experiment_id,
                    current_phase=current_phase,
                    light_status=phase_defs[current_phase]["name"],
                    remaining_time=get_remaining_phase_time(tl_id)
                )
                last_logged_phase = current_phase
                last_status_log_step = step

            if total_q >= 20:
                log_alert(
                    experiment_id=experiment_id,
                    alert_type="HIGH_TRAFFIC",
                    message=f"Traffic density is high. Total queue: {total_q}",
                    severity="HIGH"
                )

            if network_state["halting_count"] >= 15:
                log_alert(
                    experiment_id=experiment_id,
                    alert_type="LONG_WAITING",
                    message=f"Too many halted vehicles: {network_state['halting_count']}",
                    severity="MEDIUM"
                )

            if step % 200 == 0:
                print(
                    f"[{mode.upper()}] step={step} "
                    f"phase={current_phase} totalQ={total_q}"
                )
            prev_tls_phase = current_tls_phase

    finally:
        if arduino_bridge is not None:
            arduino_bridge.close()
        traci.close()

    print(f"\nSimulation finished | MODE = {mode.upper()}")

    avg_red_q = sum(red_queue_history) / len(red_queue_history) if red_queue_history else 0
    max_red_q = max(red_queue_history) if red_queue_history else 0

    avg_network_wait_sum = (
        sum(net_wait_sum_history) / len(net_wait_sum_history)
        if net_wait_sum_history else 0
    )

    avg_network_speed = (
        sum(net_avg_speed_history) / len(net_avg_speed_history)
        if net_avg_speed_history else 0
    )

    avg_halting_vehicles = (
        sum(halting_vehicle_history) / len(halting_vehicle_history)
        if halting_vehicle_history else 0
    )

    max_halting_vehicles = max(halting_vehicle_history) if halting_vehicle_history else 0

    metrics = {
        "avg_red_queue": avg_red_q,
        "max_red_queue": max_red_q,
        "switch_count": switch_count,
        "avg_network_wait_sum": avg_network_wait_sum,
        "avg_network_speed": avg_network_speed,
        "avg_halting_vehicles": avg_halting_vehicles,
        "max_halting_vehicles": max_halting_vehicles,
        "throughput_total": throughput_total,
    }

    if mode == "adaptive" and controller is not None:
        metrics["max_red_observed"] = max(controller.max_red_observed.values())

    print("\nMETRICS")
    print("--------------------------------")
    print(f"Input Avg Queue        : {metrics['avg_red_queue']:.2f}")
    print(f"Input Max Queue        : {metrics['max_red_queue']}")
    print(f"Avg Wait Sum (network) : {metrics['avg_network_wait_sum']:.2f}")
    print(f"Avg Speed (m/s)        : {metrics['avg_network_speed']:.2f}")
    print(f"Avg Halting Vehicles   : {metrics['avg_halting_vehicles']:.2f}")
    print(f"Max Halting Vehicles   : {metrics['max_halting_vehicles']}")
    print(f"Throughput (arrived)   : {metrics['throughput_total']}")
    print(f"Switch Count           : {metrics['switch_count']}")

    if "max_red_observed" in metrics:
        print(f"Max Red Observed       : {metrics['max_red_observed']}")

    # Algorithm-native runtime improvement KPI:
    # Compare current window waiting average against initial window waiting average.
    # This gives a per-experiment improvement metric even in adaptive-only runs.
    if net_wait_sum_history:
        window = min(60, len(net_wait_sum_history))
        baseline_wait = sum(net_wait_sum_history[:window]) / window
        current_wait = sum(net_wait_sum_history[-window:]) / window
        if baseline_wait > 0:
            congestion_improvement = ((baseline_wait - current_wait) / baseline_wait) * 100.0
        else:
            congestion_improvement = 0.0
        congestion_improvement = max(-100.0, min(100.0, congestion_improvement))
        log_experiment_runtime_kpi(
            experiment_id=experiment_id,
            congestion_improvement=congestion_improvement,
            baseline_wait=baseline_wait,
            current_wait=current_wait,
        )

    return metrics


def print_comparison(fixed_metrics, adaptive_metrics):
    print("\n===== COMPARISON RESULTS =====")
    print("--------------------------------------------------")
    print(f"Fixed Input Avg Queue        : {fixed_metrics['avg_red_queue']:.2f}")
    print(f"Adaptive Input Avg Queue     : {adaptive_metrics['avg_red_queue']:.2f}")
    print(f"Fixed Input Max Queue        : {fixed_metrics['max_red_queue']}")
    print(f"Adaptive Input Max Queue     : {adaptive_metrics['max_red_queue']}")
    print(f"Fixed Avg Wait Sum (network) : {fixed_metrics['avg_network_wait_sum']:.2f}")
    print(f"Adaptive Avg Wait Sum        : {adaptive_metrics['avg_network_wait_sum']:.2f}")
    print(f"Fixed Avg Speed (m/s)        : {fixed_metrics['avg_network_speed']:.2f}")
    print(f"Adaptive Avg Speed (m/s)     : {adaptive_metrics['avg_network_speed']:.2f}")
    print(f"Fixed Avg Halting Vehicles   : {fixed_metrics['avg_halting_vehicles']:.2f}")
    print(f"Adaptive Avg Halting Veh.    : {adaptive_metrics['avg_halting_vehicles']:.2f}")
    print(f"Fixed Throughput (arrived)   : {fixed_metrics['throughput_total']}")
    print(f"Adaptive Throughput          : {adaptive_metrics['throughput_total']}")
    print(f"Fixed Switch Count           : {fixed_metrics['switch_count']}")
    print(f"Adaptive Switch Count        : {adaptive_metrics['switch_count']}")

    if "max_red_observed" in adaptive_metrics:
        print(f"Adaptive Max Red Observed    : {adaptive_metrics['max_red_observed']}")

    if fixed_metrics["avg_network_wait_sum"] > 0:
        wait_improvement = (
            (fixed_metrics["avg_network_wait_sum"] - adaptive_metrics["avg_network_wait_sum"])
            / fixed_metrics["avg_network_wait_sum"]
        ) * 100

        print(f"\nWait Improvement (Adaptive vs Fixed): {wait_improvement:.2f}%")

    if fixed_metrics["avg_halting_vehicles"] > 0:
        halting_improvement = (
            (fixed_metrics["avg_halting_vehicles"] - adaptive_metrics["avg_halting_vehicles"])
            / fixed_metrics["avg_halting_vehicles"]
        ) * 100

        print(f"Halting Improvement                 : {halting_improvement:.2f}%")

    if fixed_metrics["throughput_total"] > 0:
        throughput_change = (
            (adaptive_metrics["throughput_total"] - fixed_metrics["throughput_total"])
            / fixed_metrics["throughput_total"]
        ) * 100

        print(f"Throughput Change                   : {throughput_change:.2f}%")


def compare_modes(
    max_steps=None,
    use_vision=False,
    dataset_dir="dataset",
    vision_loop=True,
    use_gui=False,
    vision_weight=0.7,
    adaptive_min_switch_gap=12,
    vision_source="dataset",
    vision_api_url_template=VISION_API_URL_TEMPLATE,
    vision_junction_id="J0",
    sumo_cfg_path=SUMO_CFG,
    tl_id=TL_ID,
    arduino_port=None,
    arduino_baud=9600,
    realtime=False,
    seed=42,
    debug=False,
    debug_every=5,
):
    print("\n===== RUNNING FIXED MODE =====")

    fixed_metrics = run_simulation(
        mode="fixed",
        max_steps=max_steps,
        use_vision=use_vision,
        dataset_dir=dataset_dir,
        vision_loop=vision_loop,
        use_gui=use_gui,
        vision_weight=vision_weight,
        adaptive_min_switch_gap=adaptive_min_switch_gap,
        vision_source=vision_source,
        vision_api_url_template=vision_api_url_template,
        vision_junction_id=vision_junction_id,
        sumo_cfg_path=sumo_cfg_path,
        tl_id=tl_id,
        arduino_port=arduino_port,
        arduino_baud=arduino_baud,
        realtime=realtime,
        seed=seed,
        debug=debug,
        debug_every=debug_every,
    )

    print("\n===== RUNNING ADAPTIVE MODE =====")

    adaptive_metrics = run_simulation(
        mode="adaptive",
        max_steps=max_steps,
        use_vision=use_vision,
        dataset_dir=dataset_dir,
        vision_loop=vision_loop,
        use_gui=use_gui,
        vision_weight=vision_weight,
        adaptive_min_switch_gap=adaptive_min_switch_gap,
        vision_source=vision_source,
        vision_api_url_template=vision_api_url_template,
        vision_junction_id=vision_junction_id,
        sumo_cfg_path=sumo_cfg_path,
        tl_id=tl_id,
        arduino_port=arduino_port,
        arduino_baud=arduino_baud,
        realtime=realtime,
        seed=seed,
        debug=debug,
        debug_every=debug_every,
    )

    print_comparison(fixed_metrics, adaptive_metrics)


def run_scenario_folders(
    dataset_root,
    mode="adaptive",
    max_steps=None,
    vision_loop=False,
    use_gui=False,
    vision_weight=0.7,
    adaptive_min_switch_gap=12,
    sumo_cfg_path=SUMO_CFG,
    tl_id=TL_ID,
    arduino_port=None,
    arduino_baud=9600,
    realtime=False,
    seed=42,
    debug=False,
    debug_every=5,
):
    root = os.path.abspath(dataset_root)

    scenario_dirs = [
        os.path.join(root, d)
        for d in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, d))
    ]

    if not scenario_dirs:
        raise FileNotFoundError(f"No scenario folders found in: {root}")

    print("\n===== RUNNING SCENARIO FOLDERS =====")

    results = []

    for scenario_dir in scenario_dirs:
        scenario_name = os.path.basename(scenario_dir)

        print(f"\n--- Scenario: {scenario_name} ---")

        metrics = run_simulation(
            mode=mode,
            max_steps=max_steps,
            use_vision=True,
            dataset_dir=scenario_dir,
            vision_loop=vision_loop,
            use_gui=use_gui,
            vision_weight=vision_weight,
            adaptive_min_switch_gap=adaptive_min_switch_gap,
            sumo_cfg_path=sumo_cfg_path,
            tl_id=tl_id,
            arduino_port=arduino_port,
            arduino_baud=arduino_baud,
            realtime=realtime,
            seed=seed,
            debug=debug,
            debug_every=debug_every,
        )

        results.append((scenario_name, metrics))

    print("\n===== SCENARIO SUMMARY =====")
    print("--------------------------------")

    for scenario_name, metrics in results:
        print(
            f"{scenario_name} | avgQ={metrics['avg_red_queue']:.2f} | "
            f"maxQ={metrics['max_red_queue']} | switch={metrics['switch_count']}"
        )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GreenWave simulation runner")

    parser.add_argument(
        "--mode",
        choices=["compare", "fixed", "adaptive"],
        default="compare",
        help="Simulation mode to run",
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Maximum simulation steps"
    )

    parser.add_argument(
        "--use-vision",
        action="store_true",
        help="Read congestion input from dataset JSON files",
    )

    parser.add_argument(
        "--dataset-dir",
        default="dataset",
        help="Directory containing JSON samples for vision input",
    )

    parser.add_argument(
        "--no-vision-loop",
        action="store_true",
        help="Stop consuming dataset when JSON files end, no loop",
    )

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Use SUMO GUI. Default is headless sumo.exe",
    )

    parser.add_argument(
        "--dataset-root",
        default=None,
        help="Root folder containing scenario subfolders.",
    )
    parser.add_argument(
        "--vision-source",
        choices=["dataset", "api"],
        default="dataset",
        help="Vision input source: local dataset JSON files or API.",
    )
    parser.add_argument(
        "--vision-api-url-template",
        default=VISION_API_URL_TEMPLATE,
        help="Vision API URL template. Must include {junction_id}.",
    )
    parser.add_argument(
        "--junction-id",
        default="1",
        help="Junction ID used in vision API URL template.",
    )

    parser.add_argument(
        "--vision-weight",
        type=float,
        default=0.7,
        help="Blend weight for vision pressure vs live lane pressure, 0..1.",
    )

    parser.add_argument(
        "--adaptive-min-switch-gap",
        type=int,
        default=12,
        help="Minimum step gap between adaptive phase switches.",
    )
    parser.add_argument(
        "--sumocfg",
        default=SUMO_CFG,
        help="Path to SUMO .sumocfg file for dynamic scenario loading.",
    )
    parser.add_argument(
        "--tl-id",
        default=TL_ID,
        help="Target SUMO traffic light ID. Falls back to first available TLS if not found.",
    )
    parser.add_argument(
        "--arduino-port",
        default=None,
        help="Serial port for Arduino bridge (example: COM3).",
    )
    parser.add_argument(
        "--arduino-baud",
        type=int,
        default=9600,
        help="Arduino serial baud rate.",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Run simulation in real-time (approximately 1 simulation second per wall-clock second).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="SUMO random seed.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print detailed controller debug output in CMD.",
    )
    parser.add_argument(
        "--debug-every",
        type=int,
        default=5,
        help="Print debug information every N simulation steps.",
    )
    parser.add_argument(
        "--experiment-id",
        type=int,
        default=None,
        help="Force experiment_id for DB logging (recommended: transaction/region id).",
    )

    args = parser.parse_args()

    if args.dataset_root:
        run_scenario_folders(
            dataset_root=args.dataset_root,
            mode="adaptive",
            max_steps=args.steps,
            vision_loop=not args.no_vision_loop,
            use_gui=args.gui,
            vision_weight=args.vision_weight,
            adaptive_min_switch_gap=args.adaptive_min_switch_gap,
            sumo_cfg_path=args.sumocfg,
            tl_id=args.tl_id,
            arduino_port=args.arduino_port,
            arduino_baud=args.arduino_baud,
            realtime=args.realtime,
            seed=args.seed,
            debug=args.debug,
            debug_every=args.debug_every,
        )

    elif args.mode == "compare":
        compare_modes(
            max_steps=args.steps,
            use_vision=args.use_vision,
            dataset_dir=args.dataset_dir,
            vision_loop=not args.no_vision_loop,
            use_gui=args.gui,
            vision_weight=args.vision_weight,
            adaptive_min_switch_gap=args.adaptive_min_switch_gap,
            vision_source=args.vision_source,
            vision_api_url_template=args.vision_api_url_template,
            vision_junction_id=args.junction_id,
            sumo_cfg_path=args.sumocfg,
            tl_id=args.tl_id,
            arduino_port=args.arduino_port,
            arduino_baud=args.arduino_baud,
            realtime=args.realtime,
            seed=args.seed,
            debug=args.debug,
            debug_every=args.debug_every,
        )

    else:
        run_simulation(
            mode=args.mode,
            max_steps=args.steps,
            use_vision=args.use_vision,
            dataset_dir=args.dataset_dir,
            vision_loop=not args.no_vision_loop,
            use_gui=args.gui,
            vision_weight=args.vision_weight,
            adaptive_min_switch_gap=args.adaptive_min_switch_gap,
            vision_source=args.vision_source,
            vision_api_url_template=args.vision_api_url_template,
            vision_junction_id=args.junction_id,
            sumo_cfg_path=args.sumocfg,
            tl_id=args.tl_id,
            arduino_port=args.arduino_port,
            arduino_baud=args.arduino_baud,
            realtime=args.realtime,
            seed=args.seed,
            debug=args.debug,
            debug_every=args.debug_every,
            experiment_id_override=args.experiment_id,
        )

        













