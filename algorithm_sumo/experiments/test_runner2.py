import sys
import os
import time  # <--- YENİ EKLENDİ (Bekleme için)

# ==========================================
# 1. ADIM: YOL TARİFİ
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)                
sys.path.append(parent_dir)

import main
import db 
import traci

# ==========================================
# 2. ADIM: MONKEY PATCH
# ==========================================
original_traci_start = traci.start

def turbo_traci_start(cmd, **kwargs):
    print("🚀 GHOST MOD: Simülasyon arka planda ışık hızında çalışıyor...")
    new_cmd = list(cmd)
    if len(new_cmd) > 0 and "sumo-gui" in str(new_cmd[0]).lower():
        new_cmd[0] = new_cmd[0].replace("sumo-gui", "sumo")

    turbo_cmd = new_cmd + [
        "--start", "--quit-on-end", "--delay", "0",
    ]
    return original_traci_start(turbo_cmd, **kwargs)

traci.start = turbo_traci_start

# ==========================================
# 3. ADIM: YENİ TEST SENARYOLARI (ASİMETRİK TRAFİK)
# ==========================================
# ID'leri 200 serisi yaptık ki eski verilerle karışmasın.
test_scenarios = [
    # Threshold Denemeleri
    {"id": 201, "MIN_GREEN": 20, "MAX_GREEN": 30, "QUEUE_THRESHOLD": 5}, 
    {"id": 202, "MIN_GREEN": 20, "MAX_GREEN": 30, "QUEUE_THRESHOLD": 8},
    {"id": 203, "MIN_GREEN": 20, "MAX_GREEN": 30, "QUEUE_THRESHOLD": 12}, 
    {"id": 204, "MIN_GREEN": 20, "MAX_GREEN": 30, "QUEUE_THRESHOLD": 15},
    {"id": 205, "MIN_GREEN": 20, "MAX_GREEN": 30, "QUEUE_THRESHOLD": 20}, 
    
    # SABİT SİSTEM (Referans) - ID: 2999
    {"id": 2999, "MIN_GREEN": 45, "MAX_GREEN": 45, "QUEUE_THRESHOLD": 100}, 
]

print("🚦 Toplu Test Başlıyor (Asimetrik Senaryo)...\n")

current_run_ids = []

for test in test_scenarios:
    exp_id = test["id"]
    current_run_ids.append(exp_id)
    
    print(f"Running test {exp_id}...")
    
    # --- KRİTİK DÜZELTME: GÜVENLİK KONTROLÜ ---
    # Eğer önceki testten açık kalan bir bağlantı varsa zorla kapat.
    try:
        if traci.isLoaded():
            traci.close()
            time.sleep(2) # Kapanması için süre tanı
    except:
        pass

    try:
        main.start_smart_simulation(
            MIN_GREEN_TIME=test["MIN_GREEN"],
            MAX_GREEN_TIME=test["MAX_GREEN"],
            QUEUE_THRESHOLD=test["QUEUE_THRESHOLD"],
            EXP_ID=exp_id
        )
        print(f"✅ Test {exp_id} tamamlandı.")
        
        # --- KRİTİK DÜZELTME: SOĞUMA SÜRESİ ---
        # Bir sonraki test başlamadan önce 3 saniye bekle.
        # Bu, port hatasını engeller.
        time.sleep(3) 
        print("   (Soğuma süresi tamamlandı, devam ediliyor...)\n")

    except Exception as e:
        print(f"❌ Test {exp_id} sırasında hata: {e}")

traci.start = original_traci_start
print("🏁 Tüm testler bitti. Sonuçlar analiz ediliyor...")

# ==========================================
# 4. ADIM: RAPORLAMA
# ==========================================
print("\n" + "="*55)
print("📊 ASİMETRİK TRAFİK SONUÇLARI (SABİT vs AKILLI)")
print("="*55)

try:
    conn = db.get_connection()
    if conn:
        cursor = conn.cursor()
        ids_string = ",".join(str(x) for x in current_run_ids)
        
        query = f"""
        SELECT experiment_id, AVG(waiting_count) as ortalama_bekleme
        FROM simulation_logs 
        WHERE experiment_id IN ({ids_string})
        GROUP BY experiment_id
        ORDER BY ortalama_bekleme ASC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        print(f"{'TEST ID':<10} | {'ORT. BEKLEME':<15} | {'AÇIKLAMA'}")
        print("-" * 60)
        
        for row in results:
            exp_id = row[0]
            score = row[1]
            label = ""
            if exp_id == 2999: label = "🛑 SABİT SİSTEM (45sn)"
            elif exp_id == 203: label = "🏆 Akıllı Sistem (Th:12)"
            else: label = f"Akıllı (Th:{next((t['QUEUE_THRESHOLD'] for t in test_scenarios if t['id'] == exp_id), '?')})"
            
            print(f"{exp_id:<10} | {score:.2f}            | {label}")
            
        print("-" * 60)
        
        if results:
            best_exp = results[0][0]
            if best_exp == 2999:
                print("⚠️  Sabit Sistem hala kazanıyorsa 'unbalanced.rou.xml' dosyasının")
                print("    main.py içinde aktif edildiğinden emin ol!")
            else:
                diff = 0
                sabit_score = next((r[1] for r in results if r[0] == 2999), 0)
                smart_score = results[0][1]
                if sabit_score > 0:
                    diff = ((sabit_score - smart_score) / sabit_score) * 100
                    print(f"🎉 TEBRİKLER! Akıllı sistem, Sabit sisteme göre %{diff:.1f} daha verimli!")

        cursor.close()
        conn.close()
    else:
        print("❌ Veritabanı bağlantısı yok.")
except Exception as e:
    print(f"⚠️ Raporlama hatası: {e}")

    