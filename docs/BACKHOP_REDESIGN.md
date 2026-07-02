# Agent 回跳机制优化目标框架

> **文档目的**：记录当前 agent graph 回跳（back-hop）机制的结构性缺陷，并定义优化后的**理想目标框架**。这是后续实现的设计依据，不是实现本身。
> **关联**：补充 `agent_test/DIAGNOSTICS.md`（诊断报告）中"根因 B/F + `Command(goto=)` 双时间线"部分。
> **状态**：设计目标，待评审。

---

## 一、当前问题（为什么要改）

### 问题本质：`Command(goto=)` 回跳会产生两条并发时间线

当前 agent graph 用 `Command(goto=<上游phase>)` 实现"飞行中回跳"——某个 phase（如 surface）发现它引用的上游对象（如 Zone）不存在时，立即跳回上游 phase 重建。

**致命缺陷**：LangGraph 1.x 的 `Command(goto=)` 在节点**同时拥有静态出边**（`add_edge("surface","fenestration")`）时，会把"回跳目标"和"静态出边的下游"**一起加入调度队列，并发执行**，而不是"跳过去执行完再回来"。

经最小复现实验确认（LangGraph 1.1.8），当 surface 回跳到 zone 时，实际执行顺序是：

```
... → construction → surface → [发出 Command(goto="zone")]
                                    │
                    ┌───────────────┴────────────────┐
                    ▼                                  ▼
          时间线A（回跳链）                   时间线B（下游直冲链）
          zone(重建)                          fenestration（surface 的下游）
          → construction                      → hvac
          → surface(重建)                     → validate
                                             → simulate  ★ 抢跑！
```

- **时间线 A**（回跳链）：zone → construction → surface（重建缺失对象）
- **时间线 B**（下游直冲链）：fenestration → hvac → validate → simulate

时间线 B 永远比 A 先到达 simulate（因为 A 要重建最耗时的 surface 几何），所以 **simulate 必然抢在 surface 重建前跑，必然用残缺（0-surface）的中间状态 IDF**，必然 Fatal 或假阳性。

### 问题在 case_02 的具体表现

| 时间 | 事件 | 属于哪条时间线 |
|------|------|--------------|
| 15:01:33 | surface back-hop → zone（surface 0 创建） | 触发点 |
| 15:01:34 | zone `list_zones`（重跑） | 时间线 A |
| 15:01:35 | fenestration `list_surfaces`（返回空） | **时间线 B**（与 zone 并发，仅差 0.3 秒） |
| 15:02:47 | hvac/people/lights | 时间线 B 继续下冲 |
| **15:03:13** | **simulate**（用 0-surface IDF 跑 EnergyPlus） | **时间线 B 冲到终点** |
| 15:04:50 | surface 第二轮 `create_surface`（真正重建） | 时间线 A 迟到的重建 |

### 为什么不能简单删静态出边

方案 B（删掉 `add_edge`、全靠 `Command(goto=)` 控制下游）虽能消除双时间线，但经实验验证引入了**更严重的隐形问题**：

1. **graph 可视化失真**：`get_graph().edges` 把 `surface` 误显示为直接 `→ __end__`，看不到 `surface→fenestration` 的连接。任何基于拓扑的分析工具（LangSmith 追踪、文档生成）都会被骗。
2. **节点名拼错静默失败**：`Command(goto='fenstraiton')`（拼错）只打印一行 warning 后静默忽略，不抛异常，fenestration 永不执行。
3. **漏写 Command 分支静默跳过 phase**（最危险）：若某 if 分支忘了返回 Command 而返回普通 dict，且无静态出边，**fenestration 会静默消失，无任何报错**——可能制造出和 case_01/case_02 同类的新"静默失败"。
4. **编译期无法发现死路**：静态边模式下"无出边且不到 END"编译报错；Command 模式下死路只能运行时暴露。

**结论：`Command(goto=)` 这个原语不适合做"飞行中回跳"。** 它的设计用途是"末端路由"（像 validate 那样在 pipeline 末端、无下游冲突地路由），不是"中途打断重来"。把 graph 从"显式拓扑、编译期可校验"变成"隐式拓扑、运行期才暴露问题"是维护灾难。

### 当前回跳机制的其它缺陷（已在 DIAGNOSTICS.md 详述）

