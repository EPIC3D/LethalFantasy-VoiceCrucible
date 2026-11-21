# Security


## Updates (`crucible update`)

The updater's code is MIT and public on purpose: its safety comes from the signature, not from secrecy.

- **Started by you only.** No background checks, the coordinator never updates workers.
- **HTTPS + Ed25519 signature.** Every release zip is signed with the maintainer's private key. The public
  key is built into the version you already have, so a new download is checked against a key the attacker
  cannot change. The private key is never in the repository and is stored encrypted with a passphrase.
- **What an attacker cannot do:**
  - take over the GitHub account or the download and ship a modified zip → signature invalid, refused;
  - change the network traffic (man-in-the-middle) → HTTPS, and the signature would fail anyway;
  - serve an *older* signed release with known bugs ("downgrade") → the version inside the signed zip must
    be newer than the installed one;
  - write outside the install folder or over your data with a crafted zip → paths are checked; `runtime\`,
    `work\`, `output\`, `logs\`, settings and reference voices are never overwritten.
- **What it cannot protect against:** someone who can already change files on your computer, or a fork /
  copy of Voice Crucible downloaded from somewhere else (it has its own key – only trust this repository).
- **If the signing key were ever lost or leaked**, a release note on GitHub says so and the next version
  has to be downloaded by hand once (it carries the new public key).
- `crucible update --rollback` returns to the previous version.

## Network

- **Workers** open no port. They connect out to the one coordinator they are paired with, over TLS, and only
  talk to the certificate they pinned at pairing.
- **Coordinator**: TCP 5130 (worker API, TLS) and UDP 5131 (answers "where is the coordinator?" with its ID,
  port and certificate fingerprint – nothing secret). Both accept local-network addresses only. The watcher
  (5132) listens on `127.0.0.1` only – it cannot be reached from other computers.
- **Pairing**: a one-time 10-character code, valid 10 minutes, burnt after 5 wrong tries. The worker proves it
  knows the code with an HMAC bound to the certificate it sees, so a man-in-the-middle cannot reuse it
  quickly. Tokens are stored as SHA-256 hashes on the coordinator.
- **What workers may do**: fetch jobs, fetch reference voices by checksum, send audio. The coordinator builds
  every output path itself; a worker cannot write files on the coordinator outside the output folder.

## Data

- No telemetry, no accounts, no personal data. `crucible diagnose` removes IPs, computer and user names and
  keys from what it writes.
- Game text leaves your network only if you choose an online AI director (`crucible direct` with a cloud
  API); the command names the destination and asks first. API keys are read from an environment variable,
  never written to files or logs, never sent to workers.

## Reporting a vulnerability

Please open a GitHub issue without exploit details and ask for a private contact, or use GitHub's private
vulnerability reporting if it is enabled for the repository.
