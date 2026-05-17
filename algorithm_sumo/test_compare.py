from main import run_simulation
import statistics

def main():
    print("🧪 TEST BAŞLADI\n")

    print("🚦 FIXED SYSTEM ÇALIŞIYOR...")
    fixed = run_simulation(mode="fixed")
    print("✅ FIXED BİTTİ\n")

    print("🤖 ADAPTIVE SYSTEM ÇALIŞIYOR...")
    adaptive = run_simulation(mode="adaptive")
    print("✅ ADAPTIVE BİTTİ\n")

    print("\n📊 KARŞILAŞTIRMA SONUÇLARI")
    print("-" * 40)

    print("🚦 FIXED SYSTEM")
    print(f"Ortalama Red Queue : {fixed['avg_red_queue']:.2f}")
    print(f"Switch Count       : {fixed['switch_count']}")
    print()

    print("🤖 ADAPTIVE SYSTEM")
    print(f"Ortalama Red Queue : {adaptive['avg_red_queue']:.2f}")
    print(f"Switch Count       : {adaptive['switch_count']}")
    print()

    improvement = (
        (fixed['avg_red_queue'] - adaptive['avg_red_queue'])
        / fixed['avg_red_queue']
    ) * 100

    print(f"📉 Kuyruk iyileşmesi: %{improvement:.1f}")
    print("\n🏁 TEST TAMAMLANDI")

if __name__ == "__main__":
    main()



