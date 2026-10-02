"""显式启动本模块只提供无状态shadow候选, 与Agent线上进程隔离."""

from agentscope_platform.api.conversation_app import create_conversation_app

app = create_conversation_app()
