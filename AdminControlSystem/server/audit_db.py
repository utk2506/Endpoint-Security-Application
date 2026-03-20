
import sqlite3
import os

db_path = r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\database.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

def check_table(table_name):
    curr.execute(f"PRAGMA table_info({table_name})")
    cols = [row[1] for row in curr.fetchall()]
    print(f"{table_name} columns: {cols}")

tables = ["devices", "commands", "admin_snapshots", "notification_campaigns", "installed_software", "activity_logs", "uninstall_passwords", "agent_versions", "users"]
for t in tables:
    check_table(t)

conn.close()
