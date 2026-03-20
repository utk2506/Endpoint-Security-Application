import sys
from models import SessionLocal, AgentVersion

def main():
    db = SessionLocal()
    versions_to_delete = ['1.1.15']
    deleted_count = 0
    for v in versions_to_delete:
        rec = db.query(AgentVersion).filter(AgentVersion.version == v).first()
        if rec:
            db.delete(rec)
            deleted_count += 1
            print(f"Deleted version {v}")
    db.commit()
    print(f"Done! Deleted {deleted_count} versions.")

if __name__ == '__main__':
    main()
