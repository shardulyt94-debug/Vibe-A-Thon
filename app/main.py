from dataclasses import asdict

from fastapi import FastAPI

from .seed import seed_demo
from .store import Store

app = FastAPI(title="Last-Mile Emergency Dispatch")
store = seed_demo(Store())


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
