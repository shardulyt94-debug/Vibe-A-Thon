from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel

from .engine import (
    advance_clock,
    cancel_portion,
    claim,
    list_cards_for_rider,
)
from .seed import seed_demo
from .store import Store

app = FastAPI(title="Last-Mile Emergency Dispatch")
store = seed_demo(Store())


class ClaimRequest(BaseModel):
    rider_id: str
    need_id: str
    batch_id: str


class AdvanceRequest(BaseModel):
    minutes: float


@app.get("/state")
def get_state() -> dict:
    return {
        "clock_minutes": store.clock.now(),
        "donors": [asdict(value) for value in store.donors.values()],
        "batches": [asdict(value) for value in store.batches.values()],
        "shelters": [asdict(value) for value in store.shelters.values()],
        "needs": [asdict(value) for value in store.needs.values()],
        "riders": [asdict(value) for value in store.riders.values()],
        "portions": [asdict(value) for value in store.portions.values()],
        "events": [asdict(value) for value in store.events],
    }


@app.post("/seed")
def reset_seed() -> dict:
    seed_demo(store)
    return {"ok": True, "message": "Demo reset", "clock_minutes": store.clock.now()}


@app.get("/riders/{rider_id}/cards")
def get_rider_cards(rider_id: str) -> dict:
    if rider_id not in store.riders:
        return {"ok": False, "message": "Rider not found", "cards": []}

    return {
        "ok": True,
        "rider_id": rider_id,
        "cards": list_cards_for_rider(store, rider_id),
    }


@app.post("/claim")
def create_claim(request: ClaimRequest) -> dict:
    missing = []
    if request.rider_id not in store.riders:
        missing.append(f"rider '{request.rider_id}'")
    if request.need_id not in store.needs:
        missing.append(f"need '{request.need_id}'")
    if request.batch_id not in store.batches:
        missing.append(f"batch '{request.batch_id}'")

    if missing:
        return {"ok": False, "message": "Not found: " + ", ".join(missing)}

    return claim(
        store,
        rider_id=request.rider_id,
        need_id=request.need_id,
        batch_id=request.batch_id,
    )


@app.post("/sim/advance")
def advance_simulation(request: AdvanceRequest) -> dict:
    try:
        now = advance_clock(store, request.minutes)
    except ValueError as error:
        return {"ok": False, "message": str(error)}
    return {"ok": True, "clock_minutes": now}

@app.post("/portions/{portion_id}/cancel")
def cancel_claim(portion_id: str) -> dict:
    return cancel_portion(store, portion_id)
