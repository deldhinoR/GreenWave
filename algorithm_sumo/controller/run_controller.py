# controller/run_controller.py
import os
import csv
import traci
import requests
from algorithm.algorithm import decide_phase

SUMO_EXE = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
SUMO_CFG = os.path.join(os.getcwd(), "simulation", "config.sumocfg")
LOG_FILE = os.path.join(os.getcwd(), "simulation_log.csv")

API_URL = "https://shortwave-stick-balmy.ngrok-free.dev/api/sumo/traffic/3"
TLS_ID = "tl_1"
API_FETCH_INTERVAL = 5  # her 5 stepte bir veri çek

def get_api_data():
    try:
        response = requests.get(API_URL, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"API connection error: {e}")
        return None

def parse_api_data(data):
    """
    API çıktısını algoritmanın kullanacağı forma çevirir.
    Şimdilik roadId 10'u north-south kabul edip q_ns'e,
    diğerlerini q_ew'e topluyoruz.
    Bunu kendi yol eşleşmene göre değiştireceksin.
    """
    if not data or "roads" not in data:
        return None, None, False

    q_ns = 0
    q_ew = 0
    ambulance_detected = False

    for road in data["roads"]:
        road_id = road["roadId"]
        congestion = road["congestionScore"]
        ambulance = road["ambulance"]

        if ambulance:
            ambulance_detected = True

        # ÖRNEK EŞLEME
        # roadId 10 -> north/south
        # diğerleri -> east/west
        if road_id == 10:
            q_ns += congestion
        else:
            q_ew += congestion

    return q_ns, q_ew, ambulance_detected

def run_simulation(steps=1000):
    SUMO_CMD = [
        SUMO_EXE,
        "-c", SUMO_CFG,
        "--start",
        "--quit-on-end"
    ]

    traci.start(SUMO_CMD, port=8873)

    last_api_fetch = -1
    api_q_ns = 0
    api_q_ew = 0
    ambulance_detected = False

    with open(LOG_FILE, mode="w", newline="") as csvfile:
        fieldnames = ["step", "phase", "green_duration", "q_ns", "q_ew", "ambulance"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for step in range(steps):
            traci.simulationStep()

            # API'den her step değil, belli aralıkla veri çek
            if last_api_fetch == -1 or step - last_api_fetch >= API_FETCH_INTERVAL:
                raw_data = get_api_data()
                parsed_q_ns, parsed_q_ew, parsed_ambulance = parse_api_data(raw_data)

                if parsed_q_ns is not None and parsed_q_ew is not None:
                    api_q_ns = parsed_q_ns
                    api_q_ew = parsed_q_ew
                    ambulance_detected = parsed_ambulance
                    print(f"[STEP {step}] API q_ns={api_q_ns}, q_ew={api_q_ew}, ambulance={ambulance_detected}")
                else:
                    print(f"[STEP {step}] API data unavailable, using previous values.")

                last_api_fetch = step

            # Şu anki fazı al
            current_phase = traci.trafficlight.getPhase(TLS_ID)

            # API verisini algoritmaya ver
            new_phase, green_duration = decide_phase(api_q_ns, api_q_ew, current_phase)

            # İstersen burada ambulans önceliği de ekleyebilirsin
            # örnek:
            # if ambulance_detected:
            #     new_phase = 0  # ambulansın geçtiği yöne göre değiştir

            if new_phase != current_phase:
                traci.trafficlight.setPhase(TLS_ID, new_phase)

            traci.trafficlight.setPhaseDuration(TLS_ID, green_duration)

            writer.writerow({
                "step": step,
                "phase": new_phase,
                "green_duration": green_duration,
                "q_ns": api_q_ns,
                "q_ew": api_q_ew,
                "ambulance": ambulance_detected
            })

    traci.close()
    print(f"Simulation finished. Log saved to {LOG_FILE}")