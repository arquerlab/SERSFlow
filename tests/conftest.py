from __future__ import annotations

import pytest

TEST_OWNER = "dev"


@pytest.fixture(autouse=True)
def auth_disabled_unless_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("auth"):
        return
    monkeypatch.setenv("SERSFLOW_AUTH_DISABLED", "1")


@pytest.fixture
def owner_user_id() -> str:
    return TEST_OWNER
