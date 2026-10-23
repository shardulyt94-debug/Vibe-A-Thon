from .geo import SPEED_KM_PER_MIN, distance, travel_time
from .models import (
    Batch,
    Donor,
    Event,
    Need,
    Portion,
    PortionStatus,
    Rider,
    Shelter,
    ShelterStatus,
)
from .rules import (
    BUFFER_MINUTES,
    HEARTBEAT_TIMEOUT_MINUTES,
    can_deliver,
    claim_quantity,
    is_compatible,
    lease_expiry,
    remaining_batch_qty,
    remaining_need_qty,
)
from .store import Store

STEP_MINUTES = 1.0
MAX_ADVANCE_MINUTES = 1440


def _has_active_portion(store: Store, rider_id: str) -> bool:
    return any(
        portion.rider_id == rider_id
        and portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
        for portion in store.portions.values()
    )


# --- Fix #1: Entity Creation Functions ---


def add_donor(
    store: Store, donor_id: str | None, name: str, x: float, y: float
) -> dict:
    did = donor_id or f"donor-{len(store.donors) + 1}"
    if did in store.donors:
        return {"ok": False, "message": f"REJECT: Donor '{did}' already exists"}
    donor = Donor(id=did, name=name, x=x, y=y)
    store.donors[did] = donor
    store.events.append(Event(store.clock.now(), f"Donor added: {name} ({did})"))
    return {"ok": True, "donor": donor}


def add_batch(
    store: Store,
    batch_id: str | None,
    donor_id: str,
    item_type: str,
    total_qty: int,
    safe_until: float,
    created_at: float | None = None,
) -> dict:
    if donor_id not in store.donors:
        return {"ok": False, "message": f"REJECT: Donor '{donor_id}' not found"}
    if total_qty <= 0:
        return {"ok": False, "message": "REJECT: total_qty must be positive"}
    bid = batch_id or f"batch-{len(store.batches) + 1}"
    if bid in store.batches:
        return {"ok": False, "message": f"REJECT: Batch '{bid}' already exists"}
    now = store.clock.now() if created_at is None else created_at
    batch = Batch(
        id=bid,
        donor_id=donor_id,
        item_type=item_type,
        total_qty=total_qty,
        safe_until=safe_until,
        created_at=now,
    )
    store.batches[bid] = batch
    store.events.append(
        Event(
            store.clock.now(),
            f"Batch created: {bid} ({total_qty} {item_type}, safe until {safe_until}m)",
        )
    )
    # Check if any at-risk portions can be resolved or new matches made
    _retry_at_risk_portions(store)
    return {"ok": True, "batch": batch}


def add_shelter(
    store: Store,
    shelter_id: str | None,
    name: str,
    x: float,
    y: float,
    has_water: bool = True,
    has_fuel: bool = True,
    status: str = "OPEN",
) -> dict:
    sid = shelter_id or f"shelter-{len(store.shelters) + 1}"
    if sid in store.shelters:
        return {"ok": False, "message": f"REJECT: Shelter '{sid}' already exists"}
    try:
        shelter_status = ShelterStatus(status)
    except ValueError:
        return {"ok": False, "message": f"REJECT: Invalid shelter status '{status}'"}
    shelter = Shelter(
        id=sid,
        name=name,
        x=x,
        y=y,
        has_water=has_water,
        has_fuel=has_fuel,
        status=shelter_status,
    )
    store.shelters[sid] = shelter
    store.events.append(Event(store.clock.now(), f"Shelter added: {name} ({sid})"))
    _retry_at_risk_portions(store)
    return {"ok": True, "shelter": shelter}


