import os

import psycopg2

DB_CONFIG = {
    "host": os.environ.get("SUMO_DB_HOST", "localhost"),
    "database": os.environ.get("SUMO_DB_NAME", "traffic_db"),
    "user": os.environ.get("SUMO_DB_USER", "postgres"),
    "password": os.environ.get("SUMO_DB_PASSWORD", "postgres"),
    "port": int(os.environ.get("SUMO_DB_PORT", "5434")),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def create_table():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intersections (
            id SERIAL PRIMARY KEY,
            name TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS regions (
            id SERIAL PRIMARY KEY,
            name TEXT,
            min_lat DOUBLE PRECISION,
            min_lon DOUBLE PRECISION,
            max_lat DOUBLE PRECISION,
            max_lon DOUBLE PRECISION,
            car_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS region_identity (
            region_id INTEGER PRIMARY KEY REFERENCES regions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            address TEXT
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transaction_dashboard_cards (
            transaction_id TEXT PRIMARY KEY,
            congestion_improvement DOUBLE PRECISION NOT NULL,
            avg_congestion INTEGER NOT NULL,
            r1_green_seconds INTEGER NOT NULL,
            r1_red_seconds INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intersections_live (
            intersection_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_label TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS optimization_cycles (
            id SERIAL PRIMARY KEY,
            intersection_id TEXT NOT NULL,
            cycle_no INTEGER NOT NULL,
            congestion_improvement DOUBLE PRECISION NOT NULL,
            avg_congestion DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (intersection_id, cycle_no)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS road_metrics (
            id SERIAL PRIMARY KEY,
            intersection_id TEXT NOT NULL,
            cycle_no INTEGER NOT NULL,
            road_code TEXT NOT NULL,
            vehicle_count INTEGER NOT NULL,
            queue_length INTEGER NOT NULL,
            avg_waiting_seconds DOUBLE PRECISION NOT NULL,
            density_level TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (intersection_id, cycle_no, road_code)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_plans (
            id SERIAL PRIMARY KEY,
            intersection_id TEXT NOT NULL,
            cycle_no INTEGER NOT NULL,
            phase_code TEXT NOT NULL,
            green_seconds INTEGER NOT NULL,
            red_seconds INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (intersection_id, cycle_no, phase_code)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_congestion_daily (
            junction_id INTEGER NOT NULL,
            day_date DATE NOT NULL,
            avg_congestion DOUBLE PRECISION NOT NULL,
            min_congestion DOUBLE PRECISION NOT NULL,
            max_congestion DOUBLE PRECISION NOT NULL,
            sample_count INTEGER NOT NULL,
            road_sample_count INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (junction_id, day_date)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_congestion_hourly (
            junction_id INTEGER NOT NULL,
            hour_ts TIMESTAMP NOT NULL,
            avg_congestion DOUBLE PRECISION NOT NULL,
            min_congestion DOUBLE PRECISION NOT NULL,
            max_congestion DOUBLE PRECISION NOT NULL,
            sample_count INTEGER NOT NULL,
            road_sample_count INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (junction_id, hour_ts)
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_logs (
            id SERIAL PRIMARY KEY,
            intersection_id TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL,
            issue_text TEXT NOT NULL,
            severity TEXT DEFAULT 'WARNING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.commit()
    cursor.close()
    conn.close()


def save_region(name, min_lat, min_lon, max_lat, max_lon, car_count=0, display_name=None, address=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO regions (name, min_lat, min_lon, max_lat, max_lon, car_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, min_lat, min_lon, max_lat, max_lon, int(car_count or 0)),
    )
    region_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO region_identity (region_id, name, address)
        VALUES (%s, %s, %s)
        ON CONFLICT (region_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address
        """,
        (
            region_id,
            (display_name or name or f"Region {region_id}"),
            address,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return region_id


def upsert_region(region_id, name, min_lat, min_lon, max_lat, max_lon, car_count=0, display_name=None, address=None):
    conn = get_connection()
    cursor = conn.cursor()
    rid = int(region_id)
    cursor.execute("SELECT id FROM regions WHERE id = %s", (rid,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            """
            UPDATE regions
            SET name = %s,
                min_lat = %s,
                min_lon = %s,
                max_lat = %s,
                max_lon = %s,
                car_count = %s
            WHERE id = %s
            """,
            (name, min_lat, min_lon, max_lat, max_lon, int(car_count or 0), rid),
        )
    else:
        cursor.execute(
            """
            INSERT INTO regions (id, name, min_lat, min_lon, max_lat, max_lon, car_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (rid, name, min_lat, min_lon, max_lat, max_lon, int(car_count or 0)),
        )

    cursor.execute(
        """
        INSERT INTO region_identity (region_id, name, address)
        VALUES (%s, %s, %s)
        ON CONFLICT (region_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address
        """,
        (rid, (display_name or name or f"Region {rid}"), address),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return rid


def delete_region(region_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM regions WHERE id = %s", (region_id,))
    conn.commit()
    cursor.close()
    conn.close()


def upsert_transaction_dashboard_cards(
    transaction_id,
    congestion_improvement,
    avg_congestion,
    r1_green_seconds,
    r1_red_seconds,
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO transaction_dashboard_cards
            (transaction_id, congestion_improvement, avg_congestion, r1_green_seconds, r1_red_seconds)
        VALUES
            (%s, %s, %s, %s, %s)
        ON CONFLICT(transaction_id) DO UPDATE SET
            congestion_improvement = EXCLUDED.congestion_improvement,
            avg_congestion = EXCLUDED.avg_congestion,
            r1_green_seconds = EXCLUDED.r1_green_seconds,
            r1_red_seconds = EXCLUDED.r1_red_seconds,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            str(transaction_id),
            float(congestion_improvement),
            int(avg_congestion),
            int(r1_green_seconds),
            int(r1_red_seconds),
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_transaction_dashboard_cards(transaction_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT transaction_id, congestion_improvement, avg_congestion, r1_green_seconds, r1_red_seconds
        FROM transaction_dashboard_cards
        WHERE transaction_id = %s
        """,
        (str(transaction_id),),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


if __name__ == "__main__":
    create_table()
    print("PostgreSQL tables ready.")
