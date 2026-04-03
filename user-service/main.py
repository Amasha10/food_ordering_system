from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import bcrypt

INTERNAL_SECRET = "internal-service-secret-key"

DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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
    if request.method == "GET":
        return await call_next(request)
    if request.headers.get("X-Internal-Secret") != INTERNAL_SECRET:
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, index=True)
    phone_number = Column(String)
    address = Column(String)
    password_hash = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)


def ensure_user_schema():
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(users)"))
        existing_columns = {row[1]: row[2] for row in result.fetchall()}

        if "id" not in existing_columns:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name VARCHAR, email VARCHAR, phone_number VARCHAR, address VARCHAR)"
                )
            )
        else:
            if "name" not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR"))
            if "email" not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR"))
            if "phone_number" not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN phone_number VARCHAR"))
            if "address" not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN address VARCHAR"))
            if "password_hash" not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
        connection.commit()


ensure_user_schema()


class User(BaseModel):
    user_id: int = Field(..., title="User ID")
    user_name: str = Field(..., title="User Name")
    email: str = Field(..., title="Email")
    phone_number: str = Field(..., title="Phone Number")
    address: str = Field(..., title="Address")

    @field_validator("email")
    def validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("Email must contain @")
        return value

    @field_validator("phone_number")
    def validate_phone_number(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must be exactly 10 digits")
        return value

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    user_name: str = Field(..., title="User Name")
    email: str = Field(..., title="Email")
    phone_number: str = Field(..., title="Phone Number")
    address: str = Field(..., title="Address")
    password: str = Field(..., title="Password", min_length=8)

    @field_validator("email")
    def validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("Email must contain @")
        return value

    @field_validator("phone_number")
    def validate_phone_number(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must be exactly 10 digits")
        return value

    class Config:
        from_attributes = True


class UserAuthenticate(BaseModel):
    email: str = Field(..., title="Email")
    password: str = Field(..., title="Password")


class UserPatch(BaseModel):
    user_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None

    @field_validator("email")
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if "@" not in value:
            raise ValueError("Email must contain @")
        return value

    @field_validator("phone_number")
    def validate_phone_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must be exactly 10 digits")
        return value


def get_next_user_id(db):
    last_user = db.query(UserDB).order_by(UserDB.id.desc()).first()
    return last_user.id + 1 if last_user else 1


@app.post("/users")
def create_user(user: UserCreate):
    db = SessionLocal()
    new_user_id = get_next_user_id(db)
    password_hash = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt()).decode()

    db_user = UserDB(
        id=new_user_id,
        name=user.user_name,
        email=user.email,
        phone_number=user.phone_number,
        address=user.address,
        password_hash=password_hash,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {
        "user_id": db_user.id,
        "user_name": db_user.name,
        "email": db_user.email,
        "phone_number": db_user.phone_number,
        "address": db_user.address,
    }


@app.post("/users/authenticate")
def authenticate_user(credentials: UserAuthenticate):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.email == credentials.email, UserDB.password_hash.isnot(None)).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not bcrypt.checkpw(credentials.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {
        "user_id": user.id,
        "user_name": user.name,
        "email": user.email,
    }


@app.get("/users")
def get_users():
    db = SessionLocal()
    users = db.query(UserDB).all()
    return [
        {
            "user_id": user.id,
            "user_name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "address": user.address,
        }
        for user in users
    ]


@app.get("/users/{user_id}")
def get_user(user_id: int):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user.id,
        "user_name": user.name,
        "email": user.email,
        "phone_number": user.phone_number,
        "address": user.address,
    }


@app.put("/users/{user_id}")
def update_user(user_id: int, updated_user: User):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.id = updated_user.user_id
    user.name = updated_user.user_name
    user.email = updated_user.email
    user.phone_number = updated_user.phone_number
    user.address = updated_user.address
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.id,
        "user_name": user.name,
        "email": user.email,
        "phone_number": user.phone_number,
        "address": user.address,
    }


@app.patch("/users/{user_id}")
def partial_update_user(user_id: int, updated_user: UserPatch):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    before_update = {
        "user_id": user.id,
        "user_name": user.name,
        "email": user.email,
        "phone_number": user.phone_number,
        "address": user.address,
    }

    if updated_user.user_name is not None:
        user.name = updated_user.user_name
    if updated_user.email is not None:
        user.email = updated_user.email
    if updated_user.phone_number is not None:
        user.phone_number = updated_user.phone_number
    if updated_user.address is not None:
        user.address = updated_user.address

    db.commit()
    db.refresh(user)
    return {
        "message": "User partially updated",
        "before_update": before_update,
        "after_update": {
            "user_id": user.id,
            "user_name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "address": user.address,
        },
    }


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {
        "message": "User deleted",
        "user": {
            "user_id": user.id,
            "user_name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "address": user.address,
        },
    }
