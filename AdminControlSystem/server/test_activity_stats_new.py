import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys

# Add current dir to sys.path so we can import models
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import Base, ActivityLog, Device

# Use a temporary in-memory database for testing
engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

def test_get_activity_stats():
    db = SessionLocal()
    
    # Create a mock device
    device_id = "test-device"
    db.add(Device(id=device_id, hostname="test-pc", ip_address="127.0.0.1"))
    db.commit()
    
    # Mock Activity Logs (Interval = 15s)
    # Scenario: User idle for 60 seconds (Samples at T=15, 30, 45, 60)
    # Agent reports CUMULATIVE idle time: 15, 30, 45, 60
    base_time = datetime.now(timezone.utc)
    logs = [
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=0), idle_seconds=3600, process_name="Idle", username="User1"),
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=15), idle_seconds=3600, process_name="Idle", username="User1"),
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=30), idle_seconds=3600, process_name="Idle", username="User1"),
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=45), idle_seconds=3600, process_name="Idle", username="User1"),
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=60), idle_seconds=0, process_name="VS Code.exe", username="User1"),
        ActivityLog(device_id="dev-1", timestamp=base_time + timedelta(seconds=75), idle_seconds=0, process_name="VS Code.exe", username="User1"),
    ]
    db.add_all(logs)
    db.commit()
    
    # Import the function from app.py
    # We need to mock the query and db session or just call it directly with the test db
    from app import get_activity_stats
    
    class FakeUser:
        role = "admin"
        username = "test"
    
    # Call the actual function
    # Run aggregation
    result = get_activity_stats(db=db)
    
    # Total Duration: 6 samples * 15s = 90s
    # Total Idle: 4 samples * 15s = 60s
    # Process Dist: 2 samples * 15s = 30s
    
    print("--- Test Results ---")
    print(f"Total Duration (expected 90s): {result['total_duration_seconds']}s")
    print(f"Total Idle (expected 60s): {result['total_idle_seconds']}s")
    print(f"Device Count (expected 1): {result['device_count']}")
    print(f"Process Distribution: {result['process_distribution']}")
    
    # Assertions
    assert result['total_duration_seconds'] == 90
    assert result['total_idle_seconds'] == 60
    assert result['device_count'] == 1
    assert result['process_distribution'].get('VS Code.exe', 0) == 30
    assert result['user_distribution'].get('User1', 0) == 30
    
    print("\n✅ Test Passed!")

if __name__ == "__main__":
    try:
        test_get_activity_stats()
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