- **根因 F**：phase-3 节点（hvac/people/lights）曾漏接 `maybe_backhop` 执行层（已在 commit `60e74a2` 修复），导致检测到的缺失被丢弃。
- **根因 B**：surface 的回跳判定过激——一次 `create_surface` 都没调用就因 zone 名不匹配而 back-hop。
- **回跳自动触发**：工具一旦发现 `missing_ref`，`detect_upstream_gap` 立即在 `invoke_with_self_repair` 里短路回跳（`_share.py:298-305`），**根本不让 phase 的 LLM 看到错误、自己尝试解决**（比如用别的现有对象替代）。

---

## 二、目标框架（理想态）

### 设计原则

1. **单时间线原则**：整个 agent graph 的执行永远只有一条时间线，由静态边（`add_edge`）驱动。**任何 phase 节点都不主动发 `Command(goto=<上游phase>)`**——回跳控制权统一收敛到 barrier/validate 节点，避免并发直冲。
2. **显式拓扑原则**：所有节点连接用静态边声明，graph 拓扑在编译期可校验、可视化准确，杜绝隐式控制流。
3. **LLM 优先自愈原则**：工具发现缺失依赖时，错误信息先回到该 phase 的 LLM，让 LLM 自己尝试解决（用现有对象替代、调整引用等）；只有 LLM 确认无法解决时，才主动调用"回跳请求"工具。
4. **并行分支完整执行原则**：phase-3（hvac/people/lights）三个并行节点**必须全部执行完毕**才决定是否回跳——一个节点的缺失请求不能中断另两个正常节点的执行。回跳决策在 barrier（`cross_ref_complete`）汇聚后统一做出。
5. **回跳目标最早原则**：当多个 phase 同时被请求回跳（目的地分散），统一回退到 `PIPELINE_ORDER` 中**最早**的目标 phase，从那里往下顺跑，避免多条回跳链。

### 目标拓扑

```
                         START
                           │
                     intake / revise
                           │ (fan-out)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
            zone       material      schedule        【phase-1 并行】
              └────────────┼────────────┘
                        barrier
                           ▼
                  cross_ref_foundations
                           │
                  construction → surface → fenestration   【phase-2 串行】
                           │ (fan-out)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
            hvac        people        lights          【phase-3 并行】
              └────────────┼────────────┘
                        barrier
                           ▼
                  cross_ref_complete  ← ★ 回跳决策点（统一汇聚）
                           │
                  ┌────────┴────────────────────┐
            (有回跳请求)                    (无回跳请求)
                  ▼                            ▼
        取最早回跳目标                  validate（正常路径）
        Command(goto=<最早phase>)
                  │               (此处 Command 安全：barrier 无下游并发冲突，
                  ▼                且目标 phase 之后的连接仍由静态边驱动)
          重跑目标 phase
          → 静态边自然往下顺跑
```

**关键变化**：`Command(goto=)` 只在 `cross_ref_complete`（barrier 之后、无下游并发）使用，**所有 phase 节点（construction/surface/fenestration/hvac/people/lights）都不再发 Command 回跳**。这样彻底消除双时间线。

### 回跳的触发与流转（目标态）

#### 第 1 步：工具不再自动触发回跳，改为返回错误给 LLM

**移除** `invoke_with_self_repair` 里的 `detect_upstream_gap` 自动短路（`_share.py:298-305`）。

工具发现引用的对象不存在时（如 `create_surface` 发现 `zone_name` 不存在），**仍然返回带 `missing_ref` 的错误 JSON**（保留这个信息），但这个错误：
- 先作为 `ToolMessage` 回到该 phase 的 ReAct LLM
- LLM 看到错误后**先自己尝试解决**：可能用 list_* 发现别的可用对象替代，或调整自己的引用
- 只有 LLM **确认确实需要上游创建该对象**时，才主动调用下面的"回跳请求"工具

#### 第 2 步：新增 `request_backhop` 工具（LLM 主动调用）

每个会引用上游对象的 phase（construction/surface/fenestration/hvac/people/lights）的工具集里，新增一个**回跳请求工具**：

```python
@tool
def request_backhop(missing_ref: str, missing_name: str, reason: str) -> str:
    """确认需要上游 phase 创建缺失的对象后调用此工具。

    Args:
        missing_ref: 缺失对象类型（如 'Zone'、'Schedule:Compact'、'Material'）
        missing_name: 缺失对象名称
        reason: 为什么需要回跳（LLM 说明自己已尝试但无法替代）

    调用后，本 phase 会把回跳请求记录到共享状态，由后续 barrier 节点统一处理。
    本 phase 自身可以继续完成其它能做的工作，或停止。
    """
```

