"""Agent 状态：add_messages 让消息在节点之间追加而非覆盖。"""
from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """图执行过程中的共享状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
