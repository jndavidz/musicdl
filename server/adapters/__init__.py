'''adapters package: source-keyed musicdl client wrappers'''
from .base import SourceAdapter, AdapterError
from .kuwo import KuwoAdapter
from .qq import QQAdapter
from .qianqian import QianqianAdapter
from .migu import MiguAdapter

ADAPTER_CLASSES = {'kuwo': KuwoAdapter, 'qq': QQAdapter, 'qianqian': QianqianAdapter, 'migu': MiguAdapter}

__all__ = ['SourceAdapter', 'AdapterError', 'KuwoAdapter', 'QQAdapter', 'QianqianAdapter', 'MiguAdapter', 'ADAPTER_CLASSES']