def add_need(
    store: Store,
    need_id: str | None,
    shelter_id: str,
    item_type: str,
    qty: int,
    need_by: float,
) -> dict:
    if shelter_id not in store.shelters:
        return {"ok": False, "message": f"REJECT: Shelter '{shelter_id}' not found"}
    if qty < 0:
        return {"ok": False, "message": "REJECT: qty cannot be negative"}
    nid = need_id or f"need-{len(store.needs) + 1}"
    if nid in store.needs:
        return {"ok": False, "message": f"REJECT: Need '{nid}' already exists"}
    need = Need(
        id=nid,
        shelter_id=shelter_id,
        item_type=item_type,
        qty=qty,
        need_by=need_by,
    )
    store.needs[nid] = need
    store.events.append(
        Event(
            store.clock.now(),
            f"Need added: {nid} at {store.shelters[shelter_id].name} ({qty} {item_type}, need by {need_by}m)",
        )
    )
    _retry_at_risk_portions(store)
    return {"ok": True, "need": need}


def add_rider(
    store: Store,
    rider_id: str | None,
    name: str,
    x: float,
    y: float,
    capacity: int = 40,
) -> dict:
    if capacity <= 0:
        return {"ok": False, "message": "REJECT: capacity must be positive"}
    rid = rider_id or f"rider-{len(store.riders) + 1}"
    if rid in store.riders:
        return {"ok": False, "message": f"REJECT: Rider '{rid}' already exists"}
    rider = Rider(
        id=rid,
        name=name,
        x=x,
        y=y,
        capacity=capacity,
        frozen=False,
        last_ping=store.clock.now(),
        unresponsive=False,
    )
    store.riders[rid] = rider
    store.events.append(Event(store.clock.now(), f"Rider added: {name} ({rid})"))
    return {"ok": True, "rider": rider}


# --- Core Rerouting & At-Risk Helper Logic (Fixes #2, #4, #6, #7, #8, #10) ---


def _find_best_candidate_need(
    store: Store,
    portion: Portion,
    exclude_shelter_id: str | None = None,
    exclude_need_id: str | None = None,
) -> tuple[float, Need, Shelter] | None:
    batch = store.batches[portion.batch_id]
    rider = store.riders[portion.rider_id]
    donor = store.donors[batch.donor_id]
    now = store.clock.now()

    candidates: list[tuple[float, Need, Shelter]] = []

    for need in store.needs.values():
        if exclude_need_id and need.id == exclude_need_id:
            continue
        candidate_shelter = store.shelters[need.shelter_id]
        if exclude_shelter_id and candidate_shelter.id == exclude_shelter_id:
            continue
        if candidate_shelter.status != ShelterStatus.OPEN:
            continue
        if need.item_type != batch.item_type:
            continue
        if not is_compatible(batch.item_type, candidate_shelter):
            continue
        if remaining_need_qty(store, need, exclude_portion_id=portion.id) < portion.qty:
            continue

        candidate_pos = (candidate_shelter.x, candidate_shelter.y)
        if portion.status == PortionStatus.CLAIMED:
            route_time = travel_time((rider.x, rider.y), (donor.x, donor.y)) + travel_time(
                (donor.x, donor.y), candidate_pos
            )
        else:
            route_time = travel_time((rider.x, rider.y), candidate_pos)

        eta = now + route_time + BUFFER_MINUTES
        if eta > batch.safe_until or eta > need.need_by:
            continue

        if portion.status == PortionStatus.CLAIMED:
            new_lease = lease_expiry(
                store,
                rider,
                donor.x,
                donor.y,
                candidate_shelter,
                batch,
                need,
            )
            pickup_eta = now + travel_time((rider.x, rider.y), (donor.x, donor.y))
            if pickup_eta > new_lease + 1e-9:
                continue

        candidates.append((eta, need, candidate_shelter))

    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])


