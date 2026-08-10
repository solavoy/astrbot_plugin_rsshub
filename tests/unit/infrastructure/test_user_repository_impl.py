from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.domain.entities.user import User
from astrbot_plugin_rsshub.src.infrastructure.persistence.user_repository_impl import (
    UserRepositoryImpl,
)


class _DummySession:
    def __init__(self, existing=None):
        self._existing = existing
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, user_id):
        return self._existing


class _DummyCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_save_updates_existing_without_insert(monkeypatch):
    existing = SimpleNamespace(
        id="u1",
        state=1,
        interval=-100,
        notify=-100,
        send_mode=-100,
        length_limit=-100,
        display_author=-100,
        display_via=-100,
        display_title=-100,
        display_entry_tags=-100,
        style=-100,
        display_media=-100,
        default_target_session=None,
        needs_binding_notice=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session = _DummySession(existing=existing)
    db = MagicMock()
    db.get_session.return_value = _DummyCtx(session)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.persistence.user_repository_impl.get_database",
        lambda: db,
    )

    repo = UserRepositoryImpl()
    user = User(id="u1")
    user.notify = 1

    saved = await repo.save(user)

    session.add.assert_not_called()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(existing)
    assert saved.id == "u1"
    assert saved.notify == 1
