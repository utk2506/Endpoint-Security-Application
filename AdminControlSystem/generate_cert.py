"""
generate_cert.py – Generate a self-signed SSL certificate for local HTTPS.
Requires: pip install cryptography

Outputs:
  server/server.key  (private key)
  server/server.crt  (self-signed certificate)

Usage:
  python generate_cert.py
"""

import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509  # type: ignore
from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
from cryptography.hazmat.primitives.asymmetric import rsa  # type: ignore
from cryptography.x509.oid import NameOID  # type: ignore


SERVER_DIR = Path(__file__).resolve().parent / "server"
KEY_FILE   = SERVER_DIR / "server.key"
CERT_FILE  = SERVER_DIR / "server.crt"


def generate():
    # 1. Generate RSA private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # 2. Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Admin Control System"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))  # 10 years
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # 3. Write private key
    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    # 4. Write certificate
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"✓ Private key : {KEY_FILE}")
    print(f"✓ Certificate : {CERT_FILE}")
    print("  Run: uvicorn app:app --ssl-keyfile server.key --ssl-certfile server.crt")


if __name__ == "__main__":
    generate()
