from sqlalchemy import Column, String, Float, Boolean
from database import Base


class Food(Base):
    __tablename__ = "foods"

    Fid = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(String)
    category = Column(String)
    price = Column(Float)
    is_available = Column(Boolean, default=True)
