"""Config parsing + get/set round-trip tests."""
from __future__ import annotations

from pathlib import Path

from canon import config as cfg


def test_defaults_roundtrip(tmp_path: Path):
    c = cfg.CanonConfig()
    cfg.save(tmp_path, c)
    loaded = cfg.load(tmp_path)
    assert loaded.clarity_threshold == 0.7
    assert loaded.clarity_max_iter == 5
    assert loaded.agent_default == "none"


def test_set_and_get_dotted_key(tmp_path: Path):
    cfg.save(tmp_path, cfg.CanonConfig())
    cfg.set_key(tmp_path, "clarity.threshold", "0.8")
    assert cfg.get_key(tmp_path, "clarity.threshold") == 0.8


def test_set_bool(tmp_path: Path):
    cfg.save(tmp_path, cfg.CanonConfig())
    cfg.set_key(tmp_path, "pedia.link", "false")
    assert cfg.get_key(tmp_path, "pedia.link") is False


def test_list_keys(tmp_path: Path):
    cfg.save(tmp_path, cfg.CanonConfig())
    keys = cfg.list_keys(tmp_path)
    k_names = [k.split("=")[0] for k in keys]
    assert "clarity.threshold" in k_names
    assert "agent.default" in k_names


def test_find_root_walks_up(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (tmp_path / ".canon").mkdir()
    cfg.save(tmp_path, cfg.CanonConfig())
    found = cfg.find_root(nested)
    assert found == tmp_path
