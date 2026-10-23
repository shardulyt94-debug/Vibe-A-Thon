import pytest

from app.clock import FakeClock


def test_clock_advances_deterministically():
    clock = FakeClock()
    assert clock.now() == 0
    clock.advance(10)
    assert clock.now() == 10


def test_clock_rejects_non_positive_advance():
    with pytest.raises(ValueError):
        FakeClock().advance(0)
