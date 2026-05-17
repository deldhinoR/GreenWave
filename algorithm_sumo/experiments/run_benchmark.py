from main import run_simulation

def run_benchmark():
    # Aynı koşullarda karşılaştırma için aynı max_steps kullan
    MAX_STEPS = 500

    print("\n==============================")
    print("RUN 1/2 -> FIXED")
    print("==============================")
    run_simulation(mode="fixed", max_steps=MAX_STEPS, use_vision=False)

    print("\n==============================")
    print("RUN 2/2 -> ADAPTIVE")
    print("==============================")
    run_simulation(mode="adaptive", max_steps=MAX_STEPS, use_vision=False)


if __name__ == "__main__":
    run_benchmark()

