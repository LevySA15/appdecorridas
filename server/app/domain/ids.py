from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Identificador curto e único, por exemplo `ride-3f9a1c0b7d2e4a5f` (cabe nas colunas de 40 letras)."""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
