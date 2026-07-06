# Agent 回跳机制优化目标框架

> **文档目的**：记录当前 agent graph 回跳（back-hop）机制的结构性缺陷，并定义优化后的**理想目标框架**。这是后续实现的设计依据，不是实现本身。
> **关联**：补充 `tests/agent/DIAGNOSTICS.md`（诊断报告）中"根因 B/F + `Command(goto=)` 双时间线"部分。
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

1. **单时间线原则**：整个 agent graph 的执行永远只有一条时间线。回跳通过"终止当前 graph 执行 + 外层重走"实现，**绝不依赖 `Command(goto=)` 在 phase 节点中途跳转**（那是双时间线的根源）。回跳后重走的 graph 仍由静态边驱动单线流转。
2. **串行/并行区别对待原则**（核心）：
   - **phase-2 串行节点**（construction/surface/fenestration）：任一节点回跳请求 → **立即终止本轮**，外层重走（不白跑下游串行节点）
   - **phase-3 并行节点**（hvac/people/lights）：回跳请求**必须等三节点全部完成**后在 barrier 合并，统一一次回跳（绝不一个回跳就终止另两个）
3. **显式拓扑原则**：所有节点连接用静态边声明，graph 拓扑在编译期可校验、可视化准确，杜绝隐式控制流（不采用"删静态边 + Command 控制"方案）。
4. **LLM 优先自愈原则**：工具发现缺失依赖时，错误信息先回到该 phase 的 LLM，让 LLM 自己尝试解决（用现有对象替代、调整引用等）；只有 LLM 确认无法解决时，才主动调用"回跳请求"工具。
5. **回跳目标最早原则**：当多个回跳请求目的地分散在不同 phase，统一回退到 `PIPELINE_ORDER` 中**最早**的目标 phase，从那里往下顺跑，一条回跳链修复多个缺失。

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
         ┌─── construction → surface → fenestration ───┐  【phase-2 串行】
         │     （任一节点回跳请求 → 立即终止本轮 graph，│
         │      外层带 upstream_request 重走 graph）    │
         └─────────────────────────────────────────────┘
                           │ (fan-out)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
            hvac        people        lights          【phase-3 并行】
          (各自判断回跳，但全部跑完才合并)
              └────────────┼────────────┘
                        barrier
                           ▼
                  cross_ref_complete  ← ★ phase-3 回跳合并决策点
                           │
                  ┌────────┴────────────────────┐
            (有回跳请求)                    (无回跳请求)
                  ▼                            ▼
        合并多请求→取最早目标           validate（正常路径）
        终止本轮，外层重走 graph
        从最早目标 phase 起
```

### 回跳的两种模式（关键设计）

回跳行为按 phase 的拓扑特征分两种模式——这是目标框架的核心区分：

#### 模式 A：phase-2 串行节点 —— 回跳请求立即终止本轮、外层重走 graph

phase-2（construction → surface → fenestration）是**严格串行**。任一节点发出回跳请求后：
- **立即终止当前 graph 的执行**（不再往下跑后续串行节点——既然上游要重做，下游跑了也白跑）
- 回跳请求（`missing_ref` + `missing_name`）记录到 `state.upstream_request`
- **外层重新启动 graph 执行**，从回跳目标 phase 开始重走（目标 phase 接收 `upstream_request`、重建缺失对象，然后静态边自然驱动往下顺跑）

> **为什么串行节点要立即终止**：串行节点之间有严格依赖（construction 的产物是 surface 的输入）。一个节点回跳意味着上游缺失，后续串行节点必然也无法正常工作，继续跑纯属浪费。立即终止 + 重走是最优路径。

#### 模式 B：phase-3 并行节点 —— 三个节点全部跑完后，合并请求统一回跳

phase-3（hvac / people / lights）是**三路并行**。回跳处理必须等三者都完成：
- 每个节点独立判断是否需要回跳，需要则调 `request_backhop` 写入 `state.upstream_request`
- 三节点通过 `_merge_upstream_request` reducer（"非 None 请求获胜"）把各自的回跳请求**合并到 state**
- **三个节点全部执行完毕后**，在 `cross_ref_complete` barrier 汇聚点统一处理——**绝不能一个节点回跳就终止另两个没跑完的节点**
- `cross_ref_complete` 收集所有回跳请求，用 `earliest_phase()` 取 `PIPELINE_ORDER` 中**最早**的目标，统一发起一次回跳

> **为什么并行节点要合并**：phase-3 三个节点互不依赖（各自独立引用 zone/schedule）。若一个节点回跳就终止，会浪费另两个可能已完成或快完成的工作；且并行终止在 LangGraph 里正是双时间线问题的根源。合并后统一回跳保证单时间线。

> **两种模式的共同点**：无论模式 A 还是 B，最终都是"终止当前 graph → 外层带着 `upstream_request` + `hop_count+1` 重走"。区别只在**何时终止**——串行立即终止，并行等 barrier 合并后终止。

### 回跳的触发与流转（目标态，6 步）

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

    调用后，本 phase 会把回跳请求记录到共享状态。
    - phase-2 串行节点：立即终止本轮 graph，外层重走。
    - phase-3 并行节点：请求合并到 state，等三节点全部完成后统一处理。
    """
```

