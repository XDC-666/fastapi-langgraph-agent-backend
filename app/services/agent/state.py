"""Agent 状态定义。

LangGraph 通过 TypedDict + add_messages 注解来管理对话消息列表，
add_messages 会在节点之间自动追加消息，而不是覆盖。
"""
from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Agent 在图执行过程中的共享状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
