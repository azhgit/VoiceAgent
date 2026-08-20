from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from db import Base


class Technician(Base):
    __tablename__ = "technicians"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    specialty = Column(String, nullable=False)  # plumbing/hvac/general
    on_call = Column(Boolean, nullable=False, default=False)

    appointments = relationship(
        "Appointment", backref="technician", cascade="all, delete-orphan"
    )


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=False)
    time_slot = Column(DateTime, nullable=False)  # appointment start, fixed 1hr block
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    urgency = Column(String, nullable=False, default="non_urgent")  # urgent/non_urgent
    status = Column(String, nullable=False, default="booked")  # booked/completed/cancelled
    created_at = Column(DateTime, server_default=func.now())
