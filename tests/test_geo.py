from app.geo import distance, travel_time


def test_travel_time_uses_demo_speed():
    assert distance((0, 0), (4, 0)) == 4
    assert travel_time((0, 0), (4, 0)) == 10