def _reroute_or_handle_affected_portion(
    store: Store,
    portion: Portion,
    reason: str,
    exclude_shelter_id: str | None = None,
    exclude_need_id: str | None = None,
) -> str:
    """
    Attempts to reroute an active portion.
    Returns: 'rerouted', 'cancelled' (if CLAIMED and no fallback), or 'at_risk' (if IN_TRANSIT and no fallback).
    """
    now = store.clock.now()
    batch = store.batches[portion.batch_id]
    rider = store.riders[portion.rider_id]
    donor = store.donors[batch.donor_id]
    old_shelter = store.shelters[portion.shelter_id]

    best = _find_best_candidate_need(
        store,
        portion,
        exclude_shelter_id=exclude_shelter_id,
        exclude_need_id=exclude_need_id,
    )

    if best is not None:
        _, new_need, new_shelter = best
        portion.shelter_id = new_shelter.id
        portion.need_id = new_need.id
        portion.warned = False
        portion.at_risk = False

        # Fix #6: Recompute claim_expires_at after reroute for CLAIMED portions
        if portion.status == PortionStatus.CLAIMED:
            portion.claim_expires_at = lease_expiry(
                store,
                rider,
                donor.x,
                donor.y,
                new_shelter,
                batch,
                new_need,
            )

        store.events.append(
            Event(
                now,
                f"{portion.id} rerouted from {old_shelter.name} to {new_shelter.name} ({reason})",
            )
        )
        return "rerouted"

    # Fix #7: If no alternative shelter found:
    # - Immediately cancel CLAIMED portions so food returns to donor pool for other needs/riders
    if portion.status == PortionStatus.CLAIMED:
        portion.status = PortionStatus.CANCELLED
        portion.at_risk = False
        store.events.append(
            Event(
                now,
                f"{portion.id} auto-cancelled ({reason}); no fallback shelter, {portion.qty} items returned to pool",
            )
        )
        return "cancelled"

    # - Mark IN_TRANSIT portions as at_risk so tick() can re-evaluate them every step
    portion.warned = True
    portion.at_risk = True
    store.events.append(
        Event(
            now,
            f"AT RISK: No fallback shelter for in-transit {portion.id} ({reason})",
        )
    )
    return "at_risk"


def _is_current_destination_valid(store: Store, portion: Portion) -> bool:
    shelter = store.shelters[portion.shelter_id]
    need = store.needs[portion.need_id]
    batch = store.batches[portion.batch_id]
    rider = store.riders[portion.rider_id]
    now = store.clock.now()

    if shelter.status != ShelterStatus.OPEN:
        return False
    if not is_compatible(batch.item_type, shelter):
        return False
    if remaining_need_qty(store, need, exclude_portion_id=portion.id) < portion.qty:
        return False

    eta = now + travel_time((rider.x, rider.y), (shelter.x, shelter.y))
    if eta > batch.safe_until or eta > need.need_by:
        return False
    return True


def _retry_at_risk_portions(store: Store) -> None:
    """Fix #7: On every tick or state update, re-check at-risk portions for newly available options."""
    now = store.clock.now()
    for portion in list(store.portions.values()):
        if not portion.at_risk:
            continue
        if portion.status not in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}:
            portion.at_risk = False
            continue

        rider = store.riders[portion.rider_id]
        if rider.frozen or rider.unresponsive:
            continue

        # First check if original destination became valid again (e.g. shelter reopened or water restored)
        if _is_current_destination_valid(store, portion):
            portion.at_risk = False
            portion.warned = False
            shelter = store.shelters[portion.shelter_id]
            store.events.append(
                Event(
                    now,
                    f"{portion.id} no longer at risk; destination {shelter.name} is valid again",
                )
            )
            continue

        # Otherwise check if another candidate need/shelter is now viable
        best = _find_best_candidate_need(store, portion)
        if best is not None:
            _, new_need, new_shelter = best
            old_shelter = store.shelters[portion.shelter_id]
            portion.shelter_id = new_shelter.id
            portion.need_id = new_need.id
            portion.at_risk = False
            portion.warned = False
            store.events.append(
                Event(
                    now,
                    f"AT-RISK RESOLVED: {portion.id} rerouted from {old_shelter.name} to {new_shelter.name}",
                )
            )


# --- Listing & Claiming ---


