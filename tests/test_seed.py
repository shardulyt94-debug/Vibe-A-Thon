from app.seed import seed_demo
from app.store import Store


def test_demo_seed_has_core_entities():
    store = seed_demo(Store())
    assert len(store.donors) == 2
    assert len(store.shelters) == 4
    assert len(store.riders) == 4
    assert store.batches["batch-meals"].total_qty == 180
