from app.engine import advance_clock, claim
from app.models import PortionStatus
from app.seed import seed_demo
from app.store import Store


def test_claimed_rider_reaches_donor_and_then_shelter():
    store = seed_demo(Store())
    result = claim(store, "rider-1", "need-a-meals", "batch-meals")
    portion = store.portions[result["portion_id"]]

    advance_clock(store, 10)
    assert portion.status == PortionStatus.IN_TRANSIT

    advance_clock(store, 10)
    assert portion.status == PortionStatus.DELIVERED


def test_frozen_rider_does_not_move():
    store = seed_demo(Store())
    result = claim(store, "rider-1", "need-a-meals", "batch-meals")
    rider = store.riders["rider-1"]
    rider.frozen = True
    before = (rider.x, rider.y)

    advance_clock(store, 5)

    assert (rider.x, rider.y) == before
    assert store.portions[result["portion_id"]].status == PortionStatus.CLAIMED


def test_lease_expiry_cancels_unpicked_claim():
    store = seed_demo(Store())
    result = claim(store, "rider-1", "need-a-meals", "batch-meals")
    rider = store.riders["rider-1"]
    rider.frozen = True

    advance_clock(store, 11)

    assert store.portions[result["portion_id"]].status == PortionStatus.CANCELLED
