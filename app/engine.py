from .geo import SPEED_KM_PER_MIN, distance
from .models import Event, Portion, PortionStatus
from .rules import (
    can_deliver,
    claim_quantity,
    is_compatible,
    lease_expiry,
    remaining_batch_qty,
    remaining_need_qty,
)
from .store import Store


def _has_active_portion(store: Store, rider_id: str) -> bool:
    return any(
        portion.rider_id == rider_id
        and portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
        for portion in store.portions.values()
    )


def list_cards_for_rider(store: Store, rider_id: str) -> list[dict]:
    rider = store.riders[rider_id]
    if _has_active_portion(store, rider_id):
        return []

    cards = []
    for need in store.needs.values():
        shelter = store.shelters[need.shelter_id]
        if shelter.status.value != "OPEN" or remaining_need_qty(store, need) <= 0:
            continue

        for batch in store.batches.values():
            if batch.item_type != need.item_type or remaining_batch_qty(store, batch) <= 0:
                continue
            if not is_compatible(batch.item_type, shelter):
                continue

            donor = store.donors[batch.donor_id]
            possible, reason = can_deliver(
                store, rider, donor.x, donor.y, shelter, batch
            )
            if possible:
                cards.append({
                    "need_id": need.id,
                    "batch_id": batch.id,
                    "shelter_id": shelter.id,
                    "shelter_name": shelter.name,
                    "item_type": batch.item_type,
                    "available_qty": claim_quantity(store, rider, need, batch),
                    "message": reason,
                })
    return cards


def claim(store: Store, rider_id: str, need_id: str, batch_id: str) -> dict:
    rider = store.riders[rider_id]
    need = store.needs[need_id]
    batch = store.batches[batch_id]
    shelter = store.shelters[need.shelter_id]
    donor = store.donors[batch.donor_id]

    if _has_active_portion(store, rider_id):
        return {"ok": False, "message": "REJECT: Rider already has an active delivery"}
    if shelter.status.value != "OPEN":
        return {"ok": False, "message": "REJECT: Shelter is temporarily unavailable"}
    if not is_compatible(batch.item_type, shelter):
        return {"ok": False, "message": "REJECT: Shelter is incompatible with this item"}

    quantity = claim_quantity(store, rider, need, batch)
    if quantity <= 0:
        return {"ok": False, "message": "REJECT: No quantity available"}

    possible, reason = can_deliver(
        store, rider, donor.x, donor.y, shelter, batch
    )
    if not possible:
        return {"ok": False, "message": reason}

    portion_id = f"portion-{len(store.portions) + 1}"
    portion = Portion(
        id=portion_id,
        batch_id=batch.id,
        need_id=need.id,
        shelter_id=shelter.id,
        rider_id=rider.id,
        qty=quantity,
        status=PortionStatus.CLAIMED,
        claim_expires_at=lease_expiry(
            store, donor.x, donor.y, shelter, batch
        ),
        checkpoint_time=store.clock.now(),
    )
    store.portions[portion.id] = portion
    store.events.append(Event(
        store.clock.now(),
        f"{rider.name} claimed {quantity} {batch.item_type} for {shelter.name}",
    ))

    return {
        "ok": True,
        "message": "Claim successful",
        "portion_id": portion.id,
        "quantity": quantity,
        "claim_expires_at": portion.claim_expires_at,
    }


def _move_rider_towards(rider, target_x: float, target_y: float, minutes: float) -> None:
    remaining = SPEED_KM_PER_MIN * minutes
    current_distance = distance((rider.x, rider.y), (target_x, target_y))
    if current_distance == 0:
        return
    if remaining >= current_distance:
        rider.x, rider.y = target_x, target_y
        return
    ratio = remaining / current_distance
    rider.x += (target_x - rider.x) * ratio
    rider.y += (target_y - rider.y) * ratio


def tick(store: Store) -> None:
    now = store.clock.now()

    for portion in store.portions.values():
        if portion.status == PortionStatus.CLAIMED and now > portion.claim_expires_at:
            portion.status = PortionStatus.CANCELLED
            store.events.append(Event(now, f"{portion.id} lease expired; claim cancelled"))
            continue

        batch = store.batches[portion.batch_id]
        if portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT} and now > batch.safe_until:
            portion.status = PortionStatus.EXPIRED
            store.events.append(Event(now, f"{portion.id} expired; food wasted"))
            continue

        rider = store.riders[portion.rider_id]
        donor = store.donors[batch.donor_id]
        shelter = store.shelters[portion.shelter_id]

        if portion.status == PortionStatus.CLAIMED:
            if distance((rider.x, rider.y), (donor.x, donor.y)) <= 0.2:
                rider.x, rider.y = donor.x, donor.y
                portion.status = PortionStatus.IN_TRANSIT
                store.events.append(Event(now, f"{rider.name} picked up {portion.qty} items"))
        elif portion.status == PortionStatus.IN_TRANSIT:
            if distance((rider.x, rider.y), (shelter.x, shelter.y)) <= 0.2:
                rider.x, rider.y = shelter.x, shelter.y
                portion.status = PortionStatus.DELIVERED
                store.events.append(Event(now, f"{rider.name} delivered {portion.qty} items to {shelter.name}"))


def advance_clock(store: Store, minutes: float) -> float:
    if minutes <= 0:
        raise ValueError("minutes must be greater than zero")

    active_portions = [
        portion for portion in store.portions.values()
        if portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
    ]
    for portion in active_portions:
        rider = store.riders[portion.rider_id]
        if rider.frozen:
            continue
        batch = store.batches[portion.batch_id]
        if portion.status == PortionStatus.CLAIMED:
            target = store.donors[batch.donor_id]
        else:
            target = store.shelters[portion.shelter_id]
        _move_rider_towards(rider, target.x, target.y, minutes)
        rider.last_ping = store.clock.now() + minutes

    now = store.clock.advance(minutes)
    tick(store)
    return now

def cancel_portion(store: Store, portion_id: str) -> dict:
    if portion_id not in store.portions:
        return {
            "ok": False,
            "message": "REJECT: Portion not found",
        }

    portion = store.portions[portion_id]

    if portion.status == PortionStatus.CANCELLED:
        return {
            "ok": True,
            "message": "Portion already cancelled",
        }

    if portion.status == PortionStatus.DELIVERED:
        return {
            "ok": False,
            "message": "REJECT: Food already delivered",
        }

    if portion.status == PortionStatus.EXPIRED:
        return {
            "ok": False,
            "message": "REJECT: Food already expired",
        }

    if portion.status == PortionStatus.IN_TRANSIT:
        return {
            "ok": False,
            "message": "REJECT: Pickup ke baad cancellation allowed nahi",
        }

    if portion.status == PortionStatus.CLAIMED:
        portion.status = PortionStatus.CANCELLED

        rider = store.riders[portion.rider_id]

        store.events.append(
            Event(
                store.clock.now(),
                f"{rider.name} cancelled claim {portion.id}; "
                f"{portion.qty} items returned to pool",
            )
        )

        return {
            "ok": True,
            "message": "Claim cancelled; food returned to pool",
            "portion_id": portion.id,
            "quantity_returned": portion.qty,
        }

    return {
        "ok": False,
        "message": "REJECT: Portion cannot be cancelled",
    }