"""Caches that live only for one read-only derivation (a work view, a readiness check).

r5d21: one work view of the B0GLNPC6K8 run validated the same supplement 788 times - every retained path resolved and
every retained file hashed again each time - and re-checked the specialty event chain 171,808 times; deriving the view
took most of the 15-40 s every pipeline step spent before it did anything. Inside one derivation no file and no task
record changes, so each is checked once there. Outside a derivation (a dispatch, a recorder) nothing is cached: file
verification is never carried from one dispatch to the next. ``LC_IPR_DERIVATION_MEMO=0`` turns the caches off.
"""
from __future__ import annotations

from contextlib import contextmanager
import os

_DEPTH = 0
_CACHES: dict = {}
LIMIT = 50000


@contextmanager
def active():
    """Open (or join) the derivation scope; the caches are dropped when the outermost scope ends."""
    global _DEPTH
    _DEPTH += 1
    try:
        yield
    finally:
        _DEPTH -= 1
        if _DEPTH == 0:
            _CACHES.clear()


def enabled() -> bool:
    return _DEPTH > 0 and os.environ.get('LC_IPR_DERIVATION_MEMO') != '0'


def cache(name: str):
    """The named cache of the current derivation, or None outside one."""
    if not enabled():
        return None
    table = _CACHES.setdefault(name, {})
    if len(table) >= LIMIT:
        table.clear()
    return table


def chain_key(task, rows):
    """Identity of an append-only event chain inside one derivation: the same list object, length and last row."""
    return (id(task), id(rows), len(rows), id(rows[-1]) if rows else None)
