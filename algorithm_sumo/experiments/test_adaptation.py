# experiments/test_adaptation.py
import sys
import os

from algorithm.algorithm import AdaptiveController

def agressive_traffic_pattern(t):
    import random
    if t < 50:
        return {i: random.randint(5,10) for i in range(4)}
    elif t < 100:
        return {i: random.randint(10,20) for i in range(4)}
    else:
        return {i: random.randint(5, 25) for i in range(4)}

controller = AdaptiveController()
current_phase = 0

adaptation_times = []
last_dominant = 0
change_time = None

for t in range(150):
    pressure = agressive_traffic_pattern(t)

    dominant = max(pressure, key=pressure.get)
    if dominant != last_dominant:
        change_time = t
        last_dominant = dominant

    controller.update_red_times(current_phase)
    switch, reason = controller.should_switch(current_phase, pressure)

    if switch:
        current_phase = controller.select_next_phase(pressure)

        if change_time and current_phase == dominant:
            adaptation_times.append(t - change_time)
            change_time = None

print("Adaptation times:", adaptation_times)

print(
    "Average adaptation time:",
    sum(adaptation_times) / len(adaptation_times)
)



