"""
Database models for the Admin Control System.
Uses SQLAlchemy ORM with SQLite.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (  # type: ignore
    Column, Integer, String, DateTime, Text, ForeignKey, Boolean, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship  # type: ignore

DATABASE_URL = "sqlite:///database.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    hostname = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=False)
    registered_at = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow)
    system_info = Column(Text, nullable=True)
    all_users = Column(Text, nullable=True)

    commands = relationship("Command", back_populates="device")
    admin_snapshots = relationship("AdminSnapshot", back_populates="device")
    event_logs = relationship("EventLog", back_populates="device")

    def __repr__(self):
        return f"<Device(id={self.id}, hostname='{self.hostname}')>"


class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    action = Column(String(20), nullable=False)       # grant | revoke | check | shell
    payload = Column(Text, nullable=True)             # raw script for 'shell' action
    username = Column(String(255), nullable=True)      # null for 'check'/'shell'
    status = Column(String(20), default="pending")     # pending | executing | completed | failed
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    executed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)         # UTC; NULL = no expiry
    auto_revoked = Column(Boolean, default=False)        # True once server auto-queued a revoke

    device = relationship("Device", back_populates="commands")

    def __repr__(self):
        return f"<Command(id={self.id}, action='{self.action}', status='{self.status}')>"


class AdminSnapshot(Base):
    __tablename__ = "admin_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    admin_users = Column(Text, nullable=False)  # JSON-encoded list
    captured_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="admin_snapshots")

    def __repr__(self):
        return f"<AdminSnapshot(id={self.id}, device_id={self.device_id})>"


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    hostname = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    event_id = Column(Integer, nullable=False, index=True)
    event_name = Column(String(100), nullable=False)
    log_source = Column(String(50), nullable=False)    # Security / System / Application
    timestamp = Column(DateTime, nullable=False, index=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="event_logs")

    def __repr__(self):
        return f"<EventLog(id={self.id}, event_id={self.event_id}, event_name='{self.event_name}')>"


# Create all tables on import
Base.metadata.create_all(bind=engine)
