from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, generate_next_fid, get_db
from models import Food


app = FastAPI()

# Ensure SQLite tables are available when the service starts.
Base.metadata.create_all(bind=engine)


class FoodCreate(BaseModel):
	name: str
	description: str
	category: str
	price: float
	is_available: bool = True


class FoodUpdate(BaseModel):
	name: str
	description: str
	category: str
	price: float
	is_available: bool


@app.get("/")
def root():
	return {"message": "Food service is running with SQLite database foods.db"}


@app.get("/foods")
def get_foods(db: Session = Depends(get_db)):
	foods = db.query(Food).all()
	return foods


@app.get("/foods/{fid}")
def get_food(fid: str, db: Session = Depends(get_db)):
	food = db.query(Food).filter(Food.Fid == fid).first()
	if not food:
		raise HTTPException(status_code=404, detail="Food not found")
	return food


@app.post("/foods")
def create_food(payload: FoodCreate, db: Session = Depends(get_db)):
	next_fid = generate_next_fid(db)
	food = Food(
		Fid=next_fid,
		name=payload.name,
		description=payload.description,
		category=payload.category,
		price=payload.price,
		is_available=payload.is_available,
	)
	db.add(food)
	db.commit()
	db.refresh(food)
	return food


@app.put("/foods/{fid}")
def update_food(fid: str, payload: FoodUpdate, db: Session = Depends(get_db)):
	food = db.query(Food).filter(Food.Fid == fid).first()
	if not food:
		raise HTTPException(status_code=404, detail="Food not found")

	food.name = payload.name
	food.description = payload.description
	food.category = payload.category
	food.price = payload.price
	food.is_available = payload.is_available

	db.commit()
	db.refresh(food)
	return food


@app.delete("/foods/{fid}")
def delete_food(fid: str, db: Session = Depends(get_db)):
	food = db.query(Food).filter(Food.Fid == fid).first()
	if not food:
		raise HTTPException(status_code=404, detail="Food not found")

	db.delete(food)
	db.commit()
	return {"message": f"Food {fid} deleted"}
