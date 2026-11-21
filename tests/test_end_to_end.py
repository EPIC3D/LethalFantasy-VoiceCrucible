"""Coordinator + worker on this machine: discovery, pairing, rendering test lines, security checks."""

import socket
import threading
import time

import pytest

from voicecrucible.coordinator import run as coordinator_run
from voicecrucible.core.config import Config
from voicecrucible.core.jobs import Line
from voicecrucible.worker import client, discovery, identity
from voicecrucible.worker.runner import Runner
from voicecrucible.worker.transport import Connection, FingerprintMismatch


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def setup(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.coordinator.discovery_port = _free_udp_port()
    state = coordinator_run.build_state(cfg)
    running = coordinator_run.RunningCoordinator(state, 0, 0, cfg.coordinator.discovery_port)
    running.start()
    cfg.coordinator.port = running.api_port
    yield cfg, state, running
    running.stop()


def test_discovery_finds_coordinator(setup):
    cfg, state, _ = setup
    found = discovery.find_coordinators(cfg.coordinator.discovery_port, timeout=1.5)
    assert any(c["id"] == state.identity.coordinator_id and c["port"] == cfg.coordinator.port for c in found)


def test_pair_and_render(setup, tmp_path):
    cfg, state, _ = setup
    ident = client.pair(cfg, state.pairing.new_code(), f"127.0.0.1:{cfg.coordinator.port}")
    assert ident.fingerprint == state.identity.fingerprint
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF fake reference voice")
    sha = state.assets.add(ref)
    state.queue.add("test", [Line(key=f"TEST_{i}", character="MIRA", text="hello", voice=sha) for i in range(5)]
                    + [Line(key="TEST_V", character="RED", text="hi", variant="she")])
    cfg.worker.coordinator = f"127.0.0.1:{cfg.coordinator.port}"
    worker = client.WorkerClient(cfg, Runner("cpu", max_batch=4))
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    deadline = time.time() + 20
    while (state.queue.counts()["done"] < 6 or worker._unsent is not None) and time.time() < deadline:
        time.sleep(0.2)
    worker.stop.set()
    t.join(timeout=15)
    assert state.queue.counts()["done"] == 6
    assert (tmp_path / "output/voices/en/MIRA/TEST_0.ogg").stat().st_size > 1000
    assert (tmp_path / "output/voices/en/RED/TEST_V__she.ogg").exists()
    cached = list((tmp_path / "work/worker/assets").iterdir())  # reference fetched once and verified
    assert [p.name for p in cached] == [f"{sha}.wav"]


def test_stopped_worker_hands_its_job_back(setup):
    cfg, state, _ = setup
    ident = client.pair(cfg, state.pairing.new_code(), f"127.0.0.1:{cfg.coordinator.port}")
    cfg.worker.coordinator = f"127.0.0.1:{cfg.coordinator.port}"
    state.queue.add("test", [Line(key=f"STOP_{i}", character="MIRA", text="x") for i in range(3)])
    worker = client.WorkerClient(cfg, Runner("cpu"))
    worker._job = state.queue.claim(ident.worker_id, 3)  # as if Ctrl+C came right after claiming
    worker._hand_back()
    assert state.queue.counts()["pending"] == 3
    assert state.queue.recent_problems() == []  # a normal stop is not reported as a problem


def test_update_request_only_for_workers_that_allow_it(setup, monkeypatch):
    cfg, state, _ = setup
    ident = client.pair(cfg, state.pairing.new_code(), f"127.0.0.1:{cfg.coordinator.port}")
    conn = Connection("127.0.0.1", cfg.coordinator.port, ident.fingerprint, ident.token)
    beat = {"version": "0.1.0", "protocol": 1, "accepts_updates": False}
    assert conn.post("/api/heartbeat", beat)[1]["update_requested"] is False
    assert state.registry.request_update() == []  # not allowed on this worker
    beat["accepts_updates"] = True
    conn.post("/api/heartbeat", beat)
    assert state.registry.request_update() == [ident.name]
    assert conn.post("/api/heartbeat", beat)[1]["update_requested"] is True
    beat["version"] = "0.2.0"  # came back updated: request cleared
    assert conn.post("/api/heartbeat", beat)[1]["update_requested"] is False
    monkeypatch.setattr("voicecrucible.core.protocol.MIN_COMPATIBLE", 2)
    assert conn.post("/api/heartbeat", {"protocol": 1})[0] == 426  # too old worker gets a clear refusal


def test_worker_self_update_restarts_or_keeps_running(setup, monkeypatch):
    from voicecrucible.installer import update
    cfg, state, _ = setup
    client.pair(cfg, state.pairing.new_code(), f"127.0.0.1:{cfg.coordinator.port}")
    worker = client.WorkerClient(cfg, Runner("cpu"))
    monkeypatch.setattr(update, "latest", lambda: {})
    monkeypatch.setattr(update, "download_and_install", lambda rel: (_ for _ in ()).throw(update.UpdateError("bad sig")))
    assert not worker._self_update() and worker._update_status == "failed: bad sig" and worker.exit_code == 0
    monkeypatch.setattr(update, "download_and_install", lambda rel: "9.9.9")
    assert worker._self_update() and worker.exit_code == client.RESTART_EXIT_CODE


def test_wrong_code_and_unknown_token_are_refused(setup):
    cfg, state, _ = setup
    state.pairing.new_code()
    with pytest.raises(client.PairingError):
        client.pair(cfg, "AAAAA-AAAAA", f"127.0.0.1:{cfg.coordinator.port}")
    status, _ = Connection("127.0.0.1", cfg.coordinator.port, state.identity.fingerprint, "forged").post(
        "/api/claim", {"max_lines": 1})
    assert status == 401


def test_other_certificate_is_refused_before_sending(setup):
    cfg, _, _ = setup
    with pytest.raises(FingerprintMismatch):
        Connection("127.0.0.1", cfg.coordinator.port, "0" * 64, "secret-token").post("/api/claim", {})


def test_unpaired_worker_does_not_start(tmp_path):
    with pytest.raises(client.NotPaired):
        client.WorkerClient(Config(base_dir=tmp_path), Runner("cpu"))
    assert not identity.load(tmp_path / "none.json").paired
