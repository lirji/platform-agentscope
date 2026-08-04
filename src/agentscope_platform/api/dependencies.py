import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from agentscope_platform.application.confirmation import ToolConfirmationError
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.security.internal_jwt import (
    InternalAuthenticationError,
)

CONFIRMED_TOOLS_HEADER = "X-Agent-Confirmed-Tools"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_CONFIRMATION_HEADER_TOKENS = 16


def _confirmation_tokens(request: Request) -> tuple[str, ...]:
    if request.headers.get(CONFIRMED_TOOLS_HEADER):
        raise HTTPException(
            status_code=400,
            detail="legacy tool-name confirmation is not supported",
        )
    configured_header = request.app.state.container.settings.agent_confirmation_header
    raw = request.headers.get(configured_header, "")
    if not raw.strip():
        return ()
    if len(raw) > 32_768:
        raise HTTPException(status_code=400, detail="invalid tool confirmation grant")
    values = tuple(item.strip() for item in raw.split(","))
    if len(values) > _MAX_CONFIRMATION_HEADER_TOKENS or any(not value for value in values):
        raise HTTPException(status_code=400, detail="invalid tool confirmation grant")
    return values


def _idempotency_key(request: Request) -> str | None:
    raw = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise HTTPException(status_code=400, detail="invalid idempotency key")
    return value


def get_run_context(request: Request) -> RunContext:
    container = request.app.state.container
    settings = container.settings
    raw_token = request.headers.get(settings.internal_jwt_header)

    if raw_token:
        try:
            verified = container.jwt_verifier.verify_with_expiry(raw_token)
            identity = verified.identity
            token_expires_at = verified.expires_at
        except InternalAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid internal authentication is required",
            ) from exc
    elif settings.internal_auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid internal authentication is required",
        )
    else:
        identity = TenantIdentity(
            tenant_id="anonymous",
            user_id="anonymous",
        )
        token_expires_at = None

    idempotency_key = _idempotency_key(request)
    try:
        confirmation_grants = container.confirmation_service.verify_tokens(
            _confirmation_tokens(request),
            identity,
            idempotency_key,
        )
    except ToolConfirmationError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid tool confirmation grant",
        ) from exc

    return RunContext(
        identity=identity,
        internal_token=raw_token,
        trace_id=request.state.trace_id,
        token_expires_at=token_expires_at,
        confirmation_grants=confirmation_grants,
        idempotency_key=idempotency_key,
    )


RunContextDependency = Annotated[RunContext, Depends(get_run_context)]
