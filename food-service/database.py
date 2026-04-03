from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "foods.db"
DATABASE_URL = f"sqlite:///{DB_FILE.as_posix()}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_next_fid(db):
    """Generate next Fid in format F_XXX based on the highest existing suffix."""
    from models import Food
    existing_fids = db.query(Food.Fid).all()
    next_num = 1

    for (fid,) in existing_fids:
        match = re.search(r"(\d+)$", str(fid))
        if match:
            next_num = max(next_num, int(match.group(1)) + 1)

    return f"F_{next_num}"
