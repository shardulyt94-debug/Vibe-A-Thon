from math import hypot

SPEED_KM_PER_MIN = 0.4


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def travel_time(a: tuple[float, float], b: tuple[float, float]) -> float:
    return distance(a, b) / SPEED_KM_PER_MIN
