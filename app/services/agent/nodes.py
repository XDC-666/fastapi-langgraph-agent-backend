"""Agent 图节点：agent（大模型决策）与 tools（执行工具）。

注意：ChatOpenAI 实例采用「懒加载」——只在第一次调用对话时才创建，
避免在没配置 OPENAI_API_KEY 时（例如运行测试、查看 /docs）就崩溃。
"""
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.services.agent.tools import calculator, search_web

# Agent 可用工具列表
TOOLS = [calculator, search_web]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

# 懒加载缓存
_llm_with_tools = None


def get_llm_with_tools():
    """延迟创建并缓存绑定了工具的 ChatOpenAI 实例。"""
    global _llm_with_tools
    if _llm_with_tools is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "未配置 OPENAI_API_KEY，请在 .env 中填入大模型 API Key"
            )
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0,
            streaming=True,
        )
        _llm_with_tools = llm.bind_tools(TOOLS)
    return _llm_with_tools


async def agent_node(state):
    """agent 节点：把当前消息列表交给大模型，得到下一条消息（可能含工具调用）。

    使用异步调用（ainvoke），让上层 `astream(stream_mode="messages")`
    能通过回调捕获到 token 级别的增量，实现真正的逐字流式输出。
    """
    response = await get_llm_with_tools().ainvoke(state["messages"])
    return {"messages": [response]}


def tools_node(state):
    """tools 节点：执行上一条 assistant 消息中声明的工具调用，返回 ToolMessage。"""
    new_messages = []
    last_message = state["messages"][-1]
    for tool_call in last_message.tool_calls:
        tool = TOOLS_BY_NAME[tool_call["name"]]
        result = tool.invoke(tool_call["args"])
        new_messages.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"])
        )
    return {"messages": new_messages}
