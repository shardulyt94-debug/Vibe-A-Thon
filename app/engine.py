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


def list_cards_for_rider(store: Store, rider_id: str) -> list[dict]:
    rider = store.riders[rider_id]
    cards = []

    has_active_portion = any(
        portion.rider_id == rider_id
        and portion.status in {
            PortionStatus.CLAIMED,
            PortionStatus.IN_TRANSIT,
        }
        for portion in store.portions.values()
    )

    if has_active_portion:
        return []

    for need in store.needs.values():
        shelter = store.shelters[need.shelter_id]

        if shelter.status.value != "OPEN":
            continue

        if remaining_need_qty(store, need) <= 0:
            continue

        for batch in store.batches.values():
            if batch.item_type != need.item_type:
                continue

            if remaining_batch_qty(store, batch) <= 0:
                continue

            if not is_compatible(batch.item_type, shelter):
                continue

            donor = store.donors[batch.donor_id]

            possible, reason = can_deliver(
                store,
                rider,
                donor.x,
                donor.y,
                shelter,
                batch,
            )

            if not possible:
                continue

            cards.append({
                "need_id": need.id,
                "batch_id": batch.id,
                "shelter_id": shelter.id,
                "shelter_name": shelter.name,
                "item_type": batch.item_type,
                "available_qty": claim_quantity(
                    store,
                    rider,
                    need,
                    batch,
                ),
                "message": reason,
            })

    return cards


def claim(
    store: Store,
    rider_id: str,
    need_id: str,
    batch_id: str,
) -> dict:
    rider = store.riders[rider_id]
    need = store.needs[need_id]
    batch = store.batches[batch_id]
    shelter = store.shelters[need.shelter_id]
    donor = store.donors[batch.donor_id]

    if any(
        portion.rider_id == rider_id
        and portion.status in {
            PortionStatus.CLAIMED,
            PortionStatus.IN_TRANSIT,
        }
        for portion in store.portions.values()
    ):
        return {
            "ok": False,
            "message": "REJECT: Rider already has an active delivery",
        }

    if shelter.status.value != "OPEN":
        return {
            "ok": False,
            "message": "REJECT: Shelter is temporarily unavailable",
        }

    if not is_compatible(batch.item_type, shelter):
        return {
            "ok": False,
            "message": "REJECT: Shelter is incompatible with this item",
        }

    quantity = claim_quantity(store, rider, need, batch)

    if quantity <= 0:
        return {
            "ok": False,
            "message": "REJECT: No quantity available",
        }

    possible, reason = can_deliver(
        store,
        rider,
        donor.x,
        donor.y,
        shelter,
        batch,
    )

    if not possible:
        return {
            "ok": False,
            "message": reason,
        }

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
            store,
            donor.x,
            donor.y,
            shelter,
            batch,
        ),
        checkpoint_time=store.clock.now(),
    )

    store.portions[portion.id] = portion
    store.events.append(
        Event(
            store.clock.now(),
            f"{rider.name} claimed {quantity} {batch.item_type} "
            f"for {shelter.name}",
        )
    )

    return {
        "ok": True,
        "message": "Claim successful",
        "portion_id": portion.id,
        "quantity": quantity,
        "claim_expires_at": portion.claim_expires_at,
    }