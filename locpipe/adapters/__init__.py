"""Project-selected I/O adapters; importing an adapter never touches a game."""
from importlib import import_module
import re

from ..config import HarnessError


def get_adapter(cfg):
    name = cfg.values.get("adapter", {}).get("type", "json")
    if name in {"json", "unreal"}:
        module = f"locpipe.adapters.{name}"
    elif name == "custom":
        module = cfg.values["adapter"].get("module", "")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", module):
            raise HarnessError("A custom adapter requires an explicit trusted Python module")
    else:
        raise HarnessError(f"Unsupported adapter {name!r}; choose json, unreal or custom")
    try:
        adapter = import_module(module)
    except ImportError as exc:
        raise HarnessError(f"Cannot import configured adapter {module}: {exc}") from exc
    required = ("doctor", "capture", "index_context", "roundtrip", "build", "verify",
                "fonts", "discover", "install", "restore")
    if any(not callable(getattr(adapter, method, None)) for method in required):
        raise HarnessError("Adapter does not implement the complete documented interface")
    if getattr(adapter, "INPUT_MODE", None) not in {"source-file", "game-root"}:
        raise HarnessError("Adapter must declare source-file or game-root INPUT_MODE")
    return adapter
