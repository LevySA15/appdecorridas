import pytest

from simulator.sandbox import Sandbox


@pytest.fixture()
def box():
    """Um servidor de verdade (uvicorn) só para este teste, com prazos curtos, num esquema e num Redis próprios."""
    with Sandbox(fast=True, redis_db=13) as sandbox:
        yield sandbox
