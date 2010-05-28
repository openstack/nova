"""

Working with Backends.

"""
import sys

from carrot.utils import rpartition

DEFAULT_BACKEND = "carrot.backends.pyamqplib.Backend"

BACKEND_ALIASES = {
    "amqp": "carrot.backends.pyamqplib.Backend",
    "amqplib": "carrot.backends.pyamqplib.Backend",
    "stomp": "carrot.backends.pystomp.Backend",
    "stompy": "carrot.backends.pystomp.Backend",
    "memory": "carrot.backends.queue.Backend",
    "mem": "carrot.backends.queue.Backend",
    "pika": "carrot.backends.pikachu.AsyncoreBackend",
    "pikachu": "carrot.backends.pikachu.AsyncoreBackend",
    "syncpika": "carrot.backends.pikachu.SyncBackend",
}

_backend_cache = {}


def resolve_backend(backend=None):
    backend = BACKEND_ALIASES.get(backend, backend)
    backend_module_name, _, backend_cls_name = rpartition(backend, ".")
    return backend_module_name, backend_cls_name


def _get_backend_cls(backend=None):
    backend_module_name, backend_cls_name = resolve_backend(backend)
    __import__(backend_module_name)
    backend_module = sys.modules[backend_module_name]
    return getattr(backend_module, backend_cls_name)


def get_backend_cls(backend=None):
    """Get backend class by name.

    The backend string is the full path to a backend class, e.g.::

        "carrot.backends.pyamqplib.Backend"

    If the name does not include "``.``" (is not fully qualified),
    the alias table will be consulted.

    """
    backend = backend or DEFAULT_BACKEND
    if backend not in _backend_cache:
        _backend_cache[backend] = _get_backend_cls(backend)
    return _backend_cache[backend]
