"""
Database models for the Admin Control System.
Uses SQLAlchemy ORM with SQLite.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = "sqlite:///database.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hostname = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=False)
    registered_at = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow)

    commands = relationship("Command", back_populates="device")
    admin_snapshots = relationship("AdminSnapshot", back_populates="device")

    def __repr__(self):
        return f"<Device(id={self.id}, hostname='{self.hostname}')>"


class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    action = Column(String(20), nullable=False)       # grant | revoke | check
    username = Column(String(255), nullable=True)      # null for 'check'
    status = Column(String(20), default="pending")     # pending | executing | completed | failed
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    executed_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="commands")

    def __repr__(self):
        return f"<Command(id={self.id}, action='{self.action}', status='{self.status}')>"


class AdminSnapshot(Base):
    __tablename__ = "admin_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    admin_users = Column(Text, nullable=False)  # JSON-encoded list
    captured_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="admin_snapshots")

    def __repr__(self):
        return f"<AdminSnapshot(id={self.id}, device_id={self.device_id})>"


# Create all tables on import
Base.metadata.create_all(bind=engine)
