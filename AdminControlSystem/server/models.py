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
    notification_campaigns = relationship("NotificationCampaign", back_populates="device")
    installed_software = relationship(
        "InstalledSoftware",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    activity_logs = relationship(
        "ActivityLog",
        back_populates="device",
        cascade="all, delete-orphan",
    )

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


class NotificationCampaign(Base):
    __tablename__ = "notification_campaigns"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False)
    message = Column(Text, nullable=False)
    target_users = Column(Text, nullable=False)        # JSON array e.g. ["All"] or ["user1"]
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    interval_minutes = Column(Integer, nullable=False)
    last_sent = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="notification_campaigns")

    def __repr__(self):
        return f"<NotificationCampaign(id={self.id}, device_id={self.device_id})>"


class InstalledSoftware(Base):
    __tablename__ = "installed_software"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False, index=True)
    name = Column(String(512), nullable=False)
    version = Column(String(100), nullable=True)
    publisher = Column(String(255), nullable=True)
    install_date = Column(String(32), nullable=True)
    uninstall_string = Column(Text, nullable=True)
    last_seen = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="installed_software")

    def __repr__(self):
        return f"<InstalledSoftware(id={self.id}, device_id={self.device_id}, name='{self.name}')>"


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


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    window_title = Column(Text, nullable=True)
    process_name = Column(String(260), nullable=True)
    idle_seconds = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    keypress_count = Column(Integer, default=0)

    device = relationship("Device", back_populates="activity_logs")

    def __repr__(self):
        return f"<ActivityLog(id={self.id}, device_id={self.device_id}, process='{self.process_name}')>"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String(20), default="admin")   # "admin" | "viewer"

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


# Create all tables on import
Base.metadata.create_all(bind=engine)
