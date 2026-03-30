"""
Database models for the Admin Control System.
Uses SQLAlchemy ORM with SQLite.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (  # type: ignore
    Column, Integer, String, DateTime, Text, ForeignKey, Boolean, create_engine, text
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
    last_version_check = Column(DateTime, nullable=True)
    agent_version = Column(String(32), nullable=True)
    install_path = Column(String(260), nullable=True)
    system_info = Column(Text, nullable=True)
    all_users = Column(Text, nullable=True)
    is_uninstalled = Column(Boolean, default=False)

    commands = relationship("Command", back_populates="device")
    admin_snapshots = relationship("AdminSnapshot", back_populates="device")
    event_logs = relationship("EventLog", back_populates="device")
    notification_campaigns = relationship("NotificationCampaign", back_populates="device")
    installed_software = relationship(
        "InstalledSoftware",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    uninstall_passwords = relationship(
        "UninstallPassword",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    activity_events = relationship(
        "ActivityEvent",
        back_populates="device",
        cascade="all, delete-orphan",
        foreign_keys="ActivityEvent.device_id",
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
    title = Column(String(100), nullable=True, default="SentraGuard")
    message = Column(Text, nullable=False)
    target_users = Column(Text, nullable=True, default='["All"]')   # JSON array e.g. ["All"]
    start_time = Column(DateTime, nullable=True)                     # NULL = send once immediately
    end_time = Column(DateTime, nullable=True)
    interval_minutes = Column(Integer, nullable=True)                # NULL = one-time delivery
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


class UninstallPassword(Base):
    __tablename__ = "uninstall_passwords"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=False, index=True)
    otp_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    used_at = Column(DateTime, nullable=True)
    issued_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    device = relationship("Device", back_populates="uninstall_passwords")

    def __repr__(self):
        return f"<UninstallPassword(device_id={self.device_id}, expires_at={self.expires_at}, used={self.used})>"


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    version = Column(String(32), unique=True, nullable=False)
    platform = Column(String(32), default="windows")
    download_path = Column(Text, nullable=False)
    checksum_sha256 = Column(String(128), nullable=False)
    release_notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def __repr__(self):
        return f"<AgentVersion(version='{self.version}', platform='{self.platform}', active={self.is_active})>"


class ActivityEvent(Base):
    """
    Stores endpoint user activity events uploaded by the SentraGuard agent.
    Events can be: LOGIN, LOGOUT, LOCK, UNLOCK, IDLE, ACTIVE,
                   SCREEN_OFF, SCREEN_ON, STARTUP, SHUTDOWN
    """
    __tablename__ = "activity_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # nullable FK — events may arrive before device is fully registered
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)   # event time (from agent)
    event = Column(String(20), nullable=False, index=True)     # LOGIN | LOGOUT | IDLE …
    username = Column(String(255), nullable=True, index=True)
    machine = Column(String(255), nullable=True, index=True)   # hostname as reported by agent
    serial = Column(String(128), nullable=True)
    ip_address = Column(String(45), nullable=True)
    duration = Column(String(32), nullable=True)               # human-readable, e.g. "12m"
    os_version = Column(String(255), nullable=True)
    synced = Column(Boolean, default=False)                    # True once server accepted it
    created_at = Column(DateTime, default=utcnow)              # server receive time
    # Application / input tracking (populated by APP_USAGE events from agent)
    process_name   = Column(String(255), nullable=True, index=True)  # e.g. "chrome.exe"
    window_title   = Column(String(512), nullable=True)
    url            = Column(String(1024), nullable=True)
    idle_seconds   = Column(Integer, nullable=True, default=0)
    mouse_clicks   = Column(Integer, nullable=True, default=0)
    keypress_count = Column(Integer, nullable=True, default=0)

    device = relationship(
        "Device",
        back_populates="activity_events",
        foreign_keys=[device_id],
    )

    def __repr__(self):
        return f"<ActivityEvent(id={self.id}, event='{self.event}', machine='{self.machine}')>"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String(20), default="admin")   # "admin" | "viewer"
    department = Column(String(255), nullable=True)

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


# Create all tables on import
Base.metadata.create_all(bind=engine)


# ── Lightweight migrations for new columns on existing SQLite DBs ─────────

def _ensure_column(table: str, column: str, ddl: str):
    """Add a column if it does not already exist (SQLite only)."""
    try:
        with engine.begin() as conn:
            cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    except Exception:
        # Silent fail to avoid blocking startup; manual migration remains possible.
        pass


_ensure_column("devices", "agent_version", "VARCHAR(32)")
_ensure_column("devices", "last_version_check", "DATETIME")
_ensure_column("devices", "install_path", "VARCHAR(260)")
_ensure_column("devices", "is_uninstalled", "BOOLEAN DEFAULT 0")
_ensure_column("users", "department", "VARCHAR(255)")

# Activity events — ensure all columns exist for older installs that predate these fields.
_ensure_column("activity_events", "machine",        "VARCHAR(255)")
_ensure_column("activity_events", "serial",         "VARCHAR(128)")
_ensure_column("activity_events", "ip_address",     "VARCHAR(45)")
_ensure_column("activity_events", "os_version",     "VARCHAR(255)")
_ensure_column("activity_events", "duration",       "VARCHAR(32)")
# Application / input tracking columns (added with APP_USAGE event support)
_ensure_column("activity_events", "process_name",   "VARCHAR(255)")
_ensure_column("activity_events", "window_title",   "VARCHAR(512)")
_ensure_column("activity_events", "url",            "VARCHAR(1024)")
_ensure_column("activity_events", "idle_seconds",   "INTEGER DEFAULT 0")
_ensure_column("activity_events", "mouse_clicks",   "INTEGER DEFAULT 0")
_ensure_column("activity_events", "keypress_count", "INTEGER DEFAULT 0")

# Notification campaigns — migrate existing DBs that may have NOT NULL constraints
_ensure_column("notification_campaigns", "title", "VARCHAR(100) DEFAULT 'SentraGuard'")

# Lightweight indexes for frequent analytics queries
try:
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_commands_created_at ON commands(created_at)"))
except Exception:
    # Index creation is best-effort to avoid startup failure on older SQLite versions.
    pass