LLM 调用此工具 = "我确认这个对象必须由上游创建，我无法自行解决"。工具把请求写入 `state.upstream_request`（沿用现有字段，但语义从"立即回跳指令"变为"待处理的回跳请求"）。

#### 第 3 步：串行节点（phase-2）的回跳流转

phase-2 是严格串行（construction → surface → fenestration）。当某个节点（如 surface）的 LLM 调了 `request_backhop`：
- 该节点把请求写入 state，**正常返回**（不发 Command）
- 因为是串行，下游节点（fenestration）会**检测到 `state.upstream_request` 存在**，并**主动跳过自身执行**（既然上游要重做，自己跑了也白跑）——直接 pass-through，把请求继续往下游传递
- 请求最终到达 `cross_ref_complete`（phase-3 的 barrier，也是全 pipeline 的末端汇聚点），在那里统一处理

#### 第 4 步：并行节点（phase-3）的回跳合并

phase-3 是 hvac/people/lights 三路并行。每个节点独立判断是否需要回跳：
- hvac 调 `request_backhop(missing_ref='Zone', missing_name='Office_North')`
- people 调 `request_backhop(missing_ref='Schedule:Compact', missing_name='Occ_Sched')`
- lights 正常完成，无回跳请求

三个节点的回跳请求（如果有）通过 `_merge_upstream_request` reducer（"非 None 请求获胜"）**合并到 state**。**三个节点都执行完毕后**，才在 `cross_ref_complete` 汇聚点统一处理——不会出现"一个节点回跳、另两个没跑完就被终止"的问题。

#### 第 5 步：`cross_ref_complete` 统一回跳决策（核心汇聚点）

`cross_ref_complete` 改造为**回跳决策节点**（不再只是 pass-through 校验）：

1. 检查 `state.upstream_request` 是否含回跳请求
2. **若无请求** → 正常走 `validate`（静态边）
3. **若有请求**：
   - 收集所有回跳请求（可能多个 phase 各自请求了不同目标）
   - 用 `earliest_phase()`（现有逻辑，`_share.py:145-150`）取 `PIPELINE_ORDER` 中**最早**的目标 phase
   - 检查 `hop_count < HOP_LIMIT`（防止死循环）
   - 发 `Command(goto=<最早目标phase>, update={upstream_request, hop_count+1, is_revision=True})`
   - **此处 Command 安全**：`cross_ref_complete` 是 barrier 之后节点，其下游只有 `validate`，而回跳时不走 validate（走 goto），不存在"下游直冲"的并发冲突

#### 第 6 步：回跳目标 phase 接收请求并顺跑

回跳目标 phase（如 zone）通过现有的 inbound 消费块读取 `state.upstream_request`，把请求 spec 追加到自己的 specs，重做创建工作。完成后，**静态边自然驱动它往下顺跑**（zone → cross_ref_foundations → construction → surface → ... → cross_ref_complete），无需任何 Command。这样保证单时间线。

### 目标态 vs 当前态对比

| 维度 | 当前态 | 目标态 |
|------|--------|--------|
| 回跳触发 | 工具发现 `missing_ref` → 自动短路回跳 | 工具返回错误 → LLM 自愈尝试 → LLM 确认后主动调 `request_backhop` |
| 回跳发起节点 | construction/surface/fenestration/hvac/people/lights（各自发 Command） | **无 phase 节点发 Command 回跳**；统一由 `cross_ref_complete` 发 |
| 时间线 | 双时间线（回跳链 + 下游直冲链并发） | **单时间线**（静态边驱动） |
| phase-3 并行回跳 | 一个回跳可能中断另两个（双时间线） | 三节点全部完成后在 barrier 统一决策 |
| 多目标回跳 | 各自 Command，可能多条回跳链 | 取最早目标，单一回跳链 |
| graph 拓扑 | 静态边 + Command 隐式跳转混合 | **纯静态边**（Command 只在 barrier 后、无并发冲突处使用） |
| LLM 自愈能力 | 无（自动回跳，LLM 看不到错误） | 有（错误先回 LLM，能替代则替代） |

### 目标态下的 case_02 场景重演（验证设计）

假设 surface 发现引用的 `Private_Office_1` zone 不存在：

