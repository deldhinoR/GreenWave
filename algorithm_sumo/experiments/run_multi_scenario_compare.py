import argparse
import csv
import os
import sys
import statistics
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import run_simulation


def find_sumocfg_files(root_dir):
    sumocfgs = []
    for base, _, files in os.walk(root_dir):
        for name in files:
            if name.endswith(".sumocfg"):
                sumocfgs.append(os.path.join(base, name))
    return sorted(sumocfgs)


def detect_tl_id(sumocfg_path):
    cfg_tree = ET.parse(sumocfg_path)
    cfg_root = cfg_tree.getroot()

    net_file_node = cfg_root.find(".//input/net-file")
    if net_file_node is None:
        raise RuntimeError(f"net-file not found in: {sumocfg_path}")

    net_file_value = net_file_node.attrib.get("value")
    if not net_file_value:
        raise RuntimeError(f"net-file value missing in: {sumocfg_path}")

    net_path = os.path.join(os.path.dirname(sumocfg_path), net_file_value)
    net_tree = ET.parse(net_path)
    net_root = net_tree.getroot()

    tl_logic = net_root.find(".//tlLogic")
    if tl_logic is None:
        raise RuntimeError(f"tlLogic not found in net file: {net_path}")

    tl_id = tl_logic.attrib.get("id")
    if not tl_id:
        raise RuntimeError(f"tlLogic id missing in net file: {net_path}")

    return tl_id


def run_for_scenario(sumocfg_path, tl_id, steps, repeats, seed_start):
    wait_improvements = []
    halting_improvements = []
    throughput_changes = []

    for i in range(repeats):
        seed = seed_start + i
        print(f"\n  Repeat {i + 1}/{repeats} | seed={seed}")

        fixed = run_simulation(
            mode="fixed",
            max_steps=steps,
            use_vision=False,
            sumo_cfg_path=sumocfg_path,
            tl_id=tl_id,
            seed=seed,
        )
        adaptive = run_simulation(
            mode="adaptive",
            max_steps=steps,
            use_vision=False,
            sumo_cfg_path=sumocfg_path,
            tl_id=tl_id,
            seed=seed,
        )

        wait_imp = 0.0
        if fixed["avg_network_wait_sum"] > 0:
            wait_imp = (
                (fixed["avg_network_wait_sum"] - adaptive["avg_network_wait_sum"])
                / fixed["avg_network_wait_sum"]
            ) * 100.0

        halting_imp = 0.0
        if fixed["avg_halting_vehicles"] > 0:
            halting_imp = (
                (fixed["avg_halting_vehicles"] - adaptive["avg_halting_vehicles"])
                / fixed["avg_halting_vehicles"]
            ) * 100.0

        throughput_change = 0.0
        if fixed["throughput_total"] > 0:
            throughput_change = (
                (adaptive["throughput_total"] - fixed["throughput_total"])
                / fixed["throughput_total"]
            ) * 100.0

        wait_improvements.append(wait_imp)
        halting_improvements.append(halting_imp)
        throughput_changes.append(throughput_change)

    return {
        "wait_improvement_avg": statistics.mean(wait_improvements),
        "wait_improvement_std": statistics.pstdev(wait_improvements) if len(wait_improvements) > 1 else 0.0,
        "halting_improvement_avg": statistics.mean(halting_improvements),
        "halting_improvement_std": statistics.pstdev(halting_improvements) if len(halting_improvements) > 1 else 0.0,
        "throughput_change_avg": statistics.mean(throughput_changes),
        "throughput_change_std": statistics.pstdev(throughput_changes) if len(throughput_changes) > 1 else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Run multi-scenario Fixed vs Adaptive benchmark.")
    parser.add_argument("--scenarios-root", required=True, help="Root folder containing scenario subfolders/files.")
    parser.add_argument("--steps", type=int, default=3000, help="Simulation step limit per run.")
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per scenario with incrementing seed.")
    parser.add_argument("--seed-start", type=int, default=42, help="Starting seed value for repeats.")
    parser.add_argument(
        "--output-csv",
        default=os.path.join("experiments", "multi_scenario_results.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    scenarios_root = os.path.abspath(args.scenarios_root)
    sumocfg_paths = find_sumocfg_files(scenarios_root)
    if not sumocfg_paths:
        raise FileNotFoundError(f"No .sumocfg files found under: {scenarios_root}")

    rows = []
    print("\n===== MULTI SCENARIO COMPARE =====")
    print(f"Root     : {scenarios_root}")
    print(f"Scenarios: {len(sumocfg_paths)}")
    print(f"Steps    : {args.steps}")
    print(f"Repeats  : {args.repeats}\n")

    for idx, sumocfg in enumerate(sumocfg_paths, start=1):
        scenario_name = os.path.basename(os.path.dirname(sumocfg))
        tl_id = detect_tl_id(sumocfg)

        print(f"[{idx}/{len(sumocfg_paths)}] Scenario: {scenario_name}")
        print(f"  sumocfg: {sumocfg}")
        print(f"  tl_id  : {tl_id}")

        metrics = run_for_scenario(
            sumocfg_path=sumocfg,
            tl_id=tl_id,
            steps=args.steps,
            repeats=args.repeats,
            seed_start=args.seed_start,
        )

        row = {
            "scenario": scenario_name,
            "sumocfg": sumocfg,
            "tl_id": tl_id,
            **metrics,
        }
        rows.append(row)

        print(
            "  Avg WaitImp={:.2f}% | Avg HaltImp={:.2f}% | Avg ThroughputΔ={:.2f}%".format(
                row["wait_improvement_avg"],
                row["halting_improvement_avg"],
                row["throughput_change_avg"],
            )
        )

    os.makedirs(os.path.dirname(args.output_csv), exist_ok=True)
    fieldnames = [
        "scenario",
        "sumocfg",
        "tl_id",
        "wait_improvement_avg",
        "wait_improvement_std",
        "halting_improvement_avg",
        "halting_improvement_std",
        "throughput_change_avg",
        "throughput_change_std",
    ]
    with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    overall_wait = statistics.mean(r["wait_improvement_avg"] for r in rows)
    overall_halt = statistics.mean(r["halting_improvement_avg"] for r in rows)
    overall_thr = statistics.mean(r["throughput_change_avg"] for r in rows)

    print("\n===== OVERALL AVERAGE =====")
    print(f"Wait Improvement Avg      : {overall_wait:.2f}%")
    print(f"Halting Improvement Avg   : {overall_halt:.2f}%")
    print(f"Throughput Change Avg     : {overall_thr:.2f}%")
    print(f"CSV saved                 : {os.path.abspath(args.output_csv)}")


if __name__ == "__main__":
    main()
