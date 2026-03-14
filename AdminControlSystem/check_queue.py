import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'server'))
from app import SessionLocal
from models import Command

db = SessionLocal()
pending = db.query(Command).filter(Command.status == 'pending').all()
print(f"Pending commands in queue: {len(pending)}")
for p in pending[:5]:
    print(f"  - {p.action}: {p.payload}")

db.close()
