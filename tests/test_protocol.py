"""Tests for discovery messages and the pairing proof."""

from voicecrucible.core import protocol


def test_beacon_roundtrip():
    b = protocol.parse_beacon(protocol.make_beacon("abc", 5130, "f" * 64))
    assert b == {"id": "abc", "port": 5130, "fp": "f" * 64}


def test_junk_is_rejected():
    for data in (b"", b"hello", b"[]", b'{"app":"other","v":1}', b'{"app":"voicecrucible","v":1,"id":"x"}', b"x" * 5000):
        assert protocol.parse_beacon(data) is None
    assert protocol.is_query(protocol.make_query())
    assert not protocol.is_query(protocol.make_beacon("a", 1, "b"))


def test_code_is_normalized():
    assert protocol.normalize_code("abcde-fghjk ") == "ABCDEFGHJK"
    assert protocol.pairing_proof("abcde-fghjk", "fp", "w") == protocol.pairing_proof("ABCDEFGHJK", "fp", "w")


def test_proof_is_bound_to_certificate_and_worker():
    p = protocol.pairing_proof("ABCDEFGHJK", "fp1", "w1")
    assert p != protocol.pairing_proof("ABCDEFGHJK", "fp2", "w1")
    assert p != protocol.pairing_proof("ABCDEFGHJK", "fp1", "w2")
    assert p != protocol.pairing_proof("ABCDEFGHJX", "fp1", "w1")