def list_cards_for_rider(store: Store, rider_id: str) -> list[dict]:
    rider = store.riders[rider_id]
    if rider.frozen or rider.unresponsive or _has_active_portion(store, rider_id):
        return []

    cards = []
    for need in store.needs.values():
        shelter = store.shelters[need.shelter_id]
        if shelter.status != ShelterStatus.OPEN or remaining_need_qty(store, need) <= 0:
            continue

        for batch in store.batches.values():
            if (
                batch.item_type != need.item_type
                or remaining_batch_qty(store, batch) <= 0
            ):
                continue
            if not is_compatible(batch.item_type, shelter):
                continue

            donor = store.donors[batch.donor_id]
            possible, reason = can_deliver(
                store, rider, donor.x, donor.y, shelter, batch, need
            )
            if possible:
                qty = claim_quantity(store, rider, need, batch)
                if qty > 0:
                    cards.append(
                        {
                            "need_id": need.id,
                            "batch_id": batch.id,
                            "shelter_id": shelter.id,
                            "shelter_name": shelter.name,
                            "item_type": batch.item_type,
                            "available_qty": qty,
                            "message": reason,
                        }
                    )
    return cards


def claim(store: Store, rider_id: str, need_id: str, batch_id: str) -> dict:
    rider = store.riders[rider_id]
    need = store.needs[need_id]
    batch = store.batches[batch_id]
    shelter = store.shelters[need.shelter_id]
    donor = store.donors[batch.donor_id]

    if _has_active_portion(store, rider_id):
        return {"ok": False, "message": "REJECT: Rider already has an active delivery"}
    if rider.frozen or rider.unresponsive:
        return {"ok": False, "message": "REJECT: Rider is frozen or unresponsive"}
    if need.item_type != batch.item_type:
        return {"ok": False, "message": "REJECT: Need and batch item types do not match"}
    if shelter.status != ShelterStatus.OPEN:
        return {"ok": False, "message": "REJECT: Shelter is temporarily unavailable"}
    if not is_compatible(batch.item_type, shelter):
        return {"ok": False, "message": "REJECT: Shelter is incompatible with this item"}

    quantity = claim_quantity(store, rider, need, batch)
    if quantity <= 0:
        return {"ok": False, "message": "REJECT: No quantity available"}

    possible, reason = can_deliver(
        store, rider, donor.x, donor.y, shelter, batch, need
    )
    if not possible:
        return {"ok": False, "message": reason}

    now = store.clock.now()
    rider.last_ping = now

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
            store, rider, donor.x, donor.y, shelter, batch, need
        ),
        checkpoint_time=now,
    )
    store.portions[portion.id] = portion
    store.events.append(
        Event(
            now,
            f"{rider.name} claimed {quantity} {batch.item_type} for {shelter.name}",
        )
    )

    return {
        "ok": True,
        "message": "Claim successful",
        "portion_id": portion.id,
        "quantity": quantity,
        "claim_expires_at": portion.claim_expires_at,
    }


# --- Simulation Movement & Tick ---


