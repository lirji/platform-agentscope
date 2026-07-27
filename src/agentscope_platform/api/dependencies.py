from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.security.internal_jwt import (
    InternalAuthenticationError,
)


def get_run_context(request: Request) -> RunContext:
    container = request.app.state.container
    settings = container.settings
    raw_token = request.headers.get(settings.internal_jwt_header)

    if raw_token:
        try:
            identity = container.jwt_verifier.verify(raw_token)
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

    return RunContext(
        identity=identity,
        internal_token=raw_token,
        trace_id=request.state.trace_id,
    )


RunContextDependency = Annotated[RunContext, Depends(get_run_context)]
