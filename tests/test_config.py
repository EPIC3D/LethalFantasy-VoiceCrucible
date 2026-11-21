"""Tests for loading and validating voicecrucible.toml."""

from pathlib import Path

import pytest

from voicecrucible.core import config


def _write(tmp_path: Path, text: str) -> Path:
    """Write a config file into the temp folder and return its path."""
    p = tmp_path / "voicecrucible.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults_are_valid():
    cfg = config.load(None)
    assert cfg.director.mode == "none"
    assert cfg.render.characters == []  # empty = every character of the profile


def test_example_file_loads():
    example = Path(__file__).parents[1] / "config" / "voicecrucible.example.toml"
    assert config.load(example).coordinator.port == 5130


def test_relative_paths_follow_config_file(tmp_path):
    cfg = config.load(_write(tmp_path, '[paths]\noutput_dir = "out"\n'))
    assert cfg.path(cfg.paths.output_dir) == (tmp_path / "out").resolve()


def test_int_accepted_for_float(tmp_path):
    assert config.load(_write(tmp_path, "[checks]\nmin_mos = 2\n")).checks.min_mos == 2.0


@pytest.mark.parametrize("text, message", [
    ("[render]\nengin = 'qwen'\n", "unknown key 'engin'"),
    ("[renderer]\nengine = 'qwen'\n", "unknown section"),
    ("[coordinator]\nport = '5130'\n", "must be int"),
    ("[coordinator]\nport = true\n", "must be int"),
    ("[coordinator]\nport = 80\n", "between 1024"),
    ("[director]\nmode = 'magic'\n", "mode must be one of"),
    ("[director]\nmode = 'file'\n", "needs 'file'"),
])
def test_errors_name_the_problem(tmp_path, text, message):
    with pytest.raises(config.ConfigError, match=message):
        config.load(_write(tmp_path, text))
