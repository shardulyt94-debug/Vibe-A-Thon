class FakeClock:
    """A deterministic clock for demos and tests."""

    def __init__(self) -> None:
        self.minutes = 0.0

    def now(self) -> float:
        return self.minutes

    def advance(self, minutes: float) -> float:
        if minutes <= 0:
            raise ValueError("minutes must be greater than zero")
        self.minutes += minutes
        return self.minutes

    def reset(self) -> None:
        self.minutes = 0.0
