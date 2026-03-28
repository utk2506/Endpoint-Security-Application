"""
network.py — HTTP/HTTPS API client, SSL context, cert pinning, and binary download.
"""

import hashlib
import http.client
import json
import ssl
from pathlib import Path
from urllib import error, request

from config import AGENT_VERSION, CREATE_NO_WINDOW
from logger import log
from state import ensure_dir

# ── Runtime globals (set once in main()) ─────────────────────────────────────

_ssl_context: "ssl.SSLContext | None" = None
AGENT_AUTH_TOKEN: "str | None" = None
PINNED_CERT_SHA256: "str | None" = None


# ── PowerShell availability ───────────────────────────────────────────────────

import subprocess
import time

_POWERSHELL_OK: "bool | None" = None
_POWERSHELL_LAST_CHECK: float = 0.0
_POWERSHELL_CACHE_TTL: float = 60.0


def powershell_available() -> bool:
    """Cached check — re-verifies every 60 s to handle transient failures."""
    global _POWERSHELL_OK, _POWERSHELL_LAST_CHECK
    now = time.time()
    if _POWERSHELL_OK is not None and (now - _POWERSHELL_LAST_CHECK) < _POWERSHELL_CACHE_TTL:
        return _POWERSHELL_OK
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', 'exit'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=5,
        )
        _POWERSHELL_OK = result.returncode == 0
    except Exception:
        _POWERSHELL_OK = False
    _POWERSHELL_LAST_CHECK = now
    if not _POWERSHELL_OK:
        log('WARN', "PowerShell unavailable or failing to start; related features disabled.")
    return _POWERSHELL_OK  # type: ignore[return-value]


# ── Certificate pinning ───────────────────────────────────────────────────────

def _check_cert_pin(response) -> None:
    """Optional TLS certificate pinning via SHA256 fingerprint."""
    if not PINNED_CERT_SHA256:
        return
    try:
        cert_bin = response.fp.raw._sock.getpeercert(binary_form=True)  # type: ignore[attr-defined]
        fp = hashlib.sha256(cert_bin).hexdigest().lower()
        if fp != PINNED_CERT_SHA256.lower():
            raise ValueError(f"TLS pin mismatch: expected {PINNED_CERT_SHA256}, got {fp}")
    except Exception as e:
        log("ERROR", f"Certificate pinning failed: {e}")
        raise


# ── API call helper ───────────────────────────────────────────────────────────

def api_call(base_url: str, method: str, path: str, body=None, headers=None, timeout: int = 15):
    """Simple HTTP helper using only stdlib urllib (no extra deps)."""
    url = f"{base_url}{path}"
    data = json.dumps(body).encode('utf-8') if body else None
    req = request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Agent-Version', AGENT_VERSION)
    if AGENT_AUTH_TOKEN:
        req.add_header('Authorization', f"Bearer {AGENT_AUTH_TOKEN}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context) as res:
            _check_cert_pin(res)
            return json.loads(res.read().decode('utf-8'))
    except error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        log('ERROR', f"API {method} {path} → {e.code}: {detail}")
        return None
    except http.client.RemoteDisconnected as e:
        log('ERROR', f"Remote end closed connection without response. "
            f"(Hint: check HTTP vs HTTPS port.) Details: {e}")
        return None
    except error.URLError as e:
        if "certificate verify failed" in str(e).lower():
            log('ERROR', f"SSL certificate verification failed: {e}. "
                f"(Hint: Use --no-verify-ssl for self-signed certs.)")
        else:
            log('ERROR', f"Cannot reach server: {e.reason}")
        return None


# ── Binary download ────────────────────────────────────────────────────────────

def download_binary(url: str, dest_path: Path) -> Path:
    """Download binary content to dest_path with auth, pinning, and progress logging."""
    req = request.Request(url)
    if AGENT_AUTH_TOKEN:
        req.add_header("Authorization", f"Bearer {AGENT_AUTH_TOKEN}")
    req.add_header("X-Agent-Version", AGENT_VERSION)

    with request.urlopen(req, timeout=60, context=_ssl_context) as res:
        _check_cert_pin(res)
        total_size = int(res.getheader('Content-Length', 0))
        ensure_dir(dest_path.parent)

        CHUNK_SIZE = 1_048_576  # 1 MB
        downloaded = 0
        last_pct = 0

        with open(dest_path, 'wb') as f:
            while True:
                chunk = res.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = int((downloaded / total_size) * 100)
                    if pct - last_pct >= 20 or pct == 100:
                        log("INFO", f"⬇ Downloading update: {pct}% "
                            f"({downloaded // 1_048_576} MB / {total_size // 1_048_576} MB)")
                        last_pct = pct
    return dest_path
