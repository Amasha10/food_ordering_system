from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from typing import Optional
import requests
import jwt
from datetime import datetime, timedelta, timezone

tags_metadata = [
    {"name": "User Service", "description": "Operations for users."},
    {"name": "Food Service", "description": "Operations for foods/menu."},
    {"name": "Order Service", "description": "Operations for orders."},
    {"name": "Delivery Service", "description": "Operations for deliveries."},
    {"name": "Gateway Overview", "description": "Combined data across services."},
]

app = FastAPI(openapi_tags=tags_metadata)

JWT_SECRET = "change-this-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60
INTERNAL_SECRET = "internal-service-secret-key"

bearer_scheme = HTTPBearer()
class TokenRequest(BaseModel):
    email: str
    password: str


class UserCreateRequest(BaseModel):
    user_name: str
    email: str
    phone_number: str
    address: str
    password: str = Field(..., min_length=8)


class UserUpdateRequest(BaseModel):
    user_id: int
    user_name: str
    email: str
    phone_number: str
    address: str


class UserPatchRequest(BaseModel):
    user_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None


class FoodCreateRequest(BaseModel):
    name: str
    description: str
    category: str
    price: float
    is_available: bool


class FoodPatchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    is_available: Optional[bool] = None


class OrderCreateRequest(BaseModel):
    user_id: int
    Fid: str
    name: Optional[str] = None
    items: str
    status: str
    order_date: str


class OrderUpdateRequest(BaseModel):
    user_id: Optional[int] = None
    Fid: Optional[str] = None
    name: Optional[str] = None
    items: Optional[str] = None
    status: Optional[str] = None
    order_date: Optional[str] = None


class OrderPatchRequest(BaseModel):
    user_id: Optional[int] = None
    Fid: Optional[str] = None
    name: Optional[str] = None
    items: Optional[str] = None
    status: Optional[str] = None
    order_date: Optional[str] = None


class DeliveryCreateRequest(BaseModel):
    order_id: int
    delivery_person: str
    phone: str
    status: str
    estimated_time: str
    delivery_address: str


class DeliveryUpdateRequest(BaseModel):
    delivery_id: int
    order_id: int
    delivery_person: str
    phone: str
    status: str
    estimated_time: str
    delivery_address: str


class DeliveryPatchRequest(BaseModel):
    order_id: Optional[int] = None
    delivery_person: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    estimated_time: Optional[str] = None
    delivery_address: Optional[str] = None


# ── Auth helpers ───────────────────────────────────────────────────────────────

