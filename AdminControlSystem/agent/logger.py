"""
logger.py — Agent log() function with stdout + rotating file output.
Intentionally imports NOTHING from other agent modules to avoid circular deps.
"""

import os
import sys
from datetime import datetime
from pathlib import Path


def log(level: str, message: str) -> None:
    """Print a timestamped log line to stdout and append it to the log file."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}]  {message}"
    print(line, flush=True)
    try:
        exe_dir = Path(os.path.dirname(os.path.abspath(sys.executable)))
        log_path = Path(os.environ.get("TEMP", ".")) / "agent_debug.log"
        if "Program Files" in str(exe_dir):
            log_path = exe_dir / "agent_debug.log"
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
