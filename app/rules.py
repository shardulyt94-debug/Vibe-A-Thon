from .geo import travel_time
from .models import Batch, Need, PortionStatus, Rider, Shelter, ShelterStatus
from .store import Store

BUFFER_MINUTES = 5.0
LEASE_BUFFER_MINUTES = 5.0
MIN_LEASE_MINUTES = 10.0
HEARTBEAT_TIMEOUT_MINUTES = 10.0

# Batch pool se woh sabhi portions minus honge jo cancel nahi hue hain.
# EXPIRED aur WASTED khana physically batch se nikal chuka hai ya kharab ho chuka hai,
# isliye woh wapas donor pool mein nahi aayega (Fix #4).
BATCH_CONSUMED_STATUSES = {
    PortionStatus.CLAIMED.value,
    PortionStatus.IN_TRANSIT.value,
    PortionStatus.DELIVERED.value,
    PortionStatus.EXPIRED.value,
    PortionStatus.WASTED.value,
}

# Shelter ki need ke liye sirf active aur delivered portions count honge.
# Agar portion EXPIRED ya WASTED ho gaya, to shelter ki need abhi bhi adhuri hai.
NEED_COUNTED_STATUSES = {
    PortionStatus.CLAIMED.value,
    PortionStatus.IN_TRANSIT.value,
    PortionStatus.DELIVERED.value,
}


def is_compatible(item_type: str, shelter: Shelter) -> bool:
    if item_type == "raw_ration":
        return shelter.has_water and shelter.has_fuel
    if item_type == "infant_formula":
        return shelter.has_water
    return True


def remaining_batch_qty(store: Store, batch: Batch) -> int:
    now = store.clock.now()
    if now > batch.safe_until:
        return 0
    used = sum(
        portion.qty
        for portion in store.portions.values()
        if portion.batch_id == batch.id
        and portion.status.value in BATCH_CONSUMED_STATUSES
    )
    return max(0, batch.total_qty - used)


def remaining_need_qty(
    store: Store, need: Need, exclude_portion_id: str | None = None
) -> int:
    used = sum(
        portion.qty
        for portion in store.portions.values()
        if portion.need_id == need.id
        and portion.id != exclude_portion_id
        and portion.status.value in NEED_COUNTED_STATUSES
    )
    return max(0, need.qty - used)


def claim_quantity(store: Store, rider: Rider, need: Need, batch: Batch) -> int:
    return min(
        rider.capacity,
        remaining_need_qty(store, need),
        remaining_batch_qty(store, batch),
    )


def lease_expiry(
    store: Store,
    rider: Rider,
    donor_x: float,
    donor_y: float,
    shelter: Shelter,
    batch: Batch,
    need: Need | None = None,
) -> float:
    now = store.clock.now()
    rider_to_donor = travel_time((rider.x, rider.y), (donor_x, donor_y))
    donor_to_shelter = travel_time((donor_x, donor_y), (shelter.x, shelter.y))

    deadline = batch.safe_until
    if need is not None:
        deadline = min(deadline, need.need_by)

    latest_pickup = deadline - donor_to_shelter - BUFFER_MINUTES
    # Dynamic lease based on rider distance to donor + buffer (Fix #3)
    dynamic_window = max(MIN_LEASE_MINUTES, rider_to_donor + LEASE_BUFFER_MINUTES)
    return min(now + dynamic_window, latest_pickup)


def can_deliver(
    store: Store,
    rider: Rider,
    donor_x: float,
    donor_y: float,
    shelter: Shelter,
    batch: Batch,
    need: Need | None = None,
) -> tuple[bool, str]:
    if rider.frozen or rider.unresponsive:
        return False, f"REJECT: Rider {rider.name} is frozen or unresponsive"

    if shelter.status != ShelterStatus.OPEN:
        return False, f"REJECT: {shelter.name} is temporarily unavailable"

    if not is_compatible(batch.item_type, shelter):
        return False, f"REJECT: {batch.item_type} not compatible with {shelter.name}"

    now = store.clock.now()
    rider_to_donor = travel_time((rider.x, rider.y), (donor_x, donor_y))
    donor_to_shelter = travel_time((donor_x, donor_y), (shelter.x, shelter.y))
    pickup_eta = now + rider_to_donor
    eta = pickup_eta + donor_to_shelter + BUFFER_MINUTES

    if eta > batch.safe_until:
        return (
            False,
            f"REJECT: ETA {eta:.1f} min exceeds batch safe time {batch.safe_until:.1f} min",
        )

    # Fix #8: Enforce need_by deadline
    if need is not None and eta > need.need_by:
        return (
            False,
            f"REJECT: ETA {eta:.1f} min exceeds shelter need_by {need.need_by:.1f} min",
        )

    # Fix #3: Verify rider can reach donor before lease expires
    lease_exp = lease_expiry(store, rider, donor_x, donor_y, shelter, batch, need)
    if pickup_eta > lease_exp + 1e-9:
        return (
            False,
            f"REJECT: Pickup ETA {pickup_eta:.1f} min exceeds lease expiry {lease_exp:.1f} min",
        )

    return True, "OK"