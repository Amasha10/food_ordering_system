from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import requests
import re

DATABASE_URL = "sqlite:///./orders.db"
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


def ensure_order_schema():
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(orders)"))
        existing_columns = {row[1]: row[2] for row in result.fetchall()}

        if "id" not in existing_columns:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER, Fid VARCHAR, name VARCHAR, items VARCHAR, status VARCHAR, order_date VARCHAR)"
            ))
        else:
            if "Fid" not in existing_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN Fid VARCHAR"))
            if "name" not in existing_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN name VARCHAR"))
            # Preserve existing values from legacy food_id column.
            if "food_id" in existing_columns:
                connection.execute(
                    text("UPDATE orders SET Fid = food_id WHERE (Fid IS NULL OR Fid = '') AND food_id IS NOT NULL")
                )
            if "items" not in existing_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN items VARCHAR"))
            if "status" not in existing_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN status VARCHAR"))
            if "order_date" not in existing_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN order_date VARCHAR"))
        connection.commit()


def fetch_food_name(fid: str) -> str:
    response = requests.get(
        f"http://localhost:8002/foods/{fid}",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail=f"Food not found for Fid '{fid}'")
    return response.json().get("name") or ""


def fetch_default_food() -> tuple[str, str]:
    response = requests.get(
        "http://localhost:8002/foods",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Food service unavailable")

    foods = response.json()
    if not foods:
        raise HTTPException(status_code=422, detail="No foods available. Create a food record first")

    latest_food = None
    latest_suffix = -1

    for food in foods:
        fid = str(food.get("Fid") or "")
        match = re.search(r"(\d+)$", fid)
        if not match:
            continue
        suffix = int(match.group(1))
        if suffix > latest_suffix:
            latest_suffix = suffix
            latest_food = food

    if latest_food is None:
        # Fallback for unexpected Fid formats.
        latest_food = foods[-1]

    default_fid = latest_food.get("Fid")
    if not default_fid:
        raise HTTPException(status_code=422, detail="Food record is missing Fid")

    return default_fid, latest_food.get("name") or ""


def fetch_default_user_id() -> int:
    response = requests.get(
        "http://localhost:8001/users",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="User service unavailable")

    users = response.json()
    if not users:
        raise HTTPException(status_code=422, detail="No users available. Create a user record first")

    user_ids = [user.get("user_id") for user in users if user.get("user_id") is not None]
    if not user_ids:
        raise HTTPException(status_code=422, detail="User records are missing user_id")

    return max(user_ids)


def order_response(order):
    return {
        "order_id": order.id,
        "user_id": order.user_id,
        "Fid": order.Fid,
        "name": order.name,
        "items": order.items,
        "status": order.status,
        "order_date": order.order_date,
    }


class OrderDB(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer)
    Fid = Column(String)
    name = Column(String)
    items = Column(String)
    status = Column(String)
    order_date = Column(String)


def get_next_order_id(db):
    max_id = db.query(func.max(OrderDB.id)).scalar() or 0
    total_rows = db.query(func.count(OrderDB.id)).scalar() or 0
    return max(max_id, total_rows) + 1


Base.metadata.create_all(bind=engine)
ensure_order_schema()


class OrderCreate(BaseModel):
    items: str = Field(..., title="Items")
    status: str = Field(..., title="Status")
    order_date: str = Field(..., title="Order Date")

    @field_validator("items")
    def validate_items(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("Items must contain only numerical values")
        return normalized

    @field_validator("order_date")
    def validate_order_date(cls, value: str) -> str:
        if not all(ch.isdigit() or ch in ".-" for ch in value):
            raise ValueError("Order date must contain only digits, dots, or dashes")
        return value

    class Config:
        from_attributes = True


class OrderUpdate(BaseModel):
    user_id: Optional[int] = None
    Fid: Optional[str] = None
    name: Optional[str] = None
    items: Optional[str] = None
    status: Optional[str] = None
    order_date: Optional[str] = None

    @field_validator("items")
    def validate_items(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("Items must contain only numerical values")
        return normalized

    @field_validator("order_date")
    def validate_order_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not all(ch.isdigit() or ch in ".-" for ch in value):
            raise ValueError("Order date must contain only digits, dots, or dashes")
        return value


class OrderPatch(BaseModel):
    user_id: Optional[int] = None
    Fid: Optional[str] = None
    name: Optional[str] = None
    items: Optional[str] = None
    status: Optional[str] = None
    order_date: Optional[str] = None

    @field_validator("items")
    def validate_items(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("Items must contain only numerical values")
        return normalized

    @field_validator("order_date")
    def validate_order_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not all(ch.isdigit() or ch in ".-" for ch in value):
            raise ValueError("Order date must contain only digits, dots, or dashes")
        return value

@app.post("/orders")
def create_order(order: OrderCreate):
    db = SessionLocal()
    new_order_id = get_next_order_id(db)

    resolved_user_id = fetch_default_user_id()
    resolved_fid, resolved_name = fetch_default_food()

    db_order = OrderDB(
        id=new_order_id,
        user_id=resolved_user_id,
        Fid=resolved_fid,
        name=resolved_name,
        items=order.items,
        status=order.status,
        order_date=order.order_date,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return order_response(db_order)


@app.get("/orders")
def get_orders():
    db = SessionLocal()
    orders = db.query(OrderDB).all()
    return [order_response(order) for order in orders]


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    db = SessionLocal()
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order_response(order)


@app.put("/orders/{order_id}")
def update_order(order_id: int, updated_order: OrderUpdate):
    db = SessionLocal()
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        # Create a new order with a system-generated ID when the requested order does not exist.
        new_order_id = get_next_order_id(db)
        if updated_order.user_id is None or updated_order.Fid is None:
            raise HTTPException(status_code=422, detail="user_id and Fid are required to create a new order")
        resolved_name = updated_order.name or fetch_food_name(updated_order.Fid)
        order = OrderDB(
            id=new_order_id,
            user_id=updated_order.user_id,
            Fid=updated_order.Fid,
            name=resolved_name,
            items=updated_order.items or "",
            status=updated_order.status or "Pending",
            order_date=updated_order.order_date or "",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order_response(order)

    if updated_order.user_id is not None:
        order.user_id = updated_order.user_id

    if updated_order.Fid is not None:
        order.Fid = updated_order.Fid
        order.name = updated_order.name or fetch_food_name(updated_order.Fid)
    elif updated_order.name is not None:
        order.name = updated_order.name

    if updated_order.items is not None:
        order.items = updated_order.items
    if updated_order.status is not None:
        order.status = updated_order.status
    if updated_order.order_date is not None:
        order.order_date = updated_order.order_date

    db.commit()
    db.refresh(order)
    return order_response(order)


@app.patch("/orders/{order_id}")
def partial_update_order(order_id: int, updated_order: OrderPatch):
    db = SessionLocal()
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    before_update = order_response(order)

    if updated_order.user_id is not None:
        order.user_id = updated_order.user_id
    if updated_order.Fid is not None:
        order.Fid = updated_order.Fid
        order.name = updated_order.name or fetch_food_name(updated_order.Fid)
    elif updated_order.name is not None:
        order.name = updated_order.name
    if updated_order.items is not None:
        order.items = updated_order.items
    if updated_order.status is not None:
        order.status = updated_order.status
    if updated_order.order_date is not None:
        order.order_date = updated_order.order_date

    db.commit()
    db.refresh(order)
    return {
        "message": "Order partially updated",
        "before_update": before_update,
        "after_update": order_response(order),
    }


@app.delete("/orders/{order_id}")
def delete_order(order_id: int):
    db = SessionLocal()
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return {"message": "Order deleted", "order": order_response(order)}
