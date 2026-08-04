import asyncio
import math
from datetime import UTC, datetime

from redis.asyncio import Redis

from agentscope_platform.application.ports import AgentSessionStore
from agentscope_platform.domain.session import AgentSessionCheckpoint

_CAS_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local expected = ARGV[1]
if expected == '' then
  if current then return 0 end
else
  if not current then return 0 end
  local decoded = cjson.decode(current)
  if tostring(decoded.revision) ~= expected then return 0 end
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
""".strip()


class InMemoryAgentSessionStore(AgentSessionStore):
    def __init__(self) -> None:
        self._values: dict[str, AgentSessionCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> AgentSessionCheckpoint | None:
        async with self._lock:
            value = self._values.get(session_id)
            if value is not None and value.expires_at <= datetime.now(UTC):
                self._values.pop(session_id, None)
                return None
            return value.model_copy(deep=True) if value is not None else None

    async def compare_and_set(
        self,
        checkpoint: AgentSessionCheckpoint,
        expected_revision: int | None,
    ) -> bool:
        async with self._lock:
            current = self._values.get(checkpoint.session_id)
            if expected_revision is None:
                if current is not None:
                    return False
            elif current is None or current.revision != expected_revision:
                return False
            self._values[checkpoint.session_id] = checkpoint.model_copy(deep=True)
            return True

    async def ready(self, timeout_seconds: float) -> bool:
        del timeout_seconds
        return True

    async def close(self) -> None:
        self._values.clear()


class RedisAgentSessionStore(AgentSessionStore):
    def __init__(self, redis_url: str, namespace: str) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._namespace = namespace

    def _key(self, session_id: str) -> str:
        return f"{self._namespace}:{session_id}"

    async def get(self, session_id: str) -> AgentSessionCheckpoint | None:
        value = await self._client.get(self._key(session_id))
        if value is None:
            return None
        return AgentSessionCheckpoint.model_validate_json(value)

    async def compare_and_set(
        self,
        checkpoint: AgentSessionCheckpoint,
        expected_revision: int | None,
    ) -> bool:
        ttl = math.ceil((checkpoint.expires_at - datetime.now(UTC)).total_seconds())
        if ttl <= 0:
            return False
        result = await self._client.eval(
            _CAS_SCRIPT,
            1,
            self._key(checkpoint.session_id),
            "" if expected_revision is None else str(expected_revision),
            checkpoint.model_dump_json(by_alias=True),
            str(ttl),
        )
        return bool(result)

    async def ready(self, timeout_seconds: float) -> bool:
        try:
            return bool(await asyncio.wait_for(self._client.ping(), timeout_seconds))
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()


def build_agent_session_store(
    *,
    kind: str,
    redis_url: str,
    namespace: str,
) -> AgentSessionStore:
    if kind == "redis":
        return RedisAgentSessionStore(redis_url, namespace)
    return InMemoryAgentSessionStore()
