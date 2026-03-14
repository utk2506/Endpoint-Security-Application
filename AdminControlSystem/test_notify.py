import requests
import datetime
import json

now = datetime.datetime.utcnow().isoformat() + "Z"
et = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat() + "Z"

payload = {
    "device_id": "test", # We need a real device ID
    "message": "test msg",
    "target_users": ["All"],
    "is_recurring": True,
    "start_time": now,
    "end_time": et,
    "interval_minutes": 1
}

devices = requests.get('http://localhost:8000/devices').json()
if devices:
    payload["device_id"] = devices[0]["id"]
    r = requests.post('http://localhost:8000/api/v1/notifications', json=payload)
    print(r.status_code, r.text)
else:
    print("No devices found")
