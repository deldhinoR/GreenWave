import os

# Yeni oluşacak dosya adı
OUTPUT_FILE = "simulation/unbalanced.rou.xml"

# ==========================================
# ASİMETRİK TRAFİK AYARLARI (KİLİT NOKTA)
# ==========================================
# ANA YOL (Kuzey-Güney): Çok Yoğun (Kusma noktası)
MAIN_FLOW = 2500  

# YAN YOL (Doğu-Batı): Çok Seyrek (Sinek avlıyor)
SIDE_FLOW = 200   

def create_unbalanced_routes():
    if not os.path.exists("simulation"):
        os.makedirs("simulation")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    
    <vType id="car" accel="2.0" decel="4.5" sigma="0.5" length="5" minGap="2.5" maxSpeed="70" guiShape="passenger"/>

    <flow id="f_main_1" type="car" begin="0.00" end="3600.00" perHour="{MAIN_FLOW}" from="E5" to="E13" via="E4" departLane="best"/>
    <flow id="f_main_2" type="car" begin="0.00" end="3600.00" perHour="{MAIN_FLOW}" from="E5" to="E12" via="E4" departLane="best"/>
    <flow id="f_main_3" type="car" begin="0.00" end="3600.00" perHour="{MAIN_FLOW}" from="E1" to="E10" via="E0" departLane="best"/>
    <flow id="f_main_4" type="car" begin="0.00" end="3600.00" perHour="{MAIN_FLOW}" from="E1" to="E12" via="E0" departLane="best"/>


    <flow id="f_side_1" type="car" begin="0.00" end="3600.00" perHour="{SIDE_FLOW}" color="28,255,0" from="E6" to="E12" via="E7" departLane="best"/>
    <flow id="f_side_2" type="car" begin="0.00" end="3600.00" perHour="{SIDE_FLOW}" color="255,0,9" from="E8" to="E10" via="E9" departLane="best"/>

</routes>
"""
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)
    
    print(f"✅ 'unbalanced.rou.xml' oluşturuldu!")
    print(f"👉 Şimdi main.py dosyasında: VALIDATION_ROU_FILE = 'unbalanced.rou.xml' yap.")

if __name__ == "__main__":
    create_unbalanced_routes()


    