import sqlite3

conn = sqlite3.connect('server/admin_control.db')
cursor = conn.cursor()

cursor.execute("UPDATE notification_campaigns SET is_active = 0 WHERE is_active = 1")
conn.commit()

print(f"Cancelled {cursor.rowcount} active campaigns.")
conn.close()