def _move_rider_towards(
    rider: Rider, target_x: float, target_y: float, minutes: float
) -> None:
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

    # Fix #7: Re-evaluate at-risk portions on each tick
    _retry_at_risk_portions(store)

    for portion in store.portions.values():
        if portion.status not in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}:
            continue

        batch = store.batches[portion.batch_id]
        need = store.needs[portion.need_id]
        rider = store.riders[portion.rider_id]
        donor = store.donors[batch.donor_id]
        shelter = store.shelters[portion.shelter_id]

        # 1. Check food safety expiry
        if now > batch.safe_until:
            portion.status = PortionStatus.EXPIRED
            portion.at_risk = False
            store.events.append(Event(now, f"{portion.id} expired; food wasted"))
            continue

        # 2. Check lease expiry for CLAIMED portions
        if portion.status == PortionStatus.CLAIMED and now > portion.claim_expires_at:
            portion.status = PortionStatus.CANCELLED
            portion.at_risk = False
            store.events.append(
                Event(now, f"{portion.id} lease expired; claim cancelled")
            )
            continue

        # 3. Fix #5: Check heartbeat timeout for frozen/unresponsive riders
        if now - rider.last_ping > HEARTBEAT_TIMEOUT_MINUTES:
            if not rider.unresponsive:
                rider.unresponsive = True
                store.events.append(
                    Event(
                        now,
                        f"ALERT: Rider {rider.name} unresponsive (last ping at {rider.last_ping:.1f}m)",
                    )
                )
            if portion.status == PortionStatus.CLAIMED:
                portion.status = PortionStatus.CANCELLED
                portion.at_risk = False
                store.events.append(
                    Event(
                        now,
                        f"{portion.id} auto-cancelled because rider {rider.name} is unresponsive; food returned to pool",
                    )
                )
                continue
            elif portion.status == PortionStatus.IN_TRANSIT and not portion.at_risk:
                portion.at_risk = True
                portion.warned = True
                store.events.append(
                    Event(
                        now,
                        f"ALERT: {portion.id} AT RISK with unresponsive rider {rider.name} in transit",
                    )
                )
                continue

        # 4. Handle pickup and delivery arrival
        if portion.status == PortionStatus.CLAIMED:
            if distance((rider.x, rider.y), (donor.x, donor.y)) <= 0.2:
                rider.x, rider.y = donor.x, donor.y
                portion.status = PortionStatus.IN_TRANSIT
                store.events.append(
                    Event(now, f"{rider.name} picked up {portion.qty} items")
                )
        elif portion.status == PortionStatus.IN_TRANSIT:
            if distance((rider.x, rider.y), (shelter.x, shelter.y)) <= 0.2:
                rider.x, rider.y = shelter.x, shelter.y

                # Fix #8 & #10: Re-verify shelter status, compatibility, need_by, and remaining need on arrival
                unfulfilled_need = remaining_need_qty(
                    store, need, exclude_portion_id=portion.id
                )
                can_complete = (
                    shelter.status == ShelterStatus.OPEN
                    and is_compatible(batch.item_type, shelter)
                    and now <= need.need_by
                    and unfulfilled_need >= portion.qty
                )

                if not can_complete:
                    # Try rerouting immediately if arrival shelter cannot accept delivery
                    _reroute_or_handle_affected_portion(
                        store,
                        portion,
                        reason=f"{shelter.name} unavailable, incompatible, or need already met on arrival",
                        exclude_need_id=need.id if unfulfilled_need < portion.qty else None,
                    )
                else:
                    portion.status = PortionStatus.DELIVERED
                    portion.at_risk = False
                    portion.warned = False
                    store.events.append(
                        Event(
                            now,
                            f"{rider.name} delivered {portion.qty} items to {shelter.name}",
                        )
                    )


