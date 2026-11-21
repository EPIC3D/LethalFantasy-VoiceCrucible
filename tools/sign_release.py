"""Maintainer tool: create the update signing key once, then sign every release zip.

  python tools/sign_release.py newkey <private-key-file>     -> prints the public key for update.PUBLIC_KEY
  python tools/sign_release.py sign <private-key-file> <release.zip>   -> writes <release.zip>.sig

Keep the private key file OUTSIDE the repository and back it up; whoever has it can publish updates.
The key file is encrypted with a passphrase you type (never stored), so a copied file alone is useless.
"""

import base64
import getpass
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def newkey(path: Path) -> None:
    """Create a key pair; the private key is written to `path` (refuses to overwrite)."""
    if path.exists():
        sys.exit(f"{path} exists – refusing to overwrite a signing key")
    path.parent.mkdir(parents=True, exist_ok=True)
    phrase = getpass.getpass("New passphrase for the signing key: ")
    if len(phrase) < 12 or phrase != getpass.getpass("Repeat it: "):
        sys.exit("passphrases differ or shorter than 12 characters – no key created")
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.BestAvailableEncryption(phrase.encode())))
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("PUBLIC_KEY =", repr(base64.b64encode(raw).decode()))


def sign(key_path: Path, zip_path: Path) -> None:
    """Write the base64 signature of the zip next to it."""
    phrase = getpass.getpass("Passphrase of the signing key: ").encode()
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=phrase)
    signature = key.sign(zip_path.read_bytes())
    zip_path.with_name(zip_path.name + ".sig").write_text(base64.b64encode(signature).decode() + "\n")
    print("signed", zip_path)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "newkey":
        newkey(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "sign":
        sign(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        sys.exit(__doc__)
