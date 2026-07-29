from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Current UTC time as a naive datetime.

    The database stores naive UTC timestamps, so all application code compares
    against naive values. This is the drop-in replacement for the deprecated
    ``datetime.utcnow()`` and keeps every comparison on the same (naive) basis.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
