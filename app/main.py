from dataclasses import asdict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import (
    add_batch,
    add_donor,
    add_need,
    add_rider,
    add_shelter,
    advance_clock,
    cancel_portion,
    claim,
    freeze_rider,
    list_cards_for_rider,
    make_shelter_unavailable,
    traffic_message,
    update_need,
    update_shelter,
)
from .seed import seed_demo
from .store import Store

app = FastAPI(title="Last-Mile Emergency Dispatch")
store = seed_demo(Store())

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Request Schemas ---


class DonorCreateRequest(BaseModel):
    id: str | None = None
    name: str
    x: float
    y: float


class BatchCreateRequest(BaseModel):
    id: str | None = None
    donor_id: str
    item_type: str
    total_qty: int
    safe_until: float
    created_at: float | None = None


class ShelterCreateRequest(BaseModel):
    id: str | None = None
    name: str
    x: float
    y: float
    has_water: bool = True
    has_fuel: bool = True
    status: str = "OPEN"


class ShelterUpdateRequest(BaseModel):
    status: str | None = None
    has_water: bool | None = None
    has_fuel: bool | None = None


class ShelterStatusSimRequest(BaseModel):
    shelter_id: str
    status: str | None = None
    has_water: bool | None = None
    has_fuel: bool | None = None


class NeedCreateRequest(BaseModel):
    id: str | None = None
    shelter_id: str
    item_type: str
    qty: int
    need_by: float


class NeedUpdateRequest(BaseModel):
    qty: int | None = None
    need_by: float | None = None


class NeedSimUpdateRequest(BaseModel):
    need_id: str
    qty: int | None = None
    need_by: float | None = None


class RiderCreateRequest(BaseModel):
    id: str | None = None
    name: str
    x: float
    y: float
    capacity: int = 40


class ClaimRequest(BaseModel):
    rider_id: str
    need_id: str
    batch_id: str


class ShelterRequest(BaseModel):
    shelter_id: str


class AdvanceRequest(BaseModel):
    minutes: float


class FreezeRequest(BaseModel):
    rider_id: str
    frozen: bool


# --- Endpoints ---


@app.get("/")
def home():
    return {"message": "Last-Mile Dispatch running", "open": "/static/index.html"}


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
    return {"ok": True, "message": "Demo reset"}


# Fix #1: Entity creation endpoints
@app.post("/donors")
def create_donor_endpoint(request: DonorCreateRequest) -> dict:
    res = add_donor(store, request.id, request.name, request.x, request.y)
    if res["ok"]:
        res["donor"] = asdict(res["donor"])
    return res


@app.post("/batches")
def create_batch_endpoint(request: BatchCreateRequest) -> dict:
    res = add_batch(
        store,
        request.id,
        request.donor_id,
        request.item_type,
        request.total_qty,
        request.safe_until,
        request.created_at,
    )
    if res["ok"]:
        res["batch"] = asdict(res["batch"])
    return res


@app.post("/shelters")
def create_shelter_endpoint(request: ShelterCreateRequest) -> dict:
    res = add_shelter(
        store,
        request.id,
        request.name,
        request.x,
        request.y,
        request.has_water,
        request.has_fuel,
        request.status,
    )
    if res["ok"]:
        res["shelter"] = asdict(res["shelter"])
    return res


@app.post("/needs")
def create_need_endpoint(request: NeedCreateRequest) -> dict:
    res = add_need(
        store,
        request.id,
        request.shelter_id,
        request.item_type,
        request.qty,
        request.need_by,
    )
    if res["ok"]:
        res["need"] = asdict(res["need"])
    return res


@app.post("/riders")
def create_rider_endpoint(request: RiderCreateRequest) -> dict:
    res = add_rider(
        store, request.id, request.name, request.x, request.y, request.capacity
    )
    if res["ok"]:
        res["rider"] = asdict(res["rider"])
    return res


# Fix #2: Need update / fulfill endpoints (RESTful PATCH + /sim alias)
@app.patch("/needs/{need_id}")
def patch_need_endpoint(need_id: str, request: NeedUpdateRequest) -> dict:
    return update_need(store, need_id, qty=request.qty, need_by=request.need_by)


@app.post("/sim/update_need")
def sim_update_need_endpoint(request: NeedSimUpdateRequest) -> dict:
    return update_need(
        store, request.need_id, qty=request.qty, need_by=request.need_by
    )


# Fix #9 & #10: Shelter status (OPEN/TEMPORARILY_UNAVAILABLE) & water/fuel update endpoints
@app.patch("/shelters/{shelter_id}")
def patch_shelter_endpoint(
    shelter_id: str, request: ShelterUpdateRequest
) -> dict:
    return update_shelter(
        store,
        shelter_id,
        status=request.status,
        has_water=request.has_water,
        has_fuel=request.has_fuel,
    )


@app.post("/sim/shelter_status")
def sim_shelter_status_endpoint(request: ShelterStatusSimRequest) -> dict:
    return update_shelter(
        store,
        request.shelter_id,
        status=request.status,
        has_water=request.has_water,
        has_fuel=request.has_fuel,
    )


@app.post("/sim/shelter_unavailable")
def shelter_unavailable(request: ShelterRequest) -> dict:
    return make_shelter_unavailable(store, request.shelter_id)


@app.post("/sim/shelter_open")
def shelter_open(request: ShelterRequest) -> dict:
    return update_shelter(store, request.shelter_id, status="OPEN")


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

    return claim(store, request.rider_id, request.need_id, request.batch_id)


@app.post("/sim/advance")
def advance_simulation(request: AdvanceRequest) -> dict:
    try:
        now = advance_clock(store, request.minutes)
        return {"ok": True, "clock_minutes": now}
    except ValueError as error:
        return {"ok": False, "message": str(error)}


@app.post("/sim/freeze_rider")
def freeze_rider_endpoint(request: FreezeRequest) -> dict:
    return freeze_rider(store, request.rider_id, request.frozen)


@app.post("/portions/{portion_id}/cancel")
def cancel_claim(portion_id: str) -> dict:
    return cancel_portion(store, portion_id)


@app.post("/portions/{portion_id}/message")
def traffic_message_endpoint(portion_id: str) -> dict:
    return traffic_message(store, portion_id)