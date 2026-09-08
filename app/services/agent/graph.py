"""构建 LangGraph 工作流。

流程：
  ┌─────────┐
  │  start  │
  └────┬────┘
       ▼
   ┌────────┐   有 tool_calls   ┌────────┐
   │ agent  │ ───────────────► │ tools  │
   └────┬────┘                  └────┬────┘
        │ 无 tool_calls               │
        ▼                            │
      (END) ◄────────────────────────┘
"""
from langgraph.graph import END, StateGraph

from app.services.agent.nodes import agent_node, tools_node
from app.services.agent.state import AgentState


def should_continue(state) -> str:
    """条件边：最后一条消息若含工具调用则走向 tools，否则结束。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def build_graph(checkpointer=None):
    """编译并返回 Agent 图（Runnable）。

    checkpointer 提供跨轮 / 跨工具调用的状态保存；不传则为无状态图。
    """
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)
