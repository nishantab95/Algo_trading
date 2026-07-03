from __future__ import annotations

import uuid
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_shadow_id() -> str:
    return "shadow_" + uuid.uuid4().hex[:12]
