
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

# Check activity_logs table
curr.execute("PRAGMA table_info(activity_logs)")
cols = [row[1] for row in curr.fetchall()]
print(f"ActivityLog columns: {cols}")

missing = ["idle_seconds", "click_count", "keypress_count"]
for m in missing:
    if m not in cols:
        print(f"Adding missing column to activity_logs: {m}")
        if m == "idle_seconds":
            curr.execute("ALTER TABLE activity_logs ADD COLUMN idle_seconds INTEGER DEFAULT 0")
        elif m == "click_count":
            curr.execute("ALTER TABLE activity_logs ADD COLUMN click_count INTEGER DEFAULT 0")
        elif m == "keypress_count":
            curr.execute("ALTER TABLE activity_logs ADD COLUMN keypress_count INTEGER DEFAULT 0")

conn.commit()
conn.close()
print("Done.")
