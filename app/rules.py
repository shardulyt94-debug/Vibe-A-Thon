from .geo import travel_time
from .models import Batch, Need, Rider, Shelter
from .store import Store

BUFFER_MINUTES = 5
MAX_LEASE_MINUTES = 10


def is_compatible(item_type: str, shelter: Shelter) -> bool:
    if item_type == "raw_ration":
        return shelter.has_water and shelter.has_fuel

    if item_type == "infant_formula":
        return shelter.has_water

    return True


def remaining_batch_qty(store: Store, batch: Batch) -> int:
    used = sum(
        portion.qty
        for portion in store.portions.values()
        if portion.batch_id == batch.id
        and portion.status.value in {"CLAIMED", "IN_TRANSIT", "DELIVERED"}
    )
    return max(0, batch.total_qty - used)


def remaining_need_qty(store: Store, need: Need) -> int:
    used = sum(
        portion.qty
        for portion in store.portions.values()
        if portion.need_id == need.id
        and portion.status.value in {"CLAIMED", "IN_TRANSIT", "DELIVERED"}
    )
    return max(0, need.qty - used)


def claim_quantity(
    store: Store,
    rider: Rider,
    need: Need,
    batch: Batch,
) -> int:
    return min(
        rider.capacity,
        remaining_need_qty(store, need),
        remaining_batch_qty(store, batch),
    )


def can_deliver(
    store: Store,
    rider: Rider,
    donor_x: float,
    donor_y: float,
    shelter: Shelter,
    batch: Batch,
) -> tuple[bool, str]:
    rider_to_donor = travel_time((rider.x, rider.y), (donor_x, donor_y))
    donor_to_shelter = travel_time(
        (donor_x, donor_y),
        (shelter.x, shelter.y),
    )

    total_time = store.clock.now() + rider_to_donor + donor_to_shelter + BUFFER_MINUTES

    if total_time > batch.safe_until:
        return (
            False,
            f"REJECT: ETA {total_time:.1f} min exceeds safe time "
            f"{batch.safe_until:.1f} min",
        )

    return True, "OK"


def lease_expiry(
    store: Store,
    donor_x: float,
    donor_y: float,
    shelter: Shelter,
    batch: Batch,
) -> float:
    donor_to_shelter = travel_time(
        (donor_x, donor_y),
        (shelter.x, shelter.y),
    )

    latest_pickup = batch.safe_until - donor_to_shelter - BUFFER_MINUTES
    max_lease = store.clock.now() + MAX_LEASE_MINUTES

    return min(max_lease, latest_pickup)