'''adapters package: source-keyed musicdl client wrappers.
   ADAPTER_CLASSES is the ONLY registry: config.SOURCES is derived from it.'''
from .base import SourceAdapter, AdapterError
from .kuwo import KuwoAdapter
from .qq import QQAdapter
from .qianqian import QianqianAdapter
from .migu import MiguAdapter
from .netease import NeteaseAdapter
from .kugou import KugouAdapter
from .bilibili import BilibiliAdapter
from .deezer import DeezerAdapter

# deezer adapter kept as experimental: its third-party resolver sites are currently
# unreachable (2026-08-23) and the official stream is encrypted — see docs/API-REFERENCE.md
# To re-enable: add 'deezer': DeezerAdapter to ADAPTER_CLASSES below (SOURCES derives).
# gdstudio: see adapters/gdstudio.py header (same procedure).
ADAPTER_CLASSES = {'kuwo': KuwoAdapter, 'qq': QQAdapter, 'qianqian': QianqianAdapter, 'migu': MiguAdapter, 'netease': NeteaseAdapter, 'kugou': KugouAdapter,
                                   'bilibili': BilibiliAdapter}

__all__ = ['SourceAdapter', 'AdapterError', 'KuwoAdapter', 'QQAdapter', 'QianqianAdapter', 'MiguAdapter',
           'NeteaseAdapter', 'KugouAdapter', 'BilibiliAdapter', 'DeezerAdapter', 'ADAPTER_CLASSES']
