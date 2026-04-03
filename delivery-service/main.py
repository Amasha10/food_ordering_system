from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import requests

DATABASE_URL = "sqlite:///./deliveries.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

INTERNAL_SECRET = "internal-service-secret-key"

app = FastAPI()

PUBLIC_PATHS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


def is_docs_request(request: Request) -> bool:
    referer = request.headers.get("referer", "")
    return "/docs" in referer or "/redoc" in referer


@app.middleware("http")
async def require_internal_secret(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if is_docs_request(request):
        return await call_next(request)
    if request.headers.get("X-Internal-Secret") != INTERNAL_SECRET:
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


def ensure_delivery_schema():
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(deliveries)"))
        existing_columns = {row[1]: row[2] for row in result.fetchall()}

        if "id" not in existing_columns:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, order_id INTEGER, delivery_person VARCHAR, phone VARCHAR, status VARCHAR, estimated_time VARCHAR, delivery_address VARCHAR)"
            ))
        else:
            if "order_id" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN order_id INTEGER"))
            if "delivery_person" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN delivery_person VARCHAR"))
            if "phone" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN phone VARCHAR"))
            if "status" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN status VARCHAR"))
            if "estimated_time" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN estimated_time VARCHAR"))
            if "delivery_address" not in existing_columns:
                connection.execute(text("ALTER TABLE deliveries ADD COLUMN delivery_address VARCHAR"))
        connection.commit()


def delivery_response(delivery):
    return {
        "delivery_id": delivery.id,
        "order_id": delivery.order_id,
        "delivery_person": delivery.delivery_person,
        "phone": delivery.phone,
        "status": delivery.status,
        "estimated_time": delivery.estimated_time,
        "delivery_address": delivery.delivery_address,
    }


def get_next_delivery_id(db):
    last_delivery = db.query(DeliveryDB).order_by(DeliveryDB.id.desc()).first()
    return last_delivery.id + 1 if last_delivery else 1


