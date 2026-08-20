from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Appointment, Technician

router = APIRouter(prefix="/appointments", tags=["appointments"])

STATUSES = {"booked", "completed", "cancelled"}
URGENCIES = {"urgent", "non_urgent"}


class AppointmentCreate(BaseModel):
    technician_id: int
    time_slot: datetime
    customer_name: str
    customer_phone: str
    urgency: str = "non_urgent"


def _serialize(a: Appointment) -> dict:
    return {
        "id": a.id,
        "technician_id": a.technician_id,
        "time_slot": a.time_slot.isoformat(),
        "customer_name": a.customer_name,
        "customer_phone": a.customer_phone,
        "urgency": a.urgency,
        "status": a.status,
    }


@router.get("")
def list_appointments(
    technician_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Appointment)
    if technician_id is not None:
        q = q.filter(Appointment.technician_id == technician_id)
    if status is not None:
        q = q.filter(Appointment.status == status)
    return [_serialize(a) for a in q.order_by(Appointment.time_slot).all()]


@router.get("/{appointment_id}")
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(a)


@router.post("")
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    if payload.urgency not in URGENCIES:
        raise HTTPException(status_code=422, detail=f"Invalid urgency: {payload.urgency}")
    if db.get(Technician, payload.technician_id) is None:
        raise HTTPException(status_code=404, detail="Technician not found")
    # Day 1: no conflict/overlap check against existing bookings or working
    # hours here - that's the "available slots" business logic, not Day 0 CRUD.
    appointment = Appointment(**payload.model_dump())
    db.add(appointment)
    db.commit()
    return _serialize(appointment)


@router.patch("/{appointment_id}")
def update_appointment_status(appointment_id: int, status: str, db: Session = Depends(get_db)):
    if status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
    a = db.get(Appointment, appointment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Not found")
    a.status = status
    db.commit()
    return _serialize(a)
