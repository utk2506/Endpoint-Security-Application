
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

curr.execute("SELECT id, hostname, last_seen FROM devices")
rows = curr.fetchall()
print(f"Registered Devices ({len(rows)}):")
for r in rows:
    print(r)

conn.close()
