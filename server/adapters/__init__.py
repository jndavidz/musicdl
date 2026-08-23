'''adapters package: source-keyed musicdl client wrappers'''
from .base import SourceAdapter, AdapterError
from .kuwo import KuwoAdapter
from .qq import QQAdapter
from .qianqian import QianqianAdapter
from .migu import MiguAdapter
from .netease import NeteaseAdapter
from .kugou import KugouAdapter
from .deezer import DeezerAdapter

# deezer adapter kept as experimental: its third-party resolver sites are currently
# unreachable (2026-08-23) and the official stream is encrypted — see docs/API-REFERENCE.md
# To re-enable: add 'deezer': DeezerAdapter back and append 'deezer' to config.SOURCES.
ADAPTER_CLASSES = {'kuwo': KuwoAdapter, 'qq': QQAdapter, 'qianqian': QianqianAdapter, 'migu': MiguAdapter, 'netease': NeteaseAdapter, 'kugou': KugouAdapter}

__all__ = ['SourceAdapter', 'AdapterError', 'KuwoAdapter', 'QQAdapter', 'QianqianAdapter', 'MiguAdapter', 'DeezerAdapter', 'ADAPTER_CLASSES']
