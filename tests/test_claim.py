from app.engine import claim, list_cards_for_rider
from app.models import PortionStatus
from app.seed import seed_demo
from app.store import Store


def test_claim_respects_rider_capacity():
    store = seed_demo(Store())

    result = claim(
        store,
        rider_id="rider-1",
        need_id="need-a-meals",
        batch_id="batch-meals",
    )

    assert result["ok"] is True
    assert result["quantity"] == 40
    assert len(store.portions) == 1


def test_second_rider_gets_remaining_need_quantity():
    store = seed_demo(Store())

    first = claim(store, "rider-1", "need-a-meals", "batch-meals")
    second = claim(store, "rider-2", "need-a-meals", "batch-meals")

    assert first["quantity"] == 40
    assert second["quantity"] == 10


def test_incompatible_shelter_is_not_shown():
    store = seed_demo(Store())

    cards = list_cards_for_rider(store, "rider-1")

    ration_cards = [
        card
        for card in cards
        if card["item_type"] == "raw_ration"
    ]

    assert ration_cards == []