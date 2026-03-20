import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'server', 'database.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'admin'")
    conn.commit()
    print("Migration successful: added 'role' column to users table.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Column 'role' already exists.")
    else:
        print(f"Error: {e}")

conn.close()