LLM 调用此工具 = "我确认这个对象必须由上游创建，我无法自行解决"。

#### 第 3 步：phase-2 串行节点 —— 立即终止 + 外层重走（模式 A）

phase-2 节点（construction/surface/fenestration）的 LLM 调了 `request_backhop` 后：
- 节点把请求写入 `state.upstream_request`，**立即终止当前 graph 执行**（具体终止机制见下方"待评审开放问题"，候选：raise 异常 / interrupt / Command）
- **外层重新启动 graph**，从回跳目标 phase 开始（带 `upstream_request` + `hop_count+1` + `is_revision=True`）
- 目标 phase 接收请求、重建缺失对象，然后静态边自然驱动往下顺跑到 simulate
- **不经过未完成的下游串行节点**（如 surface 回跳则 fenestration 本轮不跑，重走时才跑）

#### 第 4 步：phase-3 并行节点 —— 全部跑完后合并（模式 B）

phase-3 节点（hvac/people/lights）的 LLM 调了 `request_backhop` 后：
- 每个节点把请求写入 state，**但继续完成自身能做的工作**（不立即终止——另外两个节点还在并行跑）
- 三节点通过 reducer 合并各自的 `upstream_request`
- **三节点全部完成后**，`cross_ref_complete` barrier 汇聚，进入第 5 步

#### 第 5 步：`cross_ref_complete` 合并决策（phase-3 的回跳汇聚点）

`cross_ref_complete` 改造为**回跳合并决策节点**：

1. 检查 `state.upstream_request` 是否含（phase-3 合并的）回跳请求
2. **若无请求** → 正常走 `validate`（静态边）
3. **若有请求**：
   - 用 `earliest_phase()` 取所有请求目标中**最早**的 phase（如 hvac 请求回 zone、people 请求回 schedule → 取 zone）
   - 检查 `hop_count < HOP_LIMIT`
   - **终止本轮 graph，外层带 `upstream_request` + `hop_count+1` 重走**（同模式 A 的终止机制，只是发生在 barrier 之后）

#### 第 6 步：回跳目标 phase 接收请求并顺跑（两种模式共用）

回跳目标 phase（如 zone）通过现有的 inbound 消费块读取 `state.upstream_request`，把请求 spec 追加到自己的 specs，重做创建工作。完成后，**静态边自然驱动它往下顺跑**（zone → cross_ref_foundations → construction → surface → ... → simulate），无需任何中途 Command。这样保证单时间线。

### 目标态 vs 当前态对比

| 维度 | 当前态 | 目标态 |
|------|--------|--------|
| 回跳触发 | 工具发现 `missing_ref` → 自动短路回跳 | 工具返回错误 → LLM 自愈尝试 → LLM 确认后主动调 `request_backhop` |
| phase-2 串行回跳 | 各节点发 `Command(goto=)` → 双时间线竞态 | **立即终止本轮 + 外层重走**（模式 A），不白跑下游 |
| phase-3 并行回跳 | 各节点发 `Command(goto=)` → 一个回跳可能中断另两个 | **三节点全跑完后 barrier 合并**（模式 B），统一取最早目标 |
| 时间线 | 双时间线（回跳链 + 下游直冲链并发） | **单时间线**（外层重走，无并发直冲） |
| 多目标回跳 | 各自 Command，可能多条回跳链 | 取最早目标，单一回跳链 |
| LLM 自愈能力 | 无（自动回跳，LLM 看不到错误） | 有（错误先回 LLM，能替代则替代） |

### 目标态下的 case_02 场景重演（验证设计）

假设 surface（phase-2 串行节点）发现引用的 `Private_Office_1` zone 不存在：

1. `create_surface` 返回错误（`missing_ref='Zone'`）给 surface 的 LLM
2. surface LLM 检查 `list_zones`，确认确实没有 `Private_Office_1`，无法替代 → 调用 `request_backhop('Zone', 'Private_Office_1', 'spec 要求但未创建')`
3. surface 把请求写入 `state.upstream_request`，**立即终止本轮 graph**（模式 A：fenestration / hvac / people / lights / simulate 本轮全不跑）
4. **外层重走 graph**，从 zone 开始（带 `upstream_request`）：zone 重建 `Private_Office_1` → 静态边顺跑 → construction → surface（这次成功创建）→ fenestration → phase-3 → cross_ref_complete → validate → simulate
5. simulate 拿到的是**完整重建后的 IDF**

对比当前态：当前 surface 回跳后 fenestration 会跟着直冲到 simulate（双时间线），用 0-surface 的 IDF 跑出 Fatal。目标态下 simulate 永远在完整重建后才跑。

### 目标态下的 phase-3 多请求场景（验证模式 B）

