"""The coordinator's identity: a random ID and a self-signed TLS certificate created on first start.

There is no certificate authority: workers pin the certificate's SHA-256 fingerprint when they pair.
Deleting the folder creates a new identity – every worker then has to pair again.
"""

from __future__ import annotations

import secrets
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from voicecrucible.core import protocol


@dataclass
class CoordinatorIdentity:
    """Coordinator ID, certificate files and the certificate fingerprint workers pin."""

    coordinator_id: str
    cert_path: Path
    key_path: Path
    fingerprint: str

    def server_context(self) -> ssl.SSLContext:
        """TLS context for the coordinator's API server."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cert_path, self.key_path)
        ctx.num_tickets = 0  # no TLS 1.3 session tickets: unread tickets made Windows reset short connections
        return ctx


def ensure_identity(folder: Path) -> CoordinatorIdentity:
    """Load the coordinator identity from `folder`, creating it on first use."""
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path, id_path = folder / "cert.pem", folder / "key.pem", folder / "coordinator_id.txt"
    if not (cert_path.exists() and key_path.exists()):
        _generate_certificate(cert_path, key_path)
    if not id_path.exists():
        id_path.write_text(secrets.token_hex(8), encoding="utf-8")
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="ascii"))
    return CoordinatorIdentity(id_path.read_text(encoding="utf-8").strip(), cert_path, key_path,
                               protocol.fingerprint(der))


def _generate_certificate(cert_path: Path, key_path: Path) -> None:
    """Create a self-signed EC P-256 certificate valid for 10 years."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Voice Crucible coordinator")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
