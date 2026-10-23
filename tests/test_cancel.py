from app.engine import advance_clock, cancel_portion, claim
from app.models import PortionStatus
from app.seed import seed_demo
from app.store import Store


def test_claimed_portion_can_be_cancelled():
    store = seed_demo(Store())

    result = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    cancel_result = cancel_portion(
        store,
        result["portion_id"],
    )

    assert cancel_result["ok"] is True
    assert cancel_result["quantity_returned"] == 40
    assert (
        store.portions[result["portion_id"]].status
        == PortionStatus.CANCELLED
    )


def test_in_transit_portion_cannot_be_cancelled():
    store = seed_demo(Store())

    result = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    advance_clock(store, 10)

    cancel_result = cancel_portion(
        store,
        result["portion_id"],
    )

    assert cancel_result["ok"] is False
    assert "pickup ke baad" in cancel_result["message"].lower()


def test_repeated_cancel_is_safe():
    store = seed_demo(Store())

    result = claim(
        store,
        "rider-1",
        "need-a-meals",
        "batch-meals",
    )

    portion_id = result["portion_id"]

    first = cancel_portion(store, portion_id)
    second = cancel_portion(store, portion_id)

    assert first["ok"] is True
    assert second["ok"] is True
    assert store.portions[portion_id].status == PortionStatus.CANCELLED