def fetch_default_order_id() -> int:
    response = requests.get(
        "http://localhost:8003/orders",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Order service unavailable")

    orders = response.json()
    if not orders:
        raise HTTPException(status_code=422, detail="No orders available. Create an order record first")

    order_ids = [order.get("order_id") for order in orders if order.get("order_id") is not None]
    if not order_ids:
        raise HTTPException(status_code=422, detail="Order records are missing order_id")

    return max(order_ids)


def fetch_user_contact_by_order_id(order_id: int) -> tuple[str, str]:
    order_response = requests.get(
        f"http://localhost:8003/orders/{order_id}",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if order_response.status_code != 200:
        raise HTTPException(status_code=404, detail=f"Order not found for order_id '{order_id}'")

    order_payload = order_response.json()
    user_id = order_payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=422, detail="Order record is missing user_id")

    user_response = requests.get(
        f"http://localhost:8001/users/{user_id}",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if user_response.status_code != 200:
        raise HTTPException(status_code=404, detail=f"User not found for user_id '{user_id}'")

    user_payload = user_response.json()
    phone = user_payload.get("phone_number")
    address = user_payload.get("address")
    if not phone or not address:
        raise HTTPException(status_code=422, detail="User contact defaults are incomplete")

    return phone, address


FORBIDDEN_TIME_CHARS = {"@", "*", "/", "#"}


def validate_estimated_time_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if any(ch in FORBIDDEN_TIME_CHARS for ch in value):
        raise ValueError("estimated time should include letters and numerical value")
    return value


class DeliveryDB(Base):
    __tablename__ = "deliveries"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer)
    delivery_person = Column(String)
    phone = Column(String)
    status = Column(String)
    estimated_time = Column(String)
    delivery_address = Column(String)


Base.metadata.create_all(bind=engine)
ensure_delivery_schema()


class DeliveryCreate(BaseModel):
    delivery_person: str = Field(..., title="Delivery Person")
    status: str = Field(..., title="Status")
    estimated_time: str = Field(..., title="Estimated Time")

    @field_validator("delivery_person")
    def validate_delivery_person(cls, value: str) -> str:
        if not all(ch.isalpha() or ch.isspace() for ch in value):
            raise ValueError("Delivery person name must contain only letters and spaces")
        return value

    @field_validator("estimated_time")
    def validate_estimated_time(cls, value: str) -> str:
        return validate_estimated_time_value(value)

    class Config:
        from_attributes = True


class Delivery(BaseModel):
    delivery_id: int = Field(..., title="Delivery ID")
    order_id: int = Field(..., title="Order ID")
    delivery_person: str = Field(..., title="Delivery Person")
    phone: str = Field(..., title="Phone")
    status: str = Field(..., title="Status")
    estimated_time: str = Field(..., title="Estimated Time")
    delivery_address: str = Field(..., title="Delivery Address")

    @field_validator("phone")
    def validate_phone(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must contain exactly 10 numerical digits")
        return value

    @field_validator("delivery_person")
    def validate_delivery_person(cls, value: str) -> str:
        if not all(ch.isalpha() or ch.isspace() for ch in value):
            raise ValueError("Delivery person name must contain only letters and spaces")
        return value

    @field_validator("estimated_time")
    def validate_estimated_time(cls, value: str) -> str:
        return validate_estimated_time_value(value)

    class Config:
        from_attributes = True


class DeliveryPatch(BaseModel):
    order_id: Optional[int] = None
    delivery_person: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    estimated_time: Optional[str] = None
    delivery_address: Optional[str] = None

    @field_validator("phone")
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must contain exactly 10 numerical digits")
        return value

    @field_validator("delivery_person")
    def validate_delivery_person(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not all(ch.isalpha() or ch.isspace() for ch in value):
            raise ValueError("Delivery person name must contain only letters and spaces")
        return value

    @field_validator("estimated_time")
    def validate_estimated_time(cls, value: Optional[str]) -> Optional[str]:
        return validate_estimated_time_value(value)


@app.post("/deliveries")
def create_delivery(delivery: DeliveryCreate):
    db = SessionLocal()
    new_delivery_id = get_next_delivery_id(db)
    resolved_order_id = fetch_default_order_id()
    default_phone, default_address = fetch_user_contact_by_order_id(resolved_order_id)
    resolved_phone = default_phone
    resolved_address = default_address

    db_delivery = DeliveryDB(
        id=new_delivery_id,
        order_id=resolved_order_id,
        delivery_person=delivery.delivery_person,
        phone=resolved_phone,
        status=delivery.status,
        estimated_time=delivery.estimated_time,
        delivery_address=resolved_address,
    )
    db.add(db_delivery)
    db.commit()
    db.refresh(db_delivery)
    return delivery_response(db_delivery)


@app.get("/deliveries")
def get_all_deliveries():
    db = SessionLocal()
    deliveries = db.query(DeliveryDB).all()
    return [delivery_response(delivery) for delivery in deliveries]


@app.get("/deliveries/{delivery_id}")
def get_delivery(delivery_id: int):
    db = SessionLocal()
    delivery = db.query(DeliveryDB).filter(DeliveryDB.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return delivery_response(delivery)


@app.put("/deliveries/{delivery_id}")
def update_delivery(delivery_id: int, updated_delivery: Delivery):
    db = SessionLocal()
    delivery = db.query(DeliveryDB).filter(DeliveryDB.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    delivery.order_id = updated_delivery.order_id
    delivery.delivery_person = updated_delivery.delivery_person
    delivery.phone = updated_delivery.phone
    delivery.status = updated_delivery.status
    delivery.estimated_time = updated_delivery.estimated_time
    delivery.delivery_address = updated_delivery.delivery_address
    db.commit()
    db.refresh(delivery)
    return delivery_response(delivery)


@app.patch("/deliveries/{delivery_id}")
def partial_update_delivery(delivery_id: int, updated_delivery: DeliveryPatch):
    db = SessionLocal()
    delivery = db.query(DeliveryDB).filter(DeliveryDB.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    before_update = delivery_response(delivery)

    if updated_delivery.order_id is not None:
        delivery.order_id = updated_delivery.order_id
    if updated_delivery.delivery_person is not None:
        delivery.delivery_person = updated_delivery.delivery_person
    if updated_delivery.phone is not None:
        delivery.phone = updated_delivery.phone
    if updated_delivery.status is not None:
        delivery.status = updated_delivery.status
    if updated_delivery.estimated_time is not None:
        delivery.estimated_time = updated_delivery.estimated_time
    if updated_delivery.delivery_address is not None:
        delivery.delivery_address = updated_delivery.delivery_address

    db.commit()
    db.refresh(delivery)
    return {
        "message": "Delivery partially updated",
        "before_update": before_update,
        "after_update": delivery_response(delivery),
    }


@app.delete("/deliveries/{delivery_id}")
def delete_delivery(delivery_id: int):
    db = SessionLocal()
    delivery = db.query(DeliveryDB).filter(DeliveryDB.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    db.delete(delivery)
    db.commit()
    return {"message": "Delivery deleted", "delivery": delivery_response(delivery)}