假设 hvac 和 people 都发现缺失：
1. hvac 调 `request_backhop('Zone', 'Office_North')`，继续跑完自身
2. people 调 `request_backhop('Schedule:Compact', 'Occ_Sched')`，继续跑完自身
3. lights 正常完成，无请求
4. **三节点全部完成**后，`cross_ref_complete` 合并请求 → `earliest_phase({'zone','schedule'})` = zone（`PIPELINE_ORDER` 中 zone 更早）
5. 终止本轮，外层从 zone 重走 → zone 重建 → 顺跑时 schedule 也会重新执行（因为重走覆盖 schedule phase）→ 一并修复两个缺失

**一个回跳链修复多个缺失，无并发竞态。**

---

## 三、实现涉及的组件（概览，详见后续实现计划）

| 组件 | 改动方向 |
|------|---------|
| `src/agent/nodes/_share.py` | 移除 `invoke_with_self_repair` 里的 `detect_upstream_gap` 自动短路；新增统一的回跳终止/重走机制（具体形式见开放问题 1） |
| 新增 `request_backhop` 工具 | 加入 construction/surface/fenestration/hvac/people/lights 的工具集，LLM 主动调用 |
| `src/agent/nodes/cross_ref.py` | `cross_ref_complete_node` 改造为 phase-3 回跳合并决策点：等三节点完成后合并请求 → 取最早目标 → 终止重走 |
| phase-2 串行节点（construction/surface/fenestration） | LLM 调 `request_backhop` 后**立即终止本轮**（模式 A）；移除现有的 `maybe_backhop` + `Command(goto=)` 调用 |
| phase-3 并行节点（hvac/people/lights） | LLM 调 `request_backhop` 后**继续跑完自身**，请求写入 state 待合并（模式 B）；移除现有的 `maybe_backhop` + `Command(goto=)` 调用 |
| 回跳目标 phase（zone/material/schedule/construction/surface） | inbound 消费块保留（重走时读 `upstream_request` 追加 spec） |
| graph 外层驱动（`main.py` / 调用 `graph.invoke` 的入口） | 可能需要改造为"捕获回跳终止信号 → 带 `upstream_request` 重新 invoke"的循环（取决于开放问题 1 的选择） |

### 待评审的开放问题

#### 问题 1（核心，必须先定）：phase-2 "立即终止 + 外层重走" 的底层机制

这是整个目标框架落地的前提。当前已排除"删静态边 + Command 控制"（引入隐形控制流，文档第一节已证伪）。剩余候选：

- **候选 a：raise 特殊异常 + 外层捕获重跑**
  - phase-2 节点检测到回跳请求时 `raise BackhopRequest(target, missing_ref, missing_name)`
  - 外层 `graph.invoke` 的调用方用 try/except 捕获，带着 `upstream_request` + `hop_count+1` 重新 `graph.invoke`
  - **优点**：彻底单时间线，graph 拓扑完全静态，无 LangGraph 调度竞态；实现清晰
  - **缺点**：用异常做控制流（非惯用）；外层需改为 invoke 循环；checkpoint 状态需正确传递（已建的对象不能丢）

- **候选 b：interrupt() 暂停 + 外层 resume 重走**
  - phase-2 节点调 LangGraph 的 `interrupt()` 暂停 graph
  - 外层检测到 interrupt 后，用 `Command(resume=...)` 或重新 invoke 恢复
  - **优点**：用 LangGraph 原生暂停机制，状态保持完整
  - **缺点**：interrupt 设计用途是人机交互（等人审批），语义上不完全是"自动重走"；resume 机制较复杂

- **候选 c：Command(goto=END) 终止本轮 + 外层检测 state 重走**
  - phase-2 节点把请求写入 state，返回 `Command(goto=END)` 正常结束本轮 graph
  - 外层检测到 `state.upstream_request` 非空且未到 simulate，重新 invoke
  - **优点**：不抛异常，用 END 自然终止；外层逻辑简单（检查 state 字段）
  - **缺点**：需确认 `Command(goto=END)` 不会触发下游（END 是终止符，应该安全，但需验证）；需区分"正常结束"和"回跳结束"

**建议**：候选 a（异常）或候选 c（goto=END）二选一，都需要先把"外层 invoke 循环 + 状态传递"验证清楚再定。

#### 问题 2：回跳请求的 hop_count 限制
现有 `HOP_LIMIT=3` 是否够用？目标态下回跳更少（LLM 自愈拦截一部分），但需在实现后用真实 case 验证。

#### 问题 3：`request_backhop` 工具的误调防护
LLM 可能误调（明明能用现有对象替代却请求回跳）。是否需要在 `request_backhop` 内加二次校验（如检查目标对象确实不存在）？或信任 LLM 判断？

#### 问题 4：phase-1（zone/material/schedule）的回跳
它们是回跳目标，但自身也可能需要回跳到 intake（specs 不完整）——这是另一个维度（phase→intake 的回退，而非 phase→上游phase 的回跳），本文档暂不覆盖，留待后续。

#### 问题 5：重走时已建对象的保留
外层重走 graph 时，前面 phase 已建的对象（如 material/schedule 已完成）应保留，只重跑回跳目标及之后的 phase。这需要 graph 从特定节点起重新执行（而非从 intake 重头），需确认 LangGraph 是否支持"从中间节点重新 invoke"或需要外层用条件启动。

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
