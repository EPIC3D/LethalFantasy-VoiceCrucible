"""Tests for pairing codes and worker tokens."""

from voicecrucible.coordinator.pairing import MAX_WRONG_ATTEMPTS, Pairing
from voicecrucible.core import protocol


def test_code_works_once_and_token_is_stored_hashed(tmp_path):
    p = Pairing(tmp_path / "workers.json", "fp")
    code = p.new_code()
    token = p.pair("w1", "PC", protocol.pairing_proof(code, "fp", "w1"))
    assert token and p.check(token) == "w1"
    assert token not in (tmp_path / "workers.json").read_text()
    assert p.pair("w2", "PC2", protocol.pairing_proof(code, "fp", "w2")) is None  # one-time
    assert Pairing(tmp_path / "workers.json", "fp").check(token) == "w1"  # survives restart


def test_wrong_certificate_or_code_is_rejected(tmp_path):
    p = Pairing(tmp_path / "workers.json", "fp")
    code = p.new_code()
    assert p.pair("w1", "PC", protocol.pairing_proof(code, "other-fp", "w1")) is None
    assert p.pair("w1", "PC", protocol.pairing_proof(code, "fp", "w1")) is not None


def test_code_burns_after_wrong_attempts(tmp_path):
    p = Pairing(tmp_path / "workers.json", "fp")
    code = p.new_code()
    for _ in range(MAX_WRONG_ATTEMPTS):
        p.pair("w1", "PC", "bad")
    assert p.pair("w1", "PC", protocol.pairing_proof(code, "fp", "w1")) is None


def test_expired_code_and_revoke(tmp_path):
    p = Pairing(tmp_path / "workers.json", "fp", code_minutes=0)
    code = p.new_code()
    assert p.pair("w1", "PC", protocol.pairing_proof(code, "fp", "w1")) is None
    p = Pairing(tmp_path / "workers.json", "fp")
    token = p.pair("w1", "PC", protocol.pairing_proof(p.new_code(), "fp", "w1"))
    assert p.revoke("w1") and p.check(token) is None
