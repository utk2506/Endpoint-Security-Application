
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

# Check commands table
curr.execute("PRAGMA table_info(commands)")
cols = [row[1] for row in curr.fetchall()]
print(f"Commands columns: {cols}")

missing = ["auto_revoked", "expires_at"]
for m in missing:
    if m not in cols:
        print(f"Adding missing column to commands: {m}")
        if m == "auto_revoked":
            curr.execute("ALTER TABLE commands ADD COLUMN auto_revoked BOOLEAN DEFAULT 0")
        elif m == "expires_at":
            curr.execute("ALTER TABLE commands ADD COLUMN expires_at DATETIME")

conn.commit()
conn.close()
print("Done.")
