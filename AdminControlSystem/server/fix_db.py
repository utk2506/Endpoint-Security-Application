
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
curr = conn.cursor()

# Check devices table
curr.execute("PRAGMA table_info(devices)")
cols = [row[1] for row in curr.fetchall()]
print(f"Devices columns: {cols}")

missing = ["is_uninstalled", "agent_version", "last_version_check", "install_path"]
for m in missing:
    if m not in cols:
        print(f"Adding missing column: {m}")
        if m == "is_uninstalled":
            curr.execute("ALTER TABLE devices ADD COLUMN is_uninstalled BOOLEAN DEFAULT 0")
        elif m == "last_version_check":
            curr.execute("ALTER TABLE devices ADD COLUMN last_version_check DATETIME")
        elif m == "agent_version":
            curr.execute("ALTER TABLE devices ADD COLUMN agent_version VARCHAR(32)")
        elif m == "install_path":
            curr.execute("ALTER TABLE devices ADD COLUMN install_path VARCHAR(260)")

conn.commit()
conn.close()
print("Done.")
