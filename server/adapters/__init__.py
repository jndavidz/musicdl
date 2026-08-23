'''adapters package: source-keyed musicdl client wrappers'''
from .base import SourceAdapter, AdapterError
from .kuwo import KuwoAdapter
from .qq import QQAdapter

ADAPTER_CLASSES = {'kuwo': KuwoAdapter, 'qq': QQAdapter}

__all__ = ['SourceAdapter', 'AdapterError', 'KuwoAdapter', 'QQAdapter', 'ADAPTER_CLASSES']