def _advance_one_step(store: Store, minutes: float) -> None:
    active_portions = [
        portion
        for portion in store.portions.values()
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

        # If portion is at_risk and rider is already waiting at the shelter, don't move
        if not (
            portion.at_risk
            and distance((rider.x, rider.y), (target.x, target.y)) == 0
        ):
            _move_rider_towards(rider, target.x, target.y, minutes)
        rider.last_ping = store.clock.now() + minutes
        rider.unresponsive = False

    # Also update last_ping for idle active (non-frozen) riders
    for rider in store.riders.values():
        if not rider.frozen and not _has_active_portion(store, rider.id):
            rider.last_ping = store.clock.now() + minutes
            rider.unresponsive = False

    store.clock.advance(minutes)
    tick(store)


def advance_clock(store: Store, minutes: float) -> float:
    if minutes <= 0:
        raise ValueError("minutes must be greater than zero")
    if minutes > MAX_ADVANCE_MINUTES:
        raise ValueError(f"minutes must be at most {MAX_ADVANCE_MINUTES}")

    remaining = minutes
    while remaining > 1e-9:
        step = min(STEP_MINUTES, remaining)
        _advance_one_step(store, step)
        remaining -= step

    return store.clock.now()


# --- Operational Actions ---


def cancel_portion(store: Store, portion_id: str) -> dict:
    if portion_id not in store.portions:
        return {"ok": False, "message": "REJECT: Portion not found"}

    portion = store.portions[portion_id]

    if portion.status == PortionStatus.CANCELLED:
        return {"ok": True, "message": "Portion already cancelled"}

    if portion.status == PortionStatus.DELIVERED:
        return {"ok": False, "message": "REJECT: Food already delivered"}

    if portion.status in {PortionStatus.EXPIRED, PortionStatus.WASTED}:
        return {"ok": False, "message": "REJECT: Food already expired or wasted"}

    if portion.status == PortionStatus.IN_TRANSIT:
        return {
            "ok": False,
            "message": "REJECT: Pickup ke baad direct cancellation allowed nahi",
        }

    if portion.status == PortionStatus.CLAIMED:
        portion.status = PortionStatus.CANCELLED
        portion.at_risk = False
        rider = store.riders[portion.rider_id]
        store.events.append(
            Event(
                store.clock.now(),
                f"{rider.name} cancelled claim {portion.id}; {portion.qty} items returned to pool",
            )
        )
        return {
            "ok": True,
            "message": "Claim cancelled; food returned to pool",
            "portion_id": portion.id,
            "quantity_returned": portion.qty,
        }

    return {"ok": False, "message": "REJECT: Portion cannot be cancelled"}


def freeze_rider(store: Store, rider_id: str, frozen: bool) -> dict:
    if rider_id not in store.riders:
        return {"ok": False, "message": "REJECT: Rider not found"}

    rider = store.riders[rider_id]
    rider.frozen = frozen
    if not frozen:
        rider.unresponsive = False
        rider.last_ping = store.clock.now()
        # Clear at_risk on any portion carried by this rider if destination is still valid
        for portion in store.portions.values():
            if (
                portion.rider_id == rider_id
                and portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
                and portion.at_risk
            ):
                _retry_at_risk_portions(store)

    status = "frozen" if frozen else "active"
    store.events.append(Event(store.clock.now(), f"{rider.name} is now {status}"))

    return {"ok": True, "rider_id": rider_id, "frozen": frozen}


def traffic_message(store: Store, portion_id: str) -> dict:
    if portion_id not in store.portions:
        return {"ok": False, "message": "REJECT: Portion not found"}

    portion = store.portions[portion_id]
    if portion.status not in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}:
        return {"ok": False, "message": "REJECT: Active delivery nahi hai"}

    now = store.clock.now()
    batch = store.batches[portion.batch_id]
    need = store.needs[portion.need_id]
    rider = store.riders[portion.rider_id]
    rider.last_ping = now
    rider.unresponsive = False

    # Fix #4: Handle limit exceeded differently for CLAIMED vs IN_TRANSIT
    if portion.traffic_msgs >= 3:
        if portion.status == PortionStatus.CLAIMED:
            portion.status = PortionStatus.CANCELLED
            portion.at_risk = False
            store.events.append(
                Event(now, f"{portion.id} auto-cancelled: message limit exceeded")
            )
            return {
                "ok": False,
                "status": portion.status.value,
                "message": "AUTO-CANCEL: Maximum 3 traffic messages allowed",
            }
        else:
            # Rider already has the food in transit: try rerouting to a closer shelter, otherwise mark WASTED
            outcome = _reroute_or_handle_affected_portion(
                store,
                portion,
                reason="traffic message limit exceeded",
                exclude_shelter_id=portion.shelter_id,
            )
            if outcome == "rerouted":
                return {
                    "ok": False,
                    "status": portion.status.value,
                    "rerouted_to": portion.shelter_id,
                    "message": "REROUTED: Message limit exceeded for current shelter; rerouted to closer shelter",
                }
            portion.status = PortionStatus.WASTED
            portion.at_risk = False
            store.events.append(
                Event(
                    now,
                    f"{portion.id} marked WASTED: in-transit message limit exceeded and no fallback shelter",
                )
            )
            return {
                "ok": False,
                "status": portion.status.value,
                "message": "WASTED: Maximum 3 traffic messages exceeded in transit and no fallback shelter",
            }

    if portion.status == PortionStatus.CLAIMED:
        donor = store.donors[batch.donor_id]
        eta = (
            now
            + travel_time((rider.x, rider.y), (donor.x, donor.y))
            + travel_time(
                (donor.x, donor.y),
                (
                    store.shelters[portion.shelter_id].x,
                    store.shelters[portion.shelter_id].y,
                ),
            )
            + BUFFER_MINUTES
        )
    else:
        shelter = store.shelters[portion.shelter_id]
        eta = (
            now
            + travel_time((rider.x, rider.y), (shelter.x, shelter.y))
            + BUFFER_MINUTES
        )

    # Fix #4 & #8: Check both safe_until and need_by, and handle IN_TRANSIT without creating phantom stock
    if eta > batch.safe_until or eta > need.need_by:
        if portion.status == PortionStatus.CLAIMED:
            portion.status = PortionStatus.CANCELLED
            portion.at_risk = False
            store.events.append(
                Event(now, f"{portion.id} auto-cancelled: ETA unsafe or exceeds need_by")
            )
            return {
                "ok": False,
                "status": portion.status.value,
                "message": "AUTO-CANCEL: ETA safe/need_by window ke bahar hai",
            }
        else:
            outcome = _reroute_or_handle_affected_portion(
                store,
                portion,
                reason="ETA unsafe for current shelter",
                exclude_shelter_id=portion.shelter_id,
            )
            if outcome == "rerouted":
                return {
                    "ok": False,
                    "status": portion.status.value,
                    "rerouted_to": portion.shelter_id,
                    "message": "REROUTED: ETA unsafe for original shelter; rerouted to reachable shelter",
                }
            portion.status = PortionStatus.WASTED
            portion.at_risk = False
            store.events.append(
                Event(
                    now,
                    f"{portion.id} marked WASTED: in-transit ETA unsafe and no reachable fallback shelter",
                )
            )
            return {
                "ok": False,
                "status": portion.status.value,
                "message": "WASTED: ETA safe window ke bahar hai aur koi fallback shelter nahi mila",
            }

    portion.traffic_msgs += 1
    portion.claim_expires_at += 5

    store.events.append(
        Event(now, f"Traffic message {portion.traffic_msgs}/3 for {portion.id}")
    )

    return {
        "ok": True,
        "message_count": portion.traffic_msgs,
        "eta": eta,
        "message": "Traffic message accepted; lease extended by 5 minutes",
    }


