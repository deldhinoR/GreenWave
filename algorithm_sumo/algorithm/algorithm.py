class AdaptiveController:

    print("NEW CONTROLLER LOADED")

    def __init__(self,
        min_green=15,
        max_green=60,
        max_red_limit=90,
        phase_count=4,
        alpha=1.5,
        beta=1.5,
        gamma=2.0,
        hysteresis_threshold=15,
        cooldown=5,
        switch_penalty=6.0,
        dynamic_hysteresis_min=8.0,
        dynamic_hysteresis_max=24.0,
    ):

        self.min_green = min_green
        self.max_green = max_green
        self.max_red_limit = max_red_limit
        self.phase_count = phase_count

        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.hysteresis_threshold = hysteresis_threshold
        self.switch_penalty = switch_penalty
        self.dynamic_hysteresis_min = dynamic_hysteresis_min
        self.dynamic_hysteresis_max = dynamic_hysteresis_max

        self.cooldown = cooldown
        self.cooldown_timer = 0

        self.red_elapsed = {i: 0 for i in range(phase_count)}
        self.green_elapsed = {i: 0 for i in range(phase_count)}
        self.max_red_observed = {i: 0 for i in range(phase_count)}

        self.force_switch_to = None

    def _total_pressure(self, phase_pressure):
        return float(sum(max(0.0, float(v)) for v in phase_pressure.values()))

    def _dynamic_hysteresis(self, phase_pressure):
        total_p = self._total_pressure(phase_pressure)
        # High traffic -> lower threshold (more responsive)
        # Low traffic -> higher threshold (fewer unnecessary switches)
        ratio = min(1.0, total_p / 20.0)
        return (
            self.dynamic_hysteresis_max
            - (self.dynamic_hysteresis_max - self.dynamic_hysteresis_min) * ratio
        )

    # --------------------------
    # TIME UPDATE
    # --------------------------

    def update_red_times(self, current_phase):

        self.force_switch_to = None

        for phase in range(self.phase_count):

            if phase == current_phase:
                self.green_elapsed[phase] += 1
                self.red_elapsed[phase] = 0
            else:
                self.red_elapsed[phase] += 1
                self.green_elapsed[phase] = 0

                self.max_red_observed[phase] = max(
                    self.max_red_observed[phase],
                    self.red_elapsed[phase]
                )

                # HARD safety only
                if self.red_elapsed[phase] >= self.max_red_limit:
                    self.force_switch_to = phase

        if self.cooldown_timer > 0:
            self.cooldown_timer -= 1

    # --------------------------
    # SCORE (CORE DECISION)
    # --------------------------

    def compute_scores(self, phase_pressure, current_phase):

        scores = {}
        CURRENT_PHASE_BONUS = 10

        for phase in range(self.phase_count):

            # normalize red to avoid explosion
            normalized_red = min(self.red_elapsed[phase], 30)
            normalized_queue = phase_pressure.get(phase, 0) / 10

            score = (
                self.alpha * normalized_queue
                + self.beta * normalized_red
                - self.gamma * self.green_elapsed[phase]
            )

            # stay bias
            if phase == current_phase:
                score += CURRENT_PHASE_BONUS
            else:
                # switching has lost-time cost (yellow/all-red, restart friction)
                score -= self.switch_penalty

            scores[phase] = score

        return scores

    # --------------------------
    # DECISION (SCORE FIRST)
    # --------------------------

    def should_switch(self, current_phase, phase_pressure, emergency_phase=None):

        # 1) Emergency override
        if emergency_phase is not None and emergency_phase != current_phase:
            return True, "EMERGENCY"

        # 2) Hard starvation (safety)
        if self.force_switch_to is not None:
            return True, "HARD_MAX_RED"

        # 3) Min green constraint (stability)
        if self.green_elapsed[current_phase] < self.min_green:
            return False, "MIN_GREEN"

        # 4) Cooldown
        if self.cooldown_timer > 0:
            return False, "COOLDOWN"

        # 5) SCORE-BASED DECISION (MAIN)
        scores = self.compute_scores(phase_pressure, current_phase)

        best_phase = max(scores, key=scores.get)
        diff = scores[best_phase] - scores[current_phase]

        dynamic_threshold = max(
            self.hysteresis_threshold,
            self._dynamic_hysteresis(phase_pressure),
        )

        # switch only if clearly better
        if best_phase != current_phase and diff >= dynamic_threshold:
            return True, "SCORE_SWITCH"

        # 6) Hard max green: enforce turnover to prevent long monopolization.
        if self.green_elapsed[current_phase] >= self.max_green:
            if best_phase != current_phase:
                return True, "HARD_MAX_GREEN"
            return True, "HARD_MAX_GREEN_ROUND_ROBIN"

        return False, "CONTINUE"

    # --------------------------
    # NEXT PHASE
    # --------------------------

    def select_next_phase(self, phase_pressure, current_phase, emergency_phase=None):

        if emergency_phase is not None:
            return emergency_phase

        if self.force_switch_to is not None:
            return self.force_switch_to

        scores = self.compute_scores(phase_pressure, current_phase)
        next_phase = max(scores, key=scores.get)

        if next_phase == current_phase and self.green_elapsed[current_phase] >= self.max_green:
            # Fairness fallback when max_green reached but scores are tied/biased to current.
            next_phase = (current_phase + 1) % self.phase_count

        self.cooldown_timer = self.cooldown

        return next_phase
    

















