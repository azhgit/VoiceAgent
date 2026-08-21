from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from appointments import router as appointments_router
from availability import router as availability_router
from db import Base, engine
from technicians import router as technicians_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)  # schema only - seed data is separate, see seed.py
    yield


app = FastAPI(title="Voice Agent Mock CRM", lifespan=lifespan)
app.include_router(technicians_router)
app.include_router(appointments_router)
app.include_router(availability_router)


@app.get("/health")
def health():
    return {"ok": True}
