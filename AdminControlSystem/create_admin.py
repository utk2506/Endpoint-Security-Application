import sys
import os

# Add the server directory to the path so we can import models
sys.path.append(os.path.join(os.path.dirname(__file__), 'server'))

from models import SessionLocal, User
from app import get_password_hash

def create_admin(username, password):
    db = SessionLocal()
    try:
        # Check if user already exists
        user = db.query(User).filter(User.username == username).first()
        if user:
            print(f"Error: User '{username}' already exists.")
            return

        hashed_password = get_password_hash(password)
        new_user = User(username=username, hashed_password=hashed_password)
        db.add(new_user)
        db.commit()
        print(f"Success: User '{username}' created successfully.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_admin.py <username> <password>")
    else:
        create_admin(sys.argv[1], sys.argv[2])
