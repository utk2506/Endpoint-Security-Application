import sqlite3
import os

db_path = "database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

version_to_delete = "1.1.10"
print(f"Deleting version {version_to_delete} from agent_versions...")

curr.execute("DELETE FROM agent_versions WHERE version = ?", (version_to_delete,))
print(f"Rows deleted: {curr.rowcount}")

conn.commit()
conn.close()
print("Version cleanup complete.")
