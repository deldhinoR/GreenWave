import os
import argparse
import traci

from algorithm.algorithm import AdaptiveController
from db import (
    init_db,
    log_step,
    log_decision,
    create_experiment,
    log_light_status,
    log_alert
)
from controller.vision_adapter import compute_phase_pressure, VisionDatasetReader


# PATH CONFIGURATION

SUMO_BINARY_HEADLESS = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
SUMO_BINARY_GUI = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
SIM_FOLDER = "simulation"
SUMO_CFG = os.path.join(SIM_FOLDER, "kolej.sumocfg")


# TRAFFIC LIGHT CONFIGURATION

TL_ID = "clusterJ0_J1_J11_J2_#4more"

PHASE_LANES = {
    0: ["E1_0", "E1_1"],
    1: ["E0.2_0", "E0.2_1"],
    2: ["E10_0", "E10_1", "E10_2", "E10_3"],
    3: ["E11.1_0", "E11.1_1", "E11.1_2"]
}

PHASE_NAMES = {
    0: "Phase 0 - E1 lanes GREEN",
    1: "Phase 1 - E0.2 lanes GREEN",
    2: "Phase 2 - E10 lanes GREEN",
    3: "Phase 3 - E11.1 lanes GREEN"
}


def get_lane_phase_pressure():
    lane_pressure = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}

    for phase, lanes in PHASE_LANES.items():
        for lane in lanes:
            lane_pressure[phase] += traci.lane.getLastStepHaltingNumber(lane)

    return lane_pressure


def blend_phase_pressure(vision_pressure, lane_pressure, vision_weight=0.7):
    wv = max(0.0, min(1.0, vision_weight))
    wl = 1.0 - wv

    return {
        phase: (wv * float(vision_pressure.get(phase, 0.0)))
        + (wl * float(lane_pressure.get(phase, 0.0)))
        for phase in range(4)
    }


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


def run_simulation(
    mode="adaptive",
    max_steps=None,
    use_vision=False,
    dataset_dir="dataset",
    vision_loop=True,
    use_gui=False,
    vision_weight=0.7,
    adaptive_min_switch_gap=12,
):
    print(
        f"\nSimulation started | MODE = {mode.upper()} | "
        f"VISION = {use_vision} | DATASET = {dataset_dir} | "
        f"SUMO_GUI = {use_gui}"
    )

    init_db()
    experiment_id = create_experiment()
    print(f"Experiment ID: {experiment_id}")

    controller = None

    if mode == "adaptive":
        controller = AdaptiveController(
            min_green=15,
            max_green=60,
            max_red_limit=90,
            phase_count=4,
            alpha=1.5,
            beta=1.5,
            gamma=1.6,
            hysteresis_threshold=15,
            cooldown=6,
        )

        controller.max_red_observed = {
            p: 0 for p in range(controller.phase_count)
        }

    elif mode == "fixed":
        controller = None

    else:
        raise ValueError("Invalid mode. Use 'adaptive' or 'fixed'.")

    sumo_binary = SUMO_BINARY_GUI if use_gui else SUMO_BINARY_HEADLESS

    sumo_cmd = [
        sumo_binary,
        "-c", SUMO_CFG,
        "--start",
        "--quit-on-end",
        "--seed", "42"
    ]

    vision_reader = None

    if use_vision:
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

    if max_steps is None:
        max_steps = 1000

    traci.start(sumo_cmd)
    traci.trafficlight.setPhase(TL_ID, 0)

    step = 0
    fixed_phase_duration = 60
    fixed_timer = 0
    last_switch_step = -10**9

    red_queue_history = []
    switch_count = 0
    net_wait_sum_history = []
    net_avg_speed_history = []
    halting_vehicle_history = []
    throughput_total = 0

    try:
        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            try:
                traci.simulationStep()
            except traci.exceptions.FatalTraCIError:
                print("SUMO closed manually.")
                break

            step += 1
            current_phase = traci.trafficlight.getPhase(TL_ID)

            if use_vision and vision_reader is not None:
                vision_json = vision_reader.next_sample()

                if vision_json is not None:
                    vision_queues, emergency_phase = compute_phase_pressure(vision_json)
                    lane_queues = get_lane_phase_pressure()

                    red_queues = blend_phase_pressure(
                        vision_queues,
                        lane_queues,
                        vision_weight=vision_weight,
                    )

                else:
                    print(
                        f"Vision dataset exhausted at step={step}. "
                        "Stopping simulation to avoid zero-pressure tail."
                    )
                    break

            else:
                red_queues = {p: 0 for p in range(4)}
                emergency_phase = None

                for phase, lanes in PHASE_LANES.items():
                    for lane in lanes:
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

                if switch and (step - last_switch_step >= adaptive_min_switch_gap):
                    next_phase = controller.select_next_phase(
                        red_queues,
                        current_phase,
                        emergency_phase
                    )

                    traci.trafficlight.setPhase(TL_ID, next_phase)

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
                fixed_timer += 1

                if fixed_timer >= fixed_phase_duration:
                    next_phase = (current_phase + 1) % 4

                    traci.trafficlight.setPhase(TL_ID, next_phase)

                    fixed_timer = 0
                    switch_count += 1

                    log_decision(
                        step,
                        "FIXED_SWITCH",
                        "Fixed phase duration completed",
                        total_q,
                        experiment_id,
                        selected_phase=next_phase,
                        green_duration=fixed_phase_duration
                    )

            log_step(
                step,
                current_phase,
                total_q,
                network_state["halting_count"],
                experiment_id
            )

            log_light_status(
                experiment_id=experiment_id,
                current_phase=current_phase,
                light_status=PHASE_NAMES.get(
                    current_phase,
                    f"Phase {current_phase} active"
                ),
                remaining_time=get_remaining_phase_time(TL_ID)
            )

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

    finally:
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
        )

        






























