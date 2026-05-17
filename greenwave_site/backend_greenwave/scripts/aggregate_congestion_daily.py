import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Aggregate camera dataset JSON files into daily congestion averages."
    )
    parser.add_argument(
        "--dataset-root",
        default=str(Path(__file__).resolve().parents[2] / "dataset"),
        help="Path to dataset root containing JSON files.",
    )
    parser.add_argument(
        "--db-path",
        default=str(Path(__file__).resolve().parents[1] / "greenwave.db"),
        help="Path to SQLite database file.",
    )
    return parser.parse_args()


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_congestion_daily (
            junction_id INTEGER NOT NULL,
            day_date TEXT NOT NULL,
            avg_congestion REAL NOT NULL,
            min_congestion REAL NOT NULL,
            max_congestion REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            road_sample_count INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (junction_id, day_date)
        )
        """
    )
    conn.commit()


def iter_json_files(dataset_root: Path):
    for path in dataset_root.rglob("*.json"):
        if path.is_file():
            yield path


def parse_record(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    received_time = payload.get("received_time")
    junction_id = payload.get("junction_id")
    roads = payload.get("roads", [])

    if received_time is None or junction_id is None or not isinstance(roads, list) or len(roads) == 0:
        return None

    try:
        ts = datetime.fromisoformat(received_time.replace("Z", "+00:00"))
    except Exception:
        return None

    road_scores = []
    for road in roads:
        if not isinstance(road, dict):
            continue
        value = road.get("congestion_score")
        if isinstance(value, (int, float)):
            road_scores.append(float(value))

    if not road_scores:
        return None

    snapshot_avg = sum(road_scores) / len(road_scores)
    day_key = ts.date().isoformat()

    return {
        "junction_id": int(junction_id),
        "day_date": day_key,
        "snapshot_avg": snapshot_avg,
        "min_score": min(road_scores),
        "max_score": max(road_scores),
        "road_count": len(road_scores),
    }


def aggregate(dataset_root: Path):
    grouped = defaultdict(lambda: {
        "snapshot_sum": 0.0,
        "snapshot_count": 0,
        "min_congestion": float("inf"),
        "max_congestion": float("-inf"),
        "road_sample_count": 0,
    })

    file_count = 0
    valid_count = 0

    for json_file in iter_json_files(dataset_root):
        file_count += 1
        parsed = parse_record(json_file)
        if parsed is None:
            continue
        valid_count += 1

        key = (parsed["junction_id"], parsed["day_date"])
        bucket = grouped[key]

        bucket["snapshot_sum"] += parsed["snapshot_avg"]
        bucket["snapshot_count"] += 1
        bucket["min_congestion"] = min(bucket["min_congestion"], parsed["min_score"])
        bucket["max_congestion"] = max(bucket["max_congestion"], parsed["max_score"])
        bucket["road_sample_count"] += parsed["road_count"]

    return grouped, file_count, valid_count


def upsert_daily(conn, grouped):
    cur = conn.cursor()
    rows_written = 0

    for (junction_id, day_date), bucket in grouped.items():
        if bucket["snapshot_count"] == 0:
            continue

        avg_congestion = bucket["snapshot_sum"] / bucket["snapshot_count"]

        cur.execute(
            """
            INSERT INTO camera_congestion_daily
                (junction_id, day_date, avg_congestion, min_congestion, max_congestion, sample_count, road_sample_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(junction_id, day_date) DO UPDATE SET
                avg_congestion = excluded.avg_congestion,
                min_congestion = excluded.min_congestion,
                max_congestion = excluded.max_congestion,
                sample_count = excluded.sample_count,
                road_sample_count = excluded.road_sample_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                junction_id,
                day_date,
                round(avg_congestion, 3),
                round(bucket["min_congestion"], 3),
                round(bucket["max_congestion"], 3),
                int(bucket["snapshot_count"]),
                int(bucket["road_sample_count"]),
            ),
        )
        rows_written += 1

    conn.commit()
    return rows_written


def main():
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    db_path = Path(args.db_path).resolve()

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    conn = sqlite3.connect(db_path)
    ensure_table(conn)

    grouped, file_count, valid_count = aggregate(dataset_root)
    rows_written = upsert_daily(conn, grouped)

    print(f"Dataset root: {dataset_root}")
    print(f"DB path: {db_path}")
    print(f"JSON files scanned: {file_count}")
    print(f"Valid records: {valid_count}")
    print(f"Daily aggregate rows upserted: {rows_written}")

    conn.close()


if __name__ == "__main__":
    main()
