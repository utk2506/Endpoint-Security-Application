import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'server'))
from app import SessionLocal
from models import NotificationCampaign

db = SessionLocal()
camps = db.query(NotificationCampaign).filter(NotificationCampaign.is_active == True).all()
for c in camps:
    c.is_active = False

db.commit()
print(f"Cancelled {len(camps)} campaigns")
db.close()