# --- Fix #9 & #10: Shelter Status, Reopening & Dynamic Compatibility ---


def update_shelter(
    store: Store,
    shelter_id: str,
    status: str | None = None,
    has_water: bool | None = None,
    has_fuel: bool | None = None,
) -> dict:
    if shelter_id not in store.shelters:
        return {"ok": False, "message": "REJECT: Shelter not found"}

    shelter = store.shelters[shelter_id]
    now = store.clock.now()

    if status is not None:
        try:
            shelter.status = ShelterStatus(status)
        except ValueError:
            return {"ok": False, "message": f"REJECT: Invalid status '{status}'"}

    if has_water is not None:
        shelter.has_water = has_water
    if has_fuel is not None:
        shelter.has_fuel = has_fuel

    store.events.append(
        Event(
            now,
            f"Shelter {shelter.name} updated: status={shelter.status.value}, water={shelter.has_water}, fuel={shelter.has_fuel}",
        )
    )

    rerouted: list[str] = []
    cancelled: list[str] = []
    at_risk: list[str] = []

    # Check active portions heading to this shelter that are now invalid due to status or utility loss
    affected = [
        portion
        for portion in store.portions.values()
        if portion.shelter_id == shelter_id
        and portion.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
    ]

    for portion in affected:
        batch = store.batches[portion.batch_id]
        if shelter.status != ShelterStatus.OPEN or not is_compatible(
            batch.item_type, shelter
        ):
            outcome = _reroute_or_handle_affected_portion(
                store,
                portion,
                reason=f"{shelter.name} unavailable or incompatible",
                exclude_shelter_id=shelter_id,
            )
            if outcome == "rerouted":
                rerouted.append(portion.id)
            elif outcome == "cancelled":
                cancelled.append(portion.id)
            elif outcome == "at_risk":
                at_risk.append(portion.id)

    # If shelter became OPEN or regained utilities, retry any at-risk portions
    _retry_at_risk_portions(store)

    return {
        "ok": True,
        "shelter_id": shelter_id,
        "status": shelter.status.value,
        "has_water": shelter.has_water,
        "has_fuel": shelter.has_fuel,
        "rerouted": rerouted,
        "cancelled": cancelled,
        "at_risk": at_risk,
    }


