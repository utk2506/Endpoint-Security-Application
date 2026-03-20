
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

# Check agent_versions table
curr.execute("PRAGMA table_info(agent_versions)")
cols = [row[1] for row in curr.fetchall()]
print(f"AgentVersion columns: {cols}")

missing = ["is_active", "file_size"]
for m in missing:
    if m not in cols:
        print(f"Adding missing column to agent_versions: {m}")
        if m == "is_active":
            curr.execute("ALTER TABLE agent_versions ADD COLUMN is_active BOOLEAN DEFAULT 1")
        elif m == "file_size":
            curr.execute("ALTER TABLE agent_versions ADD COLUMN file_size INTEGER")

conn.commit()
conn.close()
print("Done.")
