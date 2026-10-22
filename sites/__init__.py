"""사이트 레지스트리. 새 사이트는 모듈을 만들고 _REGISTRY 에 한 줄 추가하면 된다."""
from __future__ import annotations

from config import Settings
from sites.base import Site

_REGISTRY = {
    "nol": "sites.nol:NolSite",
}


def get_site(name: str, settings: Settings) -> Site:
    try:
        module_name, cls_name = _REGISTRY[name].split(":")
    except KeyError:
        raise ValueError(f"지원하지 않는 사이트입니다: {name} (가능: {', '.join(_REGISTRY)})") from None
    module = __import__(module_name, fromlist=[cls_name])
    return getattr(module, cls_name)(settings)