def make_shelter_unavailable(store: Store, shelter_id: str) -> dict:
    return update_shelter(
        store, shelter_id, status=ShelterStatus.TEMPORARILY_UNAVAILABLE.value
    )


# --- Fix #2: Need Fulfilled / Reduced Mid-Journey ---


def update_need(
    store: Store,
    need_id: str,
    qty: int | None = None,
    need_by: float | None = None,
) -> dict:
    if need_id not in store.needs:
        return {"ok": False, "message": "REJECT: Need not found"}

    need = store.needs[need_id]
    shelter = store.shelters[need.shelter_id]
    now = store.clock.now()

    if qty is not None:
        if qty < 0:
            return {"ok": False, "message": "REJECT: qty cannot be negative"}
        need.qty = qty

    if need_by is not None:
        need.need_by = need_by

    store.events.append(
        Event(
            now,
            f"Need {need.id} at {shelter.name} updated: qty={need.qty}, need_by={need.need_by}m",
        )
    )

    rerouted: list[str] = []
    cancelled: list[str] = []
    at_risk: list[str] = []

    # Calculate how much of the updated need is already delivered
    delivered_qty = sum(
        p.qty
        for p in store.portions.values()
        if p.need_id == need_id and p.status == PortionStatus.DELIVERED
    )
    remaining_for_active = max(0, need.qty - delivered_qty)

    # Prioritise keeping IN_TRANSIT portions before CLAIMED portions
    active_for_need = sorted(
        [
            p
            for p in store.portions.values()
            if p.need_id == need_id
            and p.status in {PortionStatus.CLAIMED, PortionStatus.IN_TRANSIT}
        ],
        key=lambda p: 0 if p.status == PortionStatus.IN_TRANSIT else 1,
    )

    allocated = 0
    for portion in active_for_need:
        rider = store.riders[portion.rider_id]
        batch = store.batches[portion.batch_id]
        donor = store.donors[batch.donor_id]

        if portion.status == PortionStatus.CLAIMED:
            eta = (
                now
                + travel_time((rider.x, rider.y), (donor.x, donor.y))
                + travel_time((donor.x, donor.y), (shelter.x, shelter.y))
                + BUFFER_MINUTES
            )
        else:
            eta = (
                now
                + travel_time((rider.x, rider.y), (shelter.x, shelter.y))
                + BUFFER_MINUTES
            )

        exceeds_need_qty = allocated + portion.qty > remaining_for_active
        exceeds_deadline = eta > need.need_by

        if not exceeds_need_qty and not exceeds_deadline:
            allocated += portion.qty
            continue

        reason = (
            f"need {need.id} already fulfilled"
            if exceeds_need_qty
            else f"need {need.id} deadline tightened"
        )
        outcome = _reroute_or_handle_affected_portion(
            store,
            portion,
            reason=reason,
            exclude_need_id=need_id,
        )
        if outcome == "rerouted":
            rerouted.append(portion.id)
        elif outcome == "cancelled":
            cancelled.append(portion.id)
        elif outcome == "at_risk":
            at_risk.append(portion.id)

    _retry_at_risk_portions(store)

    return {
        "ok": True,
        "need_id": need_id,
        "qty": need.qty,
        "need_by": need.need_by,
        "rerouted": rerouted,
        "cancelled": cancelled,
        "at_risk": at_risk,
    }