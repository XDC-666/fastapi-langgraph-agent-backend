"""构建 LangGraph 工作流。

  ┌────────┐   有 tool_calls   ┌────────┐
  │ agent  │ ───────────────► │ tools  │
  └────┬───┘                  └────┬───┘
       │ 无 tool_calls              │
       ▼                           │
     (END) ◄──────────────────────┘
"""
from langgraph.graph import END, StateGraph

from app.services.agent.nodes import agent_node, tools_node
from app.services.agent.state import AgentState


def should_continue(state) -> str:
    """最后一条消息含工具调用则走向 tools，否则结束。"""
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tools"
    return END


def build_graph(checkpointer=None):
    """编译并返回 Agent 图；checkpointer 用于跨轮保存状态，不传则为无状态图。"""
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)
