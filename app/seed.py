from .models import Batch, Donor, Event, Need, Rider, Shelter
from .store import Store


def seed_demo(store: Store) -> Store:
    store.__dict__.update(Store().__dict__)
    store.donors.update({
        "donor-banquet": Donor("donor-banquet", "Banquet Hall", 1, 1),
        "donor-mess": Donor("donor-mess", "Community Mess", 8, 2),
    })
    store.shelters.update({
        "shelter-a": Shelter("shelter-a", "Shelter A", 4, 3, True, True),
        "shelter-b": Shelter("shelter-b", "Shelter B", 7, 5, True, True),
        "shelter-c": Shelter("shelter-c", "Shelter C", 2, 8, True, True),
        "shelter-d": Shelter("shelter-d", "Shelter D", 6, 1, True, False),
    })
    store.needs.update({
        "need-a-meals": Need("need-a-meals", "shelter-a", "cooked_meals", 50, 90),
        "need-b-meals": Need("need-b-meals", "shelter-b", "cooked_meals", 60, 90),
        "need-c-meals": Need("need-c-meals", "shelter-c", "cooked_meals", 40, 90),
        "need-d-ration": Need("need-d-ration", "shelter-d", "raw_ration", 30, 120),
    })
    store.batches.update({
        "batch-meals": Batch("batch-meals", "donor-banquet", "cooked_meals", 180, 75, 0),
        "batch-ration": Batch("batch-ration", "donor-mess", "raw_ration", 60, 120, 0),
    })
    for number in range(1, 5):
        store.riders[f"rider-{number}"] = Rider(
            f"rider-{number}", f"R{number}", 0, 0, 40
        )
    store.events.append(Event(0, "Demo data loaded"))
    return store
