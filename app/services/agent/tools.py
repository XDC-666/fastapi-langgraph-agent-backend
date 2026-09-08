"""Agent 可调用工具。

工具是 Agent 的「能力扩展」：模型在需要时决定调用哪个工具，并把结果回填给模型。
这里给出两个最小示例（计算器、模拟搜索），真实项目可替换为 SerpAPI / 业务 API。
"""
import ast
import operator

from langchain_core.tools import tool

# 仅允许基础算术运算，杜绝任意代码执行（不使用 eval）
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
# 指数上限，防止 2**99999999 之类的指数爆炸导致 CPU / 内存耗尽（DoS）
_MAX_EXP = 1000
_MAX_BASE = 1_000_000


def _safe_eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("仅支持数字常量")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise ValueError("不支持的运算符")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if op_type is ast.Pow:
            if abs(right) > _MAX_EXP or abs(left) > _MAX_BASE:
                raise ValueError("指数或底数过大，已拒绝计算")
        if op_type in (ast.Div, ast.Mod, ast.FloorDiv) and right == 0:
            raise ValueError("除数不能为零")
        return _ALLOWED_BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _ALLOWED_UNARYOPS:
            raise ValueError("不支持的一元运算符")
        return _ALLOWED_UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("表达式包含非法结构")


@tool
def calculator(expression: str) -> str:
    """对数学表达式求值，例如 '1 + 2 * 3'。

    仅支持数字与 + - * / ( ) ^ 运算符，使用 AST 安全求值（无 eval / exec）。
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
        return f"计算结果：{result}"
    except SyntaxError:
        return "表达式格式不合法，仅支持数字与 + - * / ( ) ^ 运算符"
    except Exception as exc:  # noqa: BLE001
        return f"计算失败：{exc}"


@tool
def search_web(query: str) -> str:
    """模拟网络搜索，返回与查询相关的摘要文本。

    真实项目可接入 DuckDuckGo / SerpAPI / Bing 等搜索服务。
    """
    return (
        f"（模拟搜索结果）关于「{query}」的搜索摘要："
        "这里是占位内容，正式环境请替换为真实搜索 API 返回的结果。"
    )
