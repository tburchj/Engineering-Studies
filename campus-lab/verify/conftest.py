"""Load the rendered campus snapshot into Batfish once per test session."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pybatfish.client.session import Session

SNAPSHOT = Path(__file__).resolve().parents[1] / "build"


@pytest.fixture(scope="session")
def bf() -> Session:
    if not (SNAPSHOT / "configs").is_dir():
        pytest.fail(
            "build/configs is missing — run "
            "'ansible-playbook -i design/inventory.yml design/render.yml' first"
        )
    session = Session(host=os.environ.get("BATFISH_HOST", "localhost"))
    session.set_network("campus")
    session.init_snapshot(str(SNAPSHOT), name="campus", overwrite=True)
    return session
