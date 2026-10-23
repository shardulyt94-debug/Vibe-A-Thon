from app.engine import (
    advance_clock,
    claim,
    make_shelter_unavailable,
)
from app.models import PortionStatus
from app.seed import seed_demo
from app.store import Store


def test_affected_rider_is_rerouted():
    store = seed_demo(Store())

    result = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    portion_id = result["portion_id"]

    # Rider donor tak pahunchta hai aur food pickup karta hai
    advance_clock(store, 10)

    assert (
        store.portions[portion_id].status
        == PortionStatus.IN_TRANSIT
    )

    result = make_shelter_unavailable(
        store,
        "shelter-a",
    )

    portion = store.portions[portion_id]

    assert result["ok"] is True
    assert portion.shelter_id != "shelter-a"
    assert portion_id in result["rerouted"]


def test_unrelated_rider_is_not_rerouted():
    store = seed_demo(Store())

    first = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    second = claim(
        store,
        "rider-2",
        "need-b-meals",
        "batch-meals",
    )

    make_shelter_unavailable(store, "shelter-a")

    assert store.portions[first["portion_id"]].shelter_id != "shelter-a"
    assert store.portions[second["portion_id"]].shelter_id == "shelter-b"


def test_no_fallback_marks_portion_at_risk():
    store = seed_demo(Store())

    result = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    portion_id = result["portion_id"]

    advance_clock(store, 10)

    # Baaki compatible shelters bhi unavailable kar do
    store.shelters["shelter-b"].status = (
        type(store.shelters["shelter-b"].status)
        .TEMPORARILY_UNAVAILABLE
    )

    store.shelters["shelter-c"].status = (
        type(store.shelters["shelter-c"].status)
        .TEMPORARILY_UNAVAILABLE
    )

    result = make_shelter_unavailable(
        store,
        "shelter-a",
    )

    assert result["ok"] is True
    assert portion_id in result["at_risk"]
    assert store.portions[portion_id].warned is True