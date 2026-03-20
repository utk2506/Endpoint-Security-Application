import sys
import hashlib
from pathlib import Path
import shutil

from models import SessionLocal, AgentVersion

def main():
    agent_src = Path(r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\agent\dist\agent.exe")
    if not agent_src.exists():
        print(f"Error: {agent_src} not found!")
        return

    updates_dir = Path(r"c:\Users\ITSupport\Downloads\New folder (9)\AdminControlSystem\server\updates")
    updates_dir.mkdir(exist_ok=True)

    version = "1.1.16"
    dest_name = f"agent-{version}.exe"
    dest_path = updates_dir / dest_name

    shutil.copy2(agent_src, dest_path)
    print(f"Copied to {dest_path}")

    data = dest_path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    size = dest_path.stat().st_size

    db = SessionLocal()
    # Deactivate old versions
    db.query(AgentVersion).update({"is_active": False})
    
    # Check if this version already exists
    existing = db.query(AgentVersion).filter(AgentVersion.version == version).first()
    if existing:
        existing.checksum_sha256 = checksum
        existing.file_size = size
        existing.is_active = True
        existing.download_path = dest_name
    else:
        rec = AgentVersion(
            version=version,
            download_path=dest_name,
            checksum_sha256=checksum,
            is_active=True,
            file_size=size,
            platform="windows"
        )
        db.add(rec)
    
    db.commit()
    print(f"Successfully registered version {version} in database!")

if __name__ == '__main__':
    main()
