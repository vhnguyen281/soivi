"""Maps source.adapter_name -> adapter class.

Adapters register themselves with @register. load_adapters() imports every
module under pipeline/adapters/ so their decorators run.
"""

import importlib
import pkgutil

from pipeline.adapters.base import BaseAdapter

_REGISTRY: dict[str, type[BaseAdapter]] = {}


class UnknownAdapter(KeyError):
    pass


def register[A: type[BaseAdapter]](cls: A) -> A:
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} has no `name`")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(f"adapter name {name!r} is used by {existing.__name__} and {cls.__name__}")
    _REGISTRY[name] = cls
    return cls


def unregister(name: str) -> None:
    """For tests."""
    _REGISTRY.pop(name, None)


def get_adapter(name: str) -> type[BaseAdapter]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownAdapter(f"no adapter registered as {name!r}") from None


def all_adapters() -> dict[str, type[BaseAdapter]]:
    return dict(_REGISTRY)


def load_adapters() -> None:
    import pipeline.adapters as package

    for module in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        importlib.import_module(module.name)
