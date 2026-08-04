import json
from datetime import UTC, datetime, timedelta

from agentscope_platform.domain.session import (
    AgentSessionCheckpoint,
    AgentSessionStatus,
    goal_sha256,
)
from agentscope_platform.infrastructure.persistence.agent_session import (
    InMemoryAgentSessionStore,
    RedisAgentSessionStore,
)


def checkpoint(revision: int = 0) -> AgentSessionCheckpoint:
    now = datetime.now(UTC)
    return AgentSessionCheckpoint(
        sessionId="sess-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        revision=revision,
        tenantId="acme",
        userId="alice",
        goalSha256=goal_sha256("goal"),
        status=AgentSessionStatus.READY,
        createdAt=now,
        updatedAt=now,
        expiresAt=now + timedelta(hours=1),
    )


async def test_memory_store_compare_and_set_prevents_lost_updates() -> None:
    store = InMemoryAgentSessionStore()

    assert await store.compare_and_set(checkpoint(), expected_revision=None)
    assert not await store.compare_and_set(checkpoint(), expected_revision=None)
    assert not await store.compare_and_set(checkpoint(2), expected_revision=1)
    assert await store.compare_and_set(checkpoint(1), expected_revision=0)
    assert (await store.get(checkpoint().session_id)).revision == 1  # type: ignore[union-attr]


async def test_memory_store_discards_expired_records() -> None:
    store = InMemoryAgentSessionStore()
    value = checkpoint().model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    assert await store.compare_and_set(value, expected_revision=None)

    assert await store.get(value.session_id) is None


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def eval(self, script: str, key_count: int, key: str, *args: str) -> int:
        del script
        assert key_count == 1
        expected, payload, ttl = args
        assert int(ttl) > 0
        current = self.values.get(key)
        if expected == "":
            if current is not None:
                return 0
        elif current is None or str(json.loads(current)["revision"]) != expected:
            return 0
        self.values[key] = payload
        return 1

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


async def test_redis_store_uses_atomic_revision_compare_and_set() -> None:
    store = RedisAgentSessionStore("redis://localhost/0", "test:session")
    fake = FakeRedis()
    store._client = fake  # type: ignore[assignment]

    assert await store.compare_and_set(checkpoint(), expected_revision=None)
    assert not await store.compare_and_set(checkpoint(2), expected_revision=1)
    assert await store.compare_and_set(checkpoint(1), expected_revision=0)
    loaded = await store.get(checkpoint().session_id)

    assert loaded is not None
    assert loaded.revision == 1
    assert await store.ready(0.1)