1. `create_surface` 返回错误（`missing_ref='Zone'`）给 surface 的 LLM
2. surface LLM 检查 `list_zones`，确认确实没有 `Private_Office_1`，无法替代 → 调用 `request_backhop('Zone', 'Private_Office_1', 'spec 要求但未创建')`
3. surface 把请求写入 state，正常返回（**不发 Command**）
4. fenestration 检测到 `upstream_request` 存在 → **跳过自身**（pass-through），把请求继续传
5. phase-3 的 hvac/people/lights **全部正常执行完毕**（它们的 zone 引用可能也有问题，各自也可能调 request_backhop，但都先跑完）
6. `cross_ref_complete` 汇聚：发现有回跳请求（zone 缺失）→ `earliest_phase()` = zone → `Command(goto="zone")`（**此时无下游并发冲突**）
7. zone 接收请求，重建 `Private_Office_1` → 静态边顺跑 → construction → surface（这次能成功创建）→ fenestration → ... → cross_ref_complete → validate → simulate
8. simulate 拿到的是**完整重建后的 IDF**，无双时间线竞态

**整个流程只有一条时间线，simulate 永远在所有重建完成后才跑。**

---

## 三、实现涉及的组件（概览，详见后续实现计划）

| 组件 | 改动方向 |
|------|---------|
| `src/agent/nodes/_share.py` | 移除 `invoke_with_self_repair` 里的 `detect_upstream_gap` 自动短路；`maybe_backhop` 从"phase 节点调用"改为"barrier 节点调用"，或新增统一的 `resolve_backhop` 函数供 `cross_ref_complete` 使用 |
| 新增 `request_backhop` 工具 | 加入 construction/surface/fenestration/hvac/people/lights 的工具集，LLM 主动调用 |
| `src/agent/nodes/cross_ref.py` | `cross_ref_complete_node` 改造为回跳决策点：检查 `upstream_request` → 取最早目标 → `Command(goto=...)` |
| 各 phase 节点 | 移除 `maybe_backhop` 调用（不再发 Command）；保留工具的 `missing_ref` 错误返回（给 LLM 看）；串行节点（fenestration）检测到 `upstream_request` 存在时跳过自身 |
| `src/agent/nodes/zone.py` 等 | inbound 消费块保留（回跳目标仍读 `upstream_request` 追加 spec） |
| `src/agent/graph.py` | 拓扑不变（仍用静态边）；确认 `cross_ref_complete` 的 Command 路由 Literal 包含所有 phase 名 |

### 待评审的开放问题

1. **串行节点检测到 `upstream_request` 时跳过自身**：需要在 fenestration（及 phase-2 节点）加"if upstream_request exists: skip"逻辑。但这会让节点行为依赖 state（非纯函数），需确认是否符合预期。
2. **回跳请求的 hop_count 限制**：现有 `HOP_LIMIT=3` 是否够用？目标态下回跳更少（LLM 自愈拦截一部分），但需验证。
3. **`request_backhop` 工具的错误处理**：LLM 可能误调（明明能替代却请求回跳）。是否需要二次校验？
4. **phase-1（zone/material/schedule）的回跳**：它们是回跳目标，但自身也可能需要回跳到 intake（ specs 不完整）——这是另一个维度，本文档暂不覆盖。

---

## 四、与已完成的 zone 校验模块的关系

commit `60e74a2` 已实现的 **zone 独立校验模块**（`zone_validator.py`）与本文档的回跳优化是**互补**关系：
- zone 校验模块解决的是"zone 静默放弃（0 zone）"问题——在 zone phase 内部用独立 LLM 校验 + 重试，不涉及跨 phase 回跳。
- 本文档的回跳优化解决的是"跨 phase 依赖缺失时的回跳竞态"问题——改造回跳机制本身。
- 两者可以共存：zone 校验模块继续在 zone phase 内部运行；回跳优化改造的是 construction/surface/fenestration/hvac/people/lights 发现缺失依赖后的处理路径。

---

## 附：关键术语

- **back-hop（回跳）**：某个 phase 发现它依赖的上游对象缺失时，请求回到上游 phase 重建该对象的机制。
- **barrier（屏障/汇聚）**：`add_edge(["a","b","c"], "join")` 语义——所有并行分支都完成后才往下走。phase-1 的 barrier 是 `cross_ref_foundations`，phase-3 的 barrier 是 `cross_ref_complete`。
- **双时间线**：当前 `Command(goto=)` 回跳时，回跳目标链与下游直冲链并发执行的现象（本文档第一节详述）。
- **directed rollback（有向回滚）**：validate 节点在 pipeline 末端统一把错误路由到最早出错 phase 的机制（`validate.py`），与"飞行中回跳"相对。
- **`PIPELINE_ORDER`**：phase 的固定顺序元组（`zone, material, schedule, construction, surface, fenestration, hvac, people, lights`），用于判断回跳目标是否在上游、以及取最早目标。
