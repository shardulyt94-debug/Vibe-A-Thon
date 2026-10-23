from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_cards_endpoint_returns_claimable_cards():
    client.post("/seed")

    response = client.get("/riders/rider-1/cards")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert any(card["need_id"] == "need-a-meals" for card in body["cards"])


def test_claim_endpoint_creates_portion():
    client.post("/seed")

    response = client.post(
        "/claim",
        json={
            "rider_id": "rider-1",
            "need_id": "need-a-meals",
            "batch_id": "batch-meals",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["quantity"] == 40


def test_claim_endpoint_returns_clear_missing_id_error():
    client.post("/seed")

    response = client.post(
        "/claim",
        json={
            "rider_id": "unknown-rider",
            "need_id": "need-a-meals",
            "batch_id": "batch-meals",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "unknown-rider" in response.json()["message"]
