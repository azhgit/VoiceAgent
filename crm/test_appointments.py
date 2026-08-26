from conftest import future_slot


def _book(client, technician_id, slot, name="Carla", phone="555-0101", urgency="non_urgent"):
    return client.post(
        "/appointments",
        json={
            "technician_id": technician_id,
            "time_slot": slot,
            "customer_name": name,
            "customer_phone": phone,
            "urgency": urgency,
        },
    )


def test_create_appointment_success(client, technicians):
    resp = _book(client, technicians["mike"], future_slot())
    assert resp.status_code == 200
    assert resp.json()["status"] == "booked"


def test_unknown_technician_rejected(client, technicians):
    resp = _book(client, 999, future_slot())
    assert resp.status_code == 404


def test_invalid_urgency_rejected(client, technicians):
    resp = _book(client, technicians["mike"], future_slot(), urgency="whenever")
    assert resp.status_code == 422


def test_same_technician_same_slot_conflict(client, technicians):
    slot = future_slot(day_offset=1, hour=9)
    first = _book(client, technicians["mike"], slot)
    assert first.status_code == 200

    second = _book(client, technicians["mike"], slot, name="Bob")
    assert second.status_code == 409


def test_different_technician_same_slot_allowed(client, technicians):
    slot = future_slot(day_offset=1, hour=9)
    first = _book(client, technicians["mike"], slot)
    assert first.status_code == 200

    second = _book(client, technicians["dana"], slot, name="Bob")
    assert second.status_code == 200


def test_cancelled_appointment_frees_slot(client, technicians):
    slot = future_slot(day_offset=1, hour=9)
    first = _book(client, technicians["mike"], slot)
    appointment_id = first.json()["id"]

    cancel = client.patch(f"/appointments/{appointment_id}", params={"status": "cancelled"})
    assert cancel.status_code == 200

    rebook = _book(client, technicians["mike"], slot, name="Dana")
    assert rebook.status_code == 200


def test_booking_rate_limit_exceeded(client, technicians):
    phone = "555-9999"
    for i in range(3):
        slot = future_slot(day_offset=1, hour=9 + i)
        resp = _book(client, technicians["mike"], slot, phone=phone)
        assert resp.status_code == 200

    resp = _book(client, technicians["mike"], future_slot(day_offset=2, hour=9), phone=phone)
    assert resp.status_code == 429
