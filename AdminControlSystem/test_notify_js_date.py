import requests

payload = {
    "device_id": "test", 
    "message": "test msg",
    "target_users": ["All"],
    "is_recurring": True,
    "start_time": "2026-03-15T10:00:00.000Z",
    "end_time": "2026-03-16T10:00:00.000Z",
    "interval_minutes": 1
}

devices = requests.get('http://localhost:8000/devices').json()
if devices:
    payload["device_id"] = devices[0]["id"]
    r = requests.post('http://localhost:8000/api/v1/notifications', json=payload)
    print(r.status_code, r.text)
