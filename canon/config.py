"""Canon's tiny config. Lives at .canon/config.yaml.

We don't add a YAML dep. We emit a *subset* of YAML (simple key: value
lines + top-level section headers) and parse the same subset back. If
users edit the file with genuine YAML (quotes, nesting), we preserve
what we can and defer deep-YAML to a future release.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "clarity": {
        "threshold": 0.7,
        "max_iter": 5,
    },
    "agent": {
        "default": "none",            # "none" | "claude" | "codex"
        "context_dir": ".canon/interview-context",
    },
    "pedia": {
        "link": True,
    },
    "hopewell": {
        "link": False,
    },
    "decompose": {
        # Default strategy when no CLI flag, no front-matter, no smart-detect
        # match. Empty string means "fall through to smart-default".
        "strategy": "",
    },
}


@dataclass
class CanonConfig:
    version: int = 1
    clarity_threshold: float = 0.7
    clarity_max_iter: int = 5
    agent_default: str = "none"
    agent_context_dir: str = ".canon/interview-context"
    pedia_link: bool = True
    hopewell_link: bool = False
    decompose_strategy: str = ""    # 0.5.0: empty -> smart-default

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanonConfig":
        c = cls()
        c.version = int(d.get("version", c.version))
        clarity = d.get("clarity") or {}
        c.clarity_threshold = float(clarity.get("threshold", c.clarity_threshold))
        c.clarity_max_iter = int(clarity.get("max_iter", c.clarity_max_iter))
        agent = d.get("agent") or {}
        c.agent_default = str(agent.get("default", c.agent_default))
        c.agent_context_dir = str(agent.get("context_dir", c.agent_context_dir))
        pedia = d.get("pedia") or {}
        c.pedia_link = bool(pedia.get("link", c.pedia_link))
        # Accept either `taskflow:` (preferred post-rebrand) or `hopewell:`
        # (legacy) as the work-graph integration block.
        taskflow = d.get("taskflow") or {}
        hopewell = d.get("hopewell") or {}
        c.hopewell_link = bool(taskflow.get("link", hopewell.get("link", c.hopewell_link)))
        decompose = d.get("decompose") or {}
        c.decompose_strategy = str(decompose.get("strategy", c.decompose_strategy))
        return c

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "clarity": {
                "threshold": self.clarity_threshold,
                "max_iter": self.clarity_max_iter,
            },
            "agent": {
                "default": self.agent_default,
                "context_dir": self.agent_context_dir,
            },
            "pedia": {"link": self.pedia_link},
            "hopewell": {"link": self.hopewell_link},
            "decompose": {"strategy": self.decompose_strategy},
        }


def canon_dir(root: Path) -> Path:
    return root / ".canon"


def config_path(root: Path) -> Path:
    return canon_dir(root) / "config.yaml"


def find_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from `start` looking for a .canon/ directory."""
    cur = (start or Path.cwd()).resolve()
    for p in [cur] + list(cur.parents):
        if (p / ".canon").is_dir():
            return p
    return None


def load(root: Path) -> CanonConfig:
    p = config_path(root)
    if not p.exists():
        return CanonConfig()
    return CanonConfig.from_dict(_parse_simple_yaml(p.read_text(encoding="utf-8")))


def save(root: Path, cfg: CanonConfig) -> None:
    p = config_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_emit_simple_yaml(cfg.to_dict()), encoding="utf-8")


# ----- simple YAML subset ---------------------------------------------------

def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse a subset: top-level scalars + one-level nesting.

    Lines like:
        version: 1
        clarity:
          threshold: 0.7
          max_iter: 5
    """
    out: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if indent == 0:
            if val == "":
                current_section = key
                out[key] = {}
            else:
                out[key] = _coerce(val)
                current_section = None
        else:
            if current_section is None:
                out[key] = _coerce(val)
            else:
                out.setdefault(current_section, {})[key] = _coerce(val)
    return out


def _coerce(val: str) -> Any:
    if val.lower() in {"true", "yes"}:
        return True
    if val.lower() in {"false", "no"}:
        return False
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


def _emit_simple_yaml(d: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# canon config -- edit with care or use `canon config set`")
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for kk, vv in v.items():
                lines.append(f"  {kk}: {_emit_scalar(vv)}")
        else:
            lines.append(f"{k}: {_emit_scalar(v)}")
    return "\n".join(lines) + "\n"


def _emit_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ----- dotted-path get/set for `canon config` -------------------------------

DOTTED_ALIASES = {
    "clarity.threshold": ("clarity", "threshold"),
    "clarity.max_iter": ("clarity", "max_iter"),
    "agent.default": ("agent", "default"),
    "agent.context_dir": ("agent", "context_dir"),
    "pedia.link": ("pedia",),
    # Both keys point at the same underlying flag so users can refer to
    # the work-graph integration by either name during the transition.
    "taskflow.link": ("hopewell",),
    "hopewell.link": ("hopewell",),
}


def get_key(root: Path, key: str) -> Any:
    d = load(root).to_dict()
    parts = key.split(".")
    cur: Any = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def set_key(root: Path, key: str, value: str) -> None:
    cfg = load(root)
    d = cfg.to_dict()
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = _coerce(value)
    save(root, CanonConfig.from_dict(d))


def list_keys(root: Path) -> List[str]:
    out: List[str] = []
    def walk(d: Dict[str, Any], prefix: str = "") -> None:
        for k, v in d.items():
            full = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, full + ".")
            else:
                out.append(f"{full}={v}")
    walk(load(root).to_dict())
    return out
