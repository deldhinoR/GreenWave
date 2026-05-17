import psycopg2
from config import DB_CONFIG


def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print("Database connection error:", e)
        return None


# 🔹 Tabloları oluştur
def init_db():
    conn = get_connection()
    if conn is None:
        return

    cur = conn.cursor()

    # 🔹 Simulation logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_logs (
            id SERIAL PRIMARY KEY,
            experiment_id INTEGER,
            step INTEGER,
            phase INTEGER,
            queue_length INTEGER,
            waiting_count INTEGER,
            density_level VARCHAR(20),
            average_waiting_time FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Existing databases may have an older simulation_logs schema.
    # Ensure newly introduced columns are present.
    cur.execute("""
        ALTER TABLE simulation_logs
        ADD COLUMN IF NOT EXISTS density_level VARCHAR(20);
    """)
    cur.execute("""
        ALTER TABLE simulation_logs
        ADD COLUMN IF NOT EXISTS average_waiting_time FLOAT;
    """)

    # Existing rows created before these columns may contain NULL.
    # Backfill them from queue_length / waiting_count.
    cur.execute("""
        UPDATE simulation_logs
        SET
            density_level = CASE
                WHEN COALESCE(queue_length, 0) < 10 THEN 'LOW'
                WHEN COALESCE(queue_length, 0) < 20 THEN 'MEDIUM'
                ELSE 'HIGH'
            END
        WHERE density_level IS NULL;
    """)
    cur.execute("""
        UPDATE simulation_logs
        SET average_waiting_time = COALESCE(waiting_count, 0)::FLOAT
        WHERE average_waiting_time IS NULL;
    """)

    # Keep data clean for future INSERT/UPDATE calls even if NULL is sent.
    cur.execute("""
        CREATE OR REPLACE FUNCTION fill_simulation_logs_defaults()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.density_level IS NULL THEN
                NEW.density_level := CASE
                    WHEN COALESCE(NEW.queue_length, 0) < 10 THEN 'LOW'
                    WHEN COALESCE(NEW.queue_length, 0) < 20 THEN 'MEDIUM'
                    ELSE 'HIGH'
                END;
            END IF;

            IF NEW.average_waiting_time IS NULL THEN
                NEW.average_waiting_time := COALESCE(NEW.waiting_count, 0)::FLOAT;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    cur.execute("""
        DROP TRIGGER IF EXISTS trg_fill_simulation_logs_defaults ON simulation_logs;
    """)
    cur.execute("""
        CREATE TRIGGER trg_fill_simulation_logs_defaults
        BEFORE INSERT OR UPDATE ON simulation_logs
        FOR EACH ROW
        EXECUTE FUNCTION fill_simulation_logs_defaults();
    """)

    # 🔹 Decision logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS decision_logs (
            id SERIAL PRIMARY KEY,
            experiment_id INTEGER,
            step INTEGER,
            action TEXT,
            reason TEXT,
            queue_size INTEGER,
            selected_phase INTEGER,
            green_duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Existing databases may have an older decision_logs schema.
    # Ensure newly introduced columns are present.
    cur.execute("""
        ALTER TABLE decision_logs
        ADD COLUMN IF NOT EXISTS selected_phase INTEGER;
    """)

    cur.execute("""
        ALTER TABLE decision_logs
        ADD COLUMN IF NOT EXISTS green_duration INTEGER;
    """)

    # Backfill NULLs in decision_logs for old rows.
    cur.execute("""
        UPDATE decision_logs
        SET selected_phase = COALESCE(selected_phase, 0)
        WHERE selected_phase IS NULL;
    """)
    cur.execute("""
        UPDATE decision_logs
        SET green_duration = COALESCE(green_duration, 0)
        WHERE green_duration IS NULL;
    """)

    # Prevent future NULL values in these columns.
    cur.execute("""
        CREATE OR REPLACE FUNCTION fill_decision_logs_defaults()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.selected_phase IS NULL THEN
                NEW.selected_phase := 0;
            END IF;

            IF NEW.green_duration IS NULL THEN
                NEW.green_duration := 0;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    cur.execute("""
        DROP TRIGGER IF EXISTS trg_fill_decision_logs_defaults ON decision_logs;
    """)
    cur.execute("""
        CREATE TRIGGER trg_fill_decision_logs_defaults
        BEFORE INSERT OR UPDATE ON decision_logs
        FOR EACH ROW
        EXECUTE FUNCTION fill_decision_logs_defaults();
    """)

    # 🔹 Current traffic light status
    cur.execute("""
        CREATE TABLE IF NOT EXISTS traffic_light_status (
            id SERIAL PRIMARY KEY,
            experiment_id INTEGER,
            current_phase INTEGER,
            light_status TEXT,
            remaining_time INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Backfill possible NULL values in existing traffic_light_status rows.
    cur.execute("""
        UPDATE traffic_light_status
        SET current_phase = COALESCE(current_phase, 0)
        WHERE current_phase IS NULL;
    """)
    cur.execute("""
        UPDATE traffic_light_status
        SET light_status = COALESCE(
            light_status,
            'Phase ' || COALESCE(current_phase, 0)::TEXT || ' active'
        )
        WHERE light_status IS NULL;
    """)
    cur.execute("""
        UPDATE traffic_light_status
        SET remaining_time = COALESCE(remaining_time, 0)
        WHERE remaining_time IS NULL;
    """)

    # Fill NULL values automatically for future INSERT/UPDATE operations.
    cur.execute("""
        CREATE OR REPLACE FUNCTION fill_traffic_light_status_defaults()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.current_phase IS NULL THEN
                NEW.current_phase := 0;
            END IF;

            IF NEW.light_status IS NULL THEN
                NEW.light_status := 'Phase ' || NEW.current_phase::TEXT || ' active';
            END IF;

            IF NEW.remaining_time IS NULL THEN
                NEW.remaining_time := 0;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    cur.execute("""
        DROP TRIGGER IF EXISTS trg_fill_traffic_light_status_defaults ON traffic_light_status;
    """)
    cur.execute("""
        CREATE TRIGGER trg_fill_traffic_light_status_defaults
        BEFORE INSERT OR UPDATE ON traffic_light_status
        FOR EACH ROW
        EXECUTE FUNCTION fill_traffic_light_status_defaults();
    """)

    # 🔹 Alerts table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            experiment_id INTEGER,
            alert_type VARCHAR(100),
            message TEXT,
            severity VARCHAR(20),
            is_resolved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Database tables ready.")


# 🔹 Yeni experiment_id üret
def create_experiment():
    conn = get_connection()
    if conn is None:
        return 1

    cur = conn.cursor()

    cur.execute("SELECT COALESCE(MAX(experiment_id), 0) FROM simulation_logs;")
    max_id = cur.fetchone()[0]

    new_id = max_id + 1

    cur.close()
    conn.close()

    return new_id


# 🔹 Simulation step log
def log_step(step, phase, queue_length, waiting_count, experiment_id):
    conn = get_connection()
    if conn is None:
        return

    # 🔹 Density level hesapla
    if queue_length < 10:
        density_level = "LOW"
    elif queue_length < 20:
        density_level = "MEDIUM"
    else:
        density_level = "HIGH"

    # 🔹 Ortalama bekleme süresi
    average_waiting_time = float(waiting_count)

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO simulation_logs
        (
            experiment_id,
            step,
            phase,
            queue_length,
            waiting_count,
            density_level,
            average_waiting_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (
        experiment_id,
        step,
        phase,
        queue_length,
        waiting_count,
        density_level,
        average_waiting_time
    ))

    conn.commit()
    cur.close()
    conn.close()


# 🔹 Decision log
def log_decision(
    step,
    action,
    reason,
    queue_size,
    experiment_id,
    selected_phase=None,
    green_duration=None
):
    conn = get_connection()
    if conn is None:
        return

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO decision_logs
        (
            experiment_id,
            step,
            action,
            reason,
            queue_size,
            selected_phase,
            green_duration
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (
        experiment_id,
        step,
        action,
        reason,
        queue_size,
        selected_phase,
        green_duration
    ))

    conn.commit()
    cur.close()
    conn.close()


# 🔹 Current traffic light status log
def log_light_status(
    experiment_id,
    current_phase,
    light_status,
    remaining_time
):
    conn = get_connection()
    if conn is None:
        return

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO traffic_light_status
        (
            experiment_id,
            current_phase,
            light_status,
            remaining_time
        )
        VALUES (%s, %s, %s, %s);
    """, (
        experiment_id,
        current_phase,
        light_status,
        remaining_time
    ))

    conn.commit()
    cur.close()
    conn.close()


# 🔹 Alert log
def log_alert(
    experiment_id,
    alert_type,
    message,
    severity
):
    conn = get_connection()
    if conn is None:
        return

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO alerts
        (
            experiment_id,
            alert_type,
            message,
            severity
        )
        VALUES (%s, %s, %s, %s);
    """, (
        experiment_id,
        alert_type,
        message,
        severity
    ))

    conn.commit()
    cur.close()
    conn.close()

    



