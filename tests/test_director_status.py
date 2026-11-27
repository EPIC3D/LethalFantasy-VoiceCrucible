"""Directing progress file and the standby of the worker on the director's PC."""

import json
import time
from types import SimpleNamespace

from voicecrucible.coordinator.app import CoordinatorState
from voicecrucible.directors import status


def test_status_roundtrip_and_stale(tmp_path):
    assert status.read(tmp_path) is None
    status.write(tmp_path, {"running": True, "addresses": ["10.0.0.5"]})
    assert status.read(tmp_path)["active"] is True
    data = json.loads((tmp_path / status.FILE).read_text())
    data["updated"] = time.time() - status.STALE_AFTER_SECONDS - 1  # a crashed `direct` stops holding the worker
    (tmp_path / status.FILE).write_text(json.dumps(data))
    assert status.read(tmp_path)["active"] is False
    status.write(tmp_path, {"running": False, "addresses": ["10.0.0.5"]})
    assert status.read(tmp_path)["active"] is False


def test_host_addresses():
    assert status.host_addresses("") == set()
    assert status.host_addresses("localhost") == {"127.0.0.1", "::1"}
    assert status.host_addresses("192.168.1.20") == {"192.168.1.20"}


def test_worker_on_director_pc_gets_no_work(tmp_path):
    state = SimpleNamespace(work_dir=tmp_path)
    directing_on = CoordinatorState.directing_on
    assert directing_on(state, "10.0.0.5") is False
    status.write(tmp_path, {"running": True, "addresses": ["10.0.0.5"]})
    assert directing_on(state, "10.0.0.5") is True
    assert directing_on(state, "10.0.0.6") is False  # the other workers keep rendering
    status.write(tmp_path, {"running": False, "addresses": ["10.0.0.5"]})
    assert directing_on(state, "10.0.0.5") is False  # done: the model is unloaded, the worker renders again
