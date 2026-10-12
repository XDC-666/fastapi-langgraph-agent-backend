# AI Agent 后端服务 面试 STAR 讲稿（全部数据可复现）

> 本文所有数字均在本地实测跑出，复现命令见文末。

## 30 秒版

这是一个 FastAPI + LangGraph 的 AI Agent 后端：LangGraph 用图编排多轮对话，支持 ReAct 工具调用、RAG 知识库、SSE 流式输出、JWT 鉴权和 Docker Compose 一键部署。我在这个项目上做的最有价值的一件事，是**把「Redis 降级」从一个我以为没问题的设计里挖出了性能缺陷**：降级逻辑写对了，但建连没设超时，Redis 不可用时每个请求要挂到系统级 TCP 超时，登录接口实测 8154ms。加上 0.5 秒超时后降到 1240ms，同一套测试用例从 177.66 秒跑到 32.96 秒，快了 5.4 倍。

## STAR 主线

**Situation（情境）**
AI 后端区别于普通后端的一点：它有**辅助组件依赖**（Redis 做限流和登录失败锁定、向量库做 RAG）。这类组件的通行写法是"不可用就降级放行，别拖垮主流程"——我当时也是这么设计的，还专门写了注释。

**Task（任务）**
给项目做一轮真实验证：测试覆盖率到底多少、接口延迟到底多少、这些"我以为没问题"的降级路径在故障场景下到底表现如何。

**Action（行动）**
1. 独立虚拟环境装依赖，跑全量 pytest（不依赖 PostgreSQL / Redis / 真实大模型，测试用内存 SQLite + 假 LangGraph 图）。
2. 写基准脚本：REST 接口 P50/P95、bcrypt 认证链路、会话 CRUD、SSE 首字节与逐 token 节拍、并发吞吐。
3. 单独压 Destroyed 场景：**在无 Redis 环境下**重复请求 `/health` 和 `/auth/login`，量化降级路径的实际延迟。
4. 定位根因 → 修复 → **做阳性对照**（把修复回退，确认新写的测试真的会红，而不是写了个永远通过的测试）。
5. 补齐 HTTP 层的防护回归（原本只有单元级限流测试）。

**Result（结果，全部实测）**
见下表。

## 实测数据表

| 指标 | 数值 |
|---|---|
| 测试通过率 | 53/53（本次新增 7 条） |
| 测试覆盖率 | 82% → **85%**（868 行语句） |
| 全量测试耗时 | 修复前 177.66s → 修复后 **32.96s**（5.4×） |
| **Redis 不可用 → health** | 4071.7ms → **513.4ms** |
| **Redis 不可用 → 登录** | 8154.3ms → **1240.0ms** |
| 单次 Redis ping | 4060ms → 510ms |
| REST 接口 P50 | `/` 1.01ms、`/docs` 0.79ms、`/auth/me` 3.32ms |
| 会话 CRUD P50 | 列表 6.50ms / 详情 6.02ms / 用量 6.72ms / 新建 100.02ms |
| bcrypt | 注册单次 324.6ms（刻意的安全成本） |
| SSE 首字节 TTFB | P50 39.22ms / P95 41.30ms（假模型 20ms/token） |
| SSE token 节拍 | P50 30.95ms vs 模型侧 20ms → 框架开销约 11ms |
| 并发吞吐 | 会话列表 202 req/s（100 请求 / 20 并发） |

## 本次发现并修复的缺陷

| 缺陷 | 根因 | 修复 | 验证方式 |
|---|---|---|---|
| Redis 不可用时认证链路被拖到秒级 | `aioredis.from_url()` 未设 socket 超时，每次调用等到系统级 TCP 超时；一次登录要碰 Redis 2–3 次 | 新增 `REDIS_CONNECT_TIMEOUT_SECONDS` / `REDIS_SOCKET_TIMEOUT_SECONDS`（默认 0.5s），并 `retry_on_timeout=False` | 前后对照 + 阳性对照（回退修复后新测试转红） |

顺带补的两类验证（非缺陷，是验证缺口）：

- `tests/test_cache_timeout.py`：把超时上限钉死，防止有人改回无超时写法。
- `tests/test_protection_http.py`：原来的限流测试是**单元级**（直接调 `is_allowed`），接线断掉也测不出来。补了 HTTP 层：对话/登录超限真返回 429、`TRUST_PROXY=False` 时忽略伪造 `X-Forwarded-For`、`True` 时取最左原始 IP、跨用户访问会话返回 404（而非 403，不泄露资源存在性）。

## 可能的追问与回答

- **"限流和锁定本来就写了降级，怎么会有问题？"**
  降级保证的是**正确性**（不会因 Redis 挂了导致登录全失败），没有保证**延迟**。这两件事是独立的：语义对了，但一次调用等了几秒，用户在页面上看到的就是转圈。这个区别是这个 bug 的核心。
- **"登录修完还是 1240ms，不够理想？"**
  是的，这是保留的技术债：一次登录碰 3 次 Redis，0.5s × 3 ≈ 1.2s。彻底解决要引入短期熔断（首次失败后 N 秒内直接跳过 Redis），我没有做，因为它会改动 `lockout` / `rate_limit` 两个模块的调用方式，属于该单独评审的改动。如果需要，这是下一步。
- **"SSE 首字节 39ms 里有多少是框架，多少是模型？"**
  实验里模型是假的、固定 20ms/token：所以 TTFB 39ms 几乎全是框架路径（鉴权 + DB 加载历史 + 图准备 + 序列化）的开销；token 间隔 30.95ms 中约 11ms 是框架抖动。**真实模型的推理耗时不在这些数字里**，这点必须说清楚。
- **"并发只有 202 req/s？"**
  这是本机、单 worker、SQLite 写为主的场景；同步 ORM 已放到线程池避免阻塞事件循环，但 SQLite 本身不适合做高并发基准。生产换 PostgreSQL + 多 worker 是另一回事，我没有跑过，不报数字。

## 复现命令

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest pytest-cov httpx
python -m pytest -q --cov=app                 # 53 passed
python _fa_redis_probe.py                     # Redis 不可用时的延迟对照
python _fa_bench.py                           # 接口 / SSE / 并发基准（含假 LLM 图）
```

## 不能夸大的

1. 所有延迟是**本机回环**数字，不代表生产（真实网络、真实模型、PostgreSQL）。
2. SSE 数字用**假模型**测得，只反映框架路径开销，不含真实推理。
3. 基准环境无 Redis，因此 Redis 相关接口的数字是「降级态」的；Redis 正常时这些接口会快得多（未实测，不报）。
4. 登录 1240ms 是修了一半的结果，彻底方案（熔断）未实施，已如实列为技术债。
5. 覆盖率 85% 是行覆盖率，不等于"测到了所有行为"；`agent/graph.py`、`checkpointer.py` 仍只有 31%，依赖真实 LLM 编排的部分未被覆盖。
