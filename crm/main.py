from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from appointments import router as appointments_router
from db import Base, engine
from technicians import router as technicians_router

app = FastAPI(title="Voice Agent Mock CRM")
app.include_router(technicians_router)
app.include_router(appointments_router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)  # schema only - seed data is separate, see seed.py


@app.get("/health")
def health():
    return {"ok": True}
