# experiments/test_hysteresis.py

import random
from algorithm.algorithm import AdaptiveController

controller = AdaptiveController(hysteresis_threshold=3)
current_phase = 0
switch_count = 0

for t in range(300):
    pressure = {
        0: 10 + random.randint(-1, 1),
        1: 9 + random.randint(-1, 1),
        2: 2,
        3: 2
    }

    controller.update_red_times(current_phase)
    switch, reason = controller.should_switch(current_phase, pressure)

    if switch:
        current_phase = controller.select_next_phase(pressure)
        switch_count += 1

print("Total switches:", switch_count)

