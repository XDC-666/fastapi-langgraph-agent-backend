"""Agent 图节点：agent（大模型决策）与 tools（执行工具）。

ChatOpenAI 懒加载：首次调用时才创建，未配置 API Key 时（跑测试、看 /docs）不崩溃。
"""
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.services.agent.tools import calculator, search_web

TOOLS = [calculator, search_web]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}

_llm_with_tools = None


def get_llm_with_tools():
    """延迟创建并缓存绑定了工具的 ChatOpenAI 实例。"""
    global _llm_with_tools
    if _llm_with_tools is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("未配置 OPENAI_API_KEY，请在 .env 中填入大模型 API Key")
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
    """agent 节点：把消息列表交给大模型，得到下一条消息（可能含工具调用）。"""
    response = await get_llm_with_tools().ainvoke(state["messages"])
    return {"messages": [response]}


def tools_node(state):
    """tools 节点：执行上条消息声明的工具调用，返回 ToolMessage。"""
    last_message = state["messages"][-1]
    return {
        "messages": [
            ToolMessage(
                content=str(TOOLS_BY_NAME[call["name"]].invoke(call["args"])),
                tool_call_id=call["id"],
            )
            for call in last_message.tool_calls
        ]
    }
