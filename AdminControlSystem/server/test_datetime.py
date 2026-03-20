
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
engine = create_engine(f"sqlite:///{db_path}")
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Device(Base):
    __tablename__ = "devices"
    id = Column(String(36), primary_key=True)
    last_seen = Column(DateTime)

session = Session()
try:
    dev = session.query(Device).first()
    if dev:
        print(f"Current last_seen: {dev.last_seen} (type: {type(dev.last_seen)})")
        print("Attempting to update with timezone-aware datetime...")
        dev.last_seen = datetime.now(timezone.utc)
        session.commit()
        print("Success!")
    else:
        print("No devices found.")
except Exception as e:
    print(f"FAILED: {e}")
finally:
    session.close()
