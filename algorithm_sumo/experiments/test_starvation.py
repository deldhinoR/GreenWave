# experiments/test_starvation.py

from algorithm.algorithm import AdaptiveController

controller = AdaptiveController(max_red=60, max_red_limit=75)
current_phase = 0

for t in range(500):
    pressure = {0: 25, 1: 1, 2: 1, 3: 1}

    controller.update_red_times(current_phase)
    switch, reason = controller.should_switch(current_phase, pressure)

    if switch:
        current_phase = controller.select_next_phase(pressure)

print("Max red observed:", controller.max_red_observed)