def create_access_token(payload: dict) -> str:
    token_payload = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    token_payload.update({"exp": expire})
    return jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def proxy_request(method: str, url: str, data: dict | None = None):
    headers = {"X-Internal-Secret": INTERNAL_SECRET}
    response = requests.request(method=method, url=url, json=data, headers=headers, timeout=10)
    return response.json()


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.post("/auth/user-token", tags=["User Service"])
def get_user_token(data: TokenRequest):
    response = requests.post(
        "http://localhost:8001/users/authenticate",
        json={"email": data.email, "password": data.password},
        headers={"X-Internal-Secret": INTERNAL_SECRET},
        timeout=10,
    )
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="User service unavailable")

    user = response.json()
    access_token = create_access_token(
        {"sub": str(user.get("user_id")), "email": user.get("email")}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users", tags=["User Service"])
def get_users(_: dict = Depends(verify_token)):
    return proxy_request("GET", "http://localhost:8001/users")


@app.post("/users", tags=["User Service"])
def create_user(data: UserCreateRequest, _: dict = Depends(verify_token)):
    return proxy_request("POST", "http://localhost:8001/users", data.model_dump())


@app.get("/users/{user_id}", tags=["User Service"])
def get_user(user_id: int, _: dict = Depends(verify_token)):
    return proxy_request("GET", f"http://localhost:8001/users/{user_id}")


@app.put("/users/{user_id}", tags=["User Service"])
def update_user(user_id: int, data: UserUpdateRequest, _: dict = Depends(verify_token)):
    return proxy_request("PUT", f"http://localhost:8001/users/{user_id}", data.model_dump())


@app.patch("/users/{user_id}", tags=["User Service"])
def partial_update_user(user_id: int, data: UserPatchRequest, _: dict = Depends(verify_token)):
    return proxy_request("PATCH", f"http://localhost:8001/users/{user_id}", data.model_dump())


@app.delete("/users/{user_id}", tags=["User Service"])
def delete_user(user_id: int, _: dict = Depends(verify_token)):
    return proxy_request("DELETE", f"http://localhost:8001/users/{user_id}")


@app.get("/foods", tags=["Food Service"])
def get_foods(_: dict = Depends(verify_token)):
    return proxy_request("GET", "http://localhost:8002/foods")


@app.post("/foods", tags=["Food Service"])
def create_food(data: FoodCreateRequest, _: dict = Depends(verify_token)):
    return proxy_request("POST", "http://localhost:8002/foods", data.model_dump())


@app.get("/foods/{food_id}", tags=["Food Service"])
def get_food(food_id: str, _: dict = Depends(verify_token)):
    return proxy_request("GET", f"http://localhost:8002/foods/{food_id}")


@app.put("/foods/{food_id}", tags=["Food Service"])
def update_food(food_id: str, data: FoodCreateRequest, _: dict = Depends(verify_token)):
    return proxy_request("PUT", f"http://localhost:8002/foods/{food_id}", data.model_dump())


@app.patch("/foods/{food_id}", tags=["Food Service"])
def partial_update_food(food_id: str, data: FoodPatchRequest, _: dict = Depends(verify_token)):
    return proxy_request("PATCH", f"http://localhost:8002/foods/{food_id}", data.model_dump())


@app.delete("/foods/{food_id}", tags=["Food Service"])
def delete_food(food_id: str, _: dict = Depends(verify_token)):
    return proxy_request("DELETE", f"http://localhost:8002/foods/{food_id}")

@app.get("/orders", tags=["Order Service"])
def get_orders(_: dict = Depends(verify_token)):
    return proxy_request("GET", "http://localhost:8003/orders")


@app.post("/orders", tags=["Order Service"])
def create_order(data: OrderCreateRequest, _: dict = Depends(verify_token)):
    return proxy_request("POST", "http://localhost:8003/orders", data.model_dump())


@app.get("/orders/{order_id}", tags=["Order Service"])
def get_order(order_id: int, _: dict = Depends(verify_token)):
    return proxy_request("GET", f"http://localhost:8003/orders/{order_id}")


@app.put("/orders/{order_id}", tags=["Order Service"])
def update_order(order_id: int, data: OrderUpdateRequest, _: dict = Depends(verify_token)):
    return proxy_request("PUT", f"http://localhost:8003/orders/{order_id}", data.model_dump())


@app.patch("/orders/{order_id}", tags=["Order Service"])
def partial_update_order(order_id: int, data: OrderPatchRequest, _: dict = Depends(verify_token)):
    return proxy_request("PATCH", f"http://localhost:8003/orders/{order_id}", data.model_dump())


@app.delete("/orders/{order_id}", tags=["Order Service"])
def delete_order(order_id: int, _: dict = Depends(verify_token)):
    return proxy_request("DELETE", f"http://localhost:8003/orders/{order_id}")

@app.get("/deliveries", tags=["Delivery Service"])
def get_all_deliveries(_: dict = Depends(verify_token)):
    return proxy_request("GET", "http://localhost:8004/deliveries")


@app.get("/deliveries/{delivery_id}", tags=["Delivery Service"])
def get_delivery(delivery_id: int, _: dict = Depends(verify_token)):
    return proxy_request("GET", f"http://localhost:8004/deliveries/{delivery_id}")


@app.post("/deliveries", tags=["Delivery Service"])
def create_delivery(data: DeliveryCreateRequest, _: dict = Depends(verify_token)):
    return proxy_request("POST", "http://localhost:8004/deliveries", data.model_dump())


@app.put("/deliveries/{delivery_id}", tags=["Delivery Service"])
def update_delivery(delivery_id: int, data: DeliveryUpdateRequest, _: dict = Depends(verify_token)):
    return proxy_request("PUT", f"http://localhost:8004/deliveries/{delivery_id}", data.model_dump())


@app.patch("/deliveries/{delivery_id}", tags=["Delivery Service"])
def partial_update_delivery(delivery_id: int, data: DeliveryPatchRequest, _: dict = Depends(verify_token)):
    return proxy_request("PATCH", f"http://localhost:8004/deliveries/{delivery_id}", data.model_dump())


@app.delete("/deliveries/{delivery_id}", tags=["Delivery Service"])
def delete_delivery(delivery_id: int, _: dict = Depends(verify_token)):
    return proxy_request("DELETE", f"http://localhost:8004/deliveries/{delivery_id}")

@app.get("/all/{delivery_id}", tags=["Gateway Overview"])
def get_all_data(delivery_id: int, _: dict = Depends(verify_token)):
    return {
        "users": proxy_request("GET", "http://localhost:8001/users"),
        "foods": proxy_request("GET", "http://localhost:8002/foods"),
        "orders": proxy_request("GET", "http://localhost:8003/orders"),
        "delivery": proxy_request("GET", f"http://localhost:8004/deliveries/{delivery_id}"),
    }


@app.get("/all", tags=["Gateway Overview"])
def get_all_data_for_all_deliveries(_: dict = Depends(verify_token)):
    return {
        "users": proxy_request("GET", "http://localhost:8001/users"),
        "foods": proxy_request("GET", "http://localhost:8002/foods"),
        "orders": proxy_request("GET", "http://localhost:8003/orders"),
        "deliveries": proxy_request("GET", "http://localhost:8004/deliveries"),
    }
