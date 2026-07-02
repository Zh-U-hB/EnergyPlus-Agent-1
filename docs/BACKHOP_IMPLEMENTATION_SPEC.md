# 回跳机制重实现规格（已验证方案）

> **文档目的**：定义 agent graph 回跳（back-hop）机制的**最终实现规格**。本文档基于 `docs/BACKHOP_REDESIGN.md`（目标框架）和一系列 LangGraph 1.1.8 验证实验，锁定具体实现方案。实现工作以此为准。
> **状态**：方案已验证，待实现。
> **前置阅读**：`docs/BACKHOP_REDESIGN.md`（问题背景 + 目标框架）、`agent_test/DIAGNOSTICS.md`（case_01/case_02 诊断）。

---

## 一、方案定论：方式 A（interrupt 挂起 + 外层开新 thread 重跑）

### 为什么选这个方案

经系统验证，LangGraph 1.1.8 的**所有节点内跳转机制**都无法干净地实现"挂起起点进度 + 回跳目标 + 不触发下游"：

| 机制 | 保留进度 | 跳到目标 | 不触发下游 | 结论 |
|------|---------|---------|----------|------|
| `Command(goto=目标)`（当前机制） | ✅ | ✅ | ❌ 静态边并发 | ❌ 双时间线（case_02 根因） |
| 删静态边 + Command | ✅ | ✅ | ✅ | ❌ 隐形拓扑（可视化失真/拼错静默/漏分支静默跳过） |
| `Command(goto=END)` | ✅ | ❌ | ❌ 下游仍触发 | ❌ |
| raise 异常（无 checkpoint） | ❌ 状态丢 | — | — | ❌ |
| raise + checkpoint + Command 恢复 | ✅ | ✅ | ❌ 下游仍触发 | ❌ 双时间线 |

**根本原因**：LangGraph 的调度模型里，节点一旦执行/标记完成，其静态出边必然被触发；`Command(goto=)` 是**追加**目标到队列，不是**替换**。所以只要回跳起点节点有静态出边，goto 和出边必然并发。唯一例外"删静态出边"会引入隐形拓扑（已否决）。

### 已验证的方案：interrupt + 外层新 thread 重跑

**把"回跳"从 graph 内部跳转重新定义为"外层循环重跑整个 graph"。** graph 本身永远是单线静态拓扑（从 START 到 END），回跳是外层驱动的责任。

**验证实验结论**（贴近真实 agent 结构的端到端复现，全部通过）：

| 验证点 | 结果 |
|--------|------|
| `interrupt()` 能在 phase 节点干净挂起 | ✅ graph 暂停，控制权回外层 |
| 挂起时起点进度（已建对象）保留 | ✅ 快照里 zone/construction 产物都在 |
| 挂起时下游（fenestration/simulate）不执行 | ✅ `next` 停在挂起点 |
| 外层能拿到 interrupt payload（回跳目标） | ✅ `{type,target,missing}` |
| 新 thread 带快照重跑，config_state 正确传递 | ✅ reducer 合并，已建对象保留 |
| 重跑时单时间线（无双线竞态） | ✅ 严格顺序执行 |
| 重跑时已建对象靠 idf.has 跳过 | ✅ 已建 phase 跳过 |
| 回跳目标读 upstream_request 重建缺失 | ✅ 补建缺失对象 |
| simulate 最终拿到完整模型 | ✅ 全部对象齐全 |

**实验的执行序列证明**（关键）：
```
第1轮(t0): intake → zone(建Office_North) → construction(建) → surface(缺Private_Office_1 → interrupt挂起)
           [fenestration/simulate 未跑，已建对象保留在快照]
外层: 捕获 interrupt → 开新 thread t1，带快照 + upstream_request + hop_count+1
第2轮(t1): intake(跳过) → zone(读upstream_request, 补建Private_Office_1) → construction(已存在,跳过)
           → surface(建surface) → fenestration(建) → simulate(拿到完整模型)
```
全程单时间线，无并发直冲，起点进度保留。

---

## 二、串行 vs 并行：两种回跳模式

回跳行为按 phase 拓扑分两种模式（核心设计，详见 `BACKHOP_REDESIGN.md` 第二节）：

### 模式 A：phase-2 串行节点 —— 立即挂起

phase-2（construction → surface → fenestration）严格串行。任一节点 LLM 调 `request_backhop` 后：
- **立即 `interrupt()` 挂起**（不等下游串行节点——上游要重做，下游白跑）
- 回跳请求写入 `state.upstream_request`
- 外层捕获 → 开新 thread 重跑

### 模式 B：phase-3 并行节点 —— 全部跑完后在 barrier 合并挂起

phase-3（hvac / people / lights）三路并行。回跳必须等三者都完成：
- 每个节点独立判断，需要回跳则调 `request_backhop`，请求写入 `upstream_request`（reducer 合并），**但继续跑完自身**（不立即挂起）
- 三节点全部完成后，在 `cross_ref_complete` barrier 汇聚
- `cross_ref_complete` 检测到合并的回跳请求 → 取最早目标（`earliest_phase()`）→ `interrupt()` 挂起
- 外层捕获 → 开新 thread 重跑

> **为什么并行不能立即挂起**：phase-3 三节点互不依赖，一个挂起会浪费另两个可能已完成的工作，且并行挂起在 LangGraph 里行为复杂。合并到 barrier 后统一挂起，保证三节点都跑完。

---

## 三、各组件实现职责（精确到文件/函数）

### 1. 新增 `request_backhop` 工具（LLM 主动调用）

**位置**：加入 construction/surface/fenestration/hvac/people/lights 的工具集（各 `src/agent/tools/*_tools.py`）。

```python
@tool
def request_backhop(missing_ref: str, missing_name: str, reason: str) -> str:
    """确认需要上游 phase 创建缺失对象后调用此工具。

    仅当已尝试用现有对象替代、确认无法自行解决时调用。
    调用后本 phase 会挂起（串行）或记录请求待合并（并行），外层重跑 graph。

    Args:
        missing_ref: 缺失对象类型（'Zone'/'Schedule:Compact'/'Material'/'Construction'）
        missing_name: 缺失对象名称
        reason: 为什么需要回跳（说明已尝试但无法替代）
    """
    return _ok("backhop requested", {
        "missing_ref": missing_ref, "missing_name": missing_name, "reason": reason,
        "target": _MISSING_REF_TO_PHASE.get(missing_ref),  # 复用现有映射表
    })
```

**设计要点**：
- LLM 主动调用（替代当前"工具报 missing_ref 自动触发回跳"）
- 工具本身只返回确认信息；真正的挂起由 phase 节点在 ReAct 结束后检测"LLM 调了 request_backhop"来执行
- 复用现有 `_MISSING_REF_TO_PHASE`（`_share.py:56-63`）映射 missing_ref → 目标 phase

### 2. 新增 `_detect_backhop_request` 辅助函数

**位置**：`src/agent/nodes/_share.py`（复用 `detect_upstream_gap` 的扫描逻辑，`_share.py:191-234`）。

```python
def _detect_backhop_request(result: dict, phase: str) -> dict | None:
    """扫描 ReAct 结果，看 LLM 是否调了 request_backhop 工具。

    复用 detect_upstream_gap 的 ToolMessage 扫描模式，但找的是
    request_backhop 工具的 success 调用（而非 missing_ref 错误）。
    返回 {target, missing_ref, missing_name} 或 None。
    """
    for msg in result.get("messages", []):
        if getattr(msg, "type", None) != "tool":
            continue
        try:
            payload = json.loads(msg.content)
        except (TypeError, ValueError):
            continue
        data = payload.get("data") or {}
        if payload.get("success") and data.get("target"):  # request_backhop 调用
            return {"target": data["target"],
                    "missing_ref": data.get("missing_ref"),
                    "missing_name": data.get("missing_name")}
    return None
```

### 3. 改造 `invoke_with_self_repair`（移除自动回跳短路）

**位置**：`src/agent/nodes/_share.py:298-305`。

**移除** `detect_upstream_gap` 的自动短路（当前：工具报 missing_ref → 立即设 hop_request → 短路返回）。

改造后：工具的 `missing_ref` 错误信息**回到 phase 的 LLM**（作为 ToolMessage），让 LLM 先自愈尝试（用 list_* 找替代对象、调整引用）。只有 LLM 主动调 `request_backhop` 才触发回跳。

`invoke_with_self_repair` 的 self-repair 循环（`MAX_SELF_REPAIR_ROUNDS=2`）保持不变——它处理的是"本 phase 自己的交叉引用错误"，与回跳无关。

### 4. 改造 phase-2 串行节点（模式 A：立即挂起）

**位置**：`src/agent/nodes/construction.py`、`surface.py`、`fenestration.py`。

以 `surface.py` 为例（`surface.py:106-108` 当前是 `maybe_backhop` 调用，改为）：

```python
def surface_agent(state: AgentState) -> AgentStateUpdate:
    ...
    result = invoke_with_self_repair(agent, local, specs, phase="surface", ...)

    record_phase_trace("surface", collector.export())

    # 【改造】检测 LLM 是否调了 request_backhop
    backhop = _detect_backhop_request(result, phase="surface")
    if backhop:
        # 模式 A：立即 interrupt 挂起
        # 把已建对象(local) + 回跳请求 写入 state，然后挂起
        from langgraph.types import interrupt
        specs_for_upstream = build_upstream_specs(backhop, state)  # 复用现有函数
        # 先把 local 写入 state（保留已建对象），再挂起
        # 注：interrupt 的 payload 由外层读取决定重跑
        return Command(goto=END, update={
            "config_state": local,
            "upstream_request": {"target": backhop["target"], "specs": specs_for_upstream},
            "hop_count": state.hop_count + 1,
        })
        # 实际实现用 interrupt() 挂起（见下方"挂起方式说明"）

    # 正常完成
    ...
    return AgentStateUpdate(config_state=local, upstream_request={}, ...)
```

**移除**：`maybe_backhop(result, state, local, "surface")` 调用 + `Command[_SurfaceRoute]` 返回类型（不再发 goto 回跳）。

**保留**：工具的 `missing_ref` 错误返回（给 LLM 看，让其自愈）；inbound `upstream_request` 消费块（重跑时读请求重建）。

### 5. 改造 phase-3 并行节点（模式 B：记录不挂起）

**位置**：`src/agent/nodes/hvac.py`、`people.py`、`lights.py`。

以 `hvac.py` 为例：

```python
def hvac_agent(state: AgentState) -> AgentStateUpdate:
    ...
    result = invoke_with_self_repair(agent, local, specs, phase="hvac", ...)

    record_phase_trace("hvac", collector.export())

    backhop = _detect_backhop_request(result, phase="hvac")
    if backhop:
        # 模式 B：只记录请求，不挂起（等 cross_ref_complete barrier 合并）
        specs_for_upstream = build_upstream_specs(backhop, state)
        return AgentStateUpdate(
            config_state=local,
            upstream_request={"target": backhop["target"], "specs": specs_for_upstream},
            hop_count=state.hop_count + 1,
        )

    # 正常完成
    return AgentStateUpdate(config_state=local, upstream_request={}, ...)
```

**移除**：`maybe_backhop` 调用 + `Command[_HvacRoute]` 返回类型。

### 6. 改造 `cross_ref_complete` barrier（模式 B 汇聚挂起点）

**位置**：`src/agent/nodes/cross_ref.py:13`（当前是 pass-through 校验）。

```python
def cross_ref_complete_node(state: AgentState) -> AgentStateUpdate:
    """phase-3 barrier：校验 + 回跳合并决策。"""
    errors = state.config_state.validate_references()
    req = state.upstream_request
    if req and isinstance(req, dict) and req.get("target"):
        # phase-3 有合并的回跳请求 → 取最早目标 → 挂起
        target = req["target"]  # 若多请求，reducer 已合并；可扩展为 earliest_phase 取最早
        if state.hop_count < HOP_LIMIT:
            from langgraph.types import interrupt
            interrupt({"type": "backhop", "target": target,
                       "specs": req.get("specs"), "hop_count": state.hop_count + 1})
    return AgentStateUpdate(validation_errors=errors)
```

### 7. 扩展外层驱动 `run_session`（核心：开新 thread 重跑）

**位置**：`src/agent/runner.py:46-64`（当前只处理 validate interrupt）。

```python
def run_session(graph, initial, context, config, on_interrupt, ...):
    reset_traces()
    payload = initial
    backhop_round = 0
    MAX_BACKHOP_ROUNDS = 5  # 防死循环

    while True:
        for event in graph.stream(payload, config=config, context=context, stream_mode="updates"):
            ...  # 事件处理不变

        snapshot = graph.get_state(config)
        pending = [t.interrupts[0] for t in snapshot.tasks if t.interrupts]
        if not pending:
            return dict(snapshot.values)  # 正常结束

        interrupt_payload = pending[0].value

        # 【新增】区分 backhop interrupt vs validate interrupt
        if isinstance(interrupt_payload, dict) and interrupt_payload.get("type") == "backhop":
            if backhop_round >= MAX_BACKHOP_ROUNDS:
                logger.warning("backhop exhausted after {} rounds, proceeding with current model",
                               MAX_BACKHOP_ROUNDS)
                return dict(snapshot.values)
            backhop_round += 1
            snap_state = dict(snapshot.values)
            target = interrupt_payload["target"]
            logger.info("[backhop round {}] target={}, 重跑 graph（保留已建对象）",
                        backhop_round, target)
            # 开新 thread：快照状态 + upstream_request + hop_count+1
            config = {**config,
                      "configurable": {"thread_id": f"{config['configurable']['thread_id']}_bh{backhop_round}"}}
            payload = {**snap_state,
                       "upstream_request": {"target": target, "specs": interrupt_payload.get("specs")},
                       "hop_count": interrupt_payload.get("hop_count", snap_state.get("hop_count", 0) + 1)}
            continue
        else:
            # validate interrupt（原逻辑）
            decision = on_interrupt(interrupt_payload)
            payload = Command(resume=decision)
```

### 8. 回跳目标 phase 接收请求（重跑时生效，现有逻辑）

**位置**：`zone.py:52-55`、`material.py:94-96`、`schedule.py:138-141`、`construction.py:94-96`、`surface.py:88-90`（inbound 消费块，已存在）。

重跑时，目标 phase 读 `state.upstream_request`，把 `upstream['specs']`（含"请创建 X"指令）追加到自己的 specs，重建缺失对象。其它 phase 靠工具的 `if idf.has(...)` 去重跳过已建对象。

### 9. intake 跳过（重跑时不重跑 intake）

**位置**：`src/agent/nodes/intake.py`（intake_node 入口）。

重跑时 intake 不该重跑（specs 已在 `intake_output`）。两种实现：
- **(a)** intake_node 加 `if state.intake_output: return {}`（跳过）
- **(b)** 外层设 `is_revision=True`，让 `_entry_router`（`graph.py:149-151`）走 revise 分支（revise 本就是"修订"语义，跳过 intake）

倾向 (a)，更直接。

---

## 四、完整回跳场景端到端流转（case_02 surface 缺 zone）

### 第 1 轮（thread t0，从 START）

```
intake(产 specs)
→ [zone(建Office_North等) / material(建) / schedule(建)] 并行 → cross_ref_foundations
→ construction(建) → surface
    └ LLM 调 create_surface → 发现 Private_Office_1 不存在 → 错误回 LLM
    └ LLM 查 list_zones，确认确实没有 → 调 request_backhop('Zone','Private_Office_1')
    └ surface 节点检测到 backhop → interrupt() 挂起
[挂起：fenestration/hvac/people/lights/simulate 都没跑]
[快照保留：zone/material/schedule/construction 已建对象 + upstream_request]
```

### 外层 run_session 捕获

```
检测到 interrupt payload = {type:"backhop", target:"zone", specs:..., hop_count:1}
snap_state = snapshot.values（含 config_state 已建对象）
开新 thread t1，payload = snap_state + upstream_request + hop_count=1
```

### 第 2 轮（thread t1，从 START，带已建对象）

```
intake(跳过，intake_done)
→ [zone(读 upstream_request，补建 Private_Office_1；其它 zone 靠 idf.has 跳过)
   / material(全跳过) / schedule(全跳过)] 并行 → cross_ref_foundations
→ construction(跳过，已建) → surface(这次 zone 齐了，成功建 surface) → fenestration(成功)
→ [hvac/people/lights] → cross_ref_complete(无回跳请求) → validate → simulate
```

**simulate 拿到完整 IDF，无双时间线，无竞态。**

---

## 五、phase-3 多请求场景（验证模式 B）

假设 hvac 和 people 都发现缺失：

```
第1轮: ... → [hvac(调 request_backhop Zone/Office_North, 但继续跑完)
              people(调 request_backhop Schedule:Compact/Occ_Sched, 但继续跑完)
              lights(正常完成)]
       → cross_ref_complete barrier 汇聚
          └ upstream_request 经 _merge_upstream_request reducer 合并
          └ 检测到有请求 → earliest_phase({zone, schedule}) = zone → interrupt 挂起
外层: 开新 thread，从 zone 重跑
第2轮: zone 重建 → 重跑时 schedule 也重新执行（覆盖） → 一条链修复两个缺失
```

**一个回跳链修复多个缺失，无并发竞态。**

---

## 六、待实现时验证的两个细节（不影响方案成立）

### 1. 真实 ConfigState（含 idfpy IDF）跨 thread 传递

验证实验用的是 dict 模拟 `config_state`。真实 `ConfigState` 含 idfpy IDF 对象（有 weakref 内部状态），跨 thread 时需确认 `merge_config_state` reducer（`state.py:247-301`）能正确接收快照的 ConfigState，不被默认空 ConfigState 覆盖。

**风险点**：新 thread 初始化时，LangGraph 用初始 state 的 `config_state` 字段值；若 reducer 行为是"new wins"，则快照的 ConfigState 应该胜出。但 idfpy IDF 的 weakref 在 pickle/checkpoint 时可能有问题（`graph.py:51-65` 的 `_PickleSerde` 已有 fallback 处理）。

**验证方法**：实现后用一个真实 ConfigState（含几个 IDF 对象）跑端到端回跳，检查重跑时已建对象是否还在。

### 2. phase-3 cross_ref_complete barrier 用 interrupt

验证实验只测了串行节点（surface）的 interrupt。`cross_ref_complete` 是并行 barrier 之后的节点，需单独验证它的 interrupt 行为是否和串行节点一致。

**风险点**：barrier 节点的 interrupt 理论上和普通节点一样（它本身是单节点），但需确认。

**验证方法**：实现后构造一个 phase-3 回跳场景（hvac 缺 zone），检查 cross_ref_complete 能否正确 interrupt + 外层重跑。

---

## 七、修改文件清单

| 文件 | 改动 |
|------|------|
| `src/agent/tools/construction_tools.py` | 新增 `request_backhop` 工具 |
| `src/agent/tools/surface_tools.py` | 同上 |
| `src/agent/tools/fenestration_tools.py` | 同上 |
| `src/agent/tools/hvac_tools.py` | 同上 |
| `src/agent/tools/people_tools.py` | 同上 |
| `src/agent/tools/lights_tools.py` | 同上 |
| `src/agent/nodes/_share.py` | 移除 `invoke_with_self_repair` 的 `detect_upstream_gap` 自动短路（298-305）；新增 `_detect_backhop_request`；`maybe_backhop` 废弃或保留供 barrier 用 |
| `src/agent/nodes/construction.py` | 移除 `maybe_backhop` 调用 + `Command[_ConstructionRoute]`；改为检测 backhop → interrupt 挂起（模式 A） |
| `src/agent/nodes/surface.py` | 同上 |
| `src/agent/nodes/fenestration.py` | 同上 |
| `src/agent/nodes/hvac.py` | 移除 `maybe_backhop` + `Command[_HvacRoute]`；改为检测 backhop → 记录到 state 不挂起（模式 B） |
| `src/agent/nodes/people.py` | 同上 |
| `src/agent/nodes/lights.py` | 同上 |
| `src/agent/nodes/cross_ref.py` | `cross_ref_complete_node` 改造为模式 B 汇聚挂起点 |
| `src/agent/nodes/intake.py` | 加 `if state.intake_output: return {}` 跳过重跑 |
| `src/agent/runner.py` | `run_session` 扩展：区分 backhop/validate interrupt，backhop 时开新 thread 重跑 |
| `src/agent/nodes/zone.py` 等 | inbound 消费块保留（已有，无需改） |
| `src/agent/graph.py` | 拓扑不变（仍纯静态边）；无需改 |

---

## 八、与已有机制的关系

### 与 validate 的 directed rollback（共存）
- validate 的 directed rollback（`validate_node` 在 pipeline 末端把错误路由到最早出错 phase）**保留不变**。
- 它处理的是"全局交叉引用错误"（对象都建了但引用关系错），通过 `retry_count` 限制。
- 本文的回跳机制处理的是"上游对象根本没建"，通过 `hop_count` 限制。
- 两者互补：回跳是"飞行中"（phase 发现缺失立即挂起重跑），validate rollback 是"后置"（全 pipeline 跑完统一修引用）。

### 与 zone 校验模块（共存）
- commit `60e74a2` 的 zone 校验模块（`zone_validator.py`）处理"zone 静默放弃（0 zone）"——zone phase 内部独立 LLM 校验 + 重试，不涉及跨 phase 回跳。
- 本文的回跳机制处理"跨 phase 依赖缺失"。
- 两者无冲突，可共存。

### 与已完成但将被替换的工作
- commit `60e74a2` 给 hvac/people/lights 接的 `maybe_backhop` + `Command[_Route]`（执行层）**将被本文方案替换**——那些 phase 节点不再发 `Command(goto=)`，改为 interrupt 挂起或记录到 state。
- commit `60e74a2` 给 create_people/create_lights 补的 `missing_ref` 引用检查**保留**（错误信息要回 LLM 让其自愈）。

---

## 附：关键术语与文件位置速查

| 术语/函数 | 位置 |
|----------|------|
| `run_session` 外层驱动 | `src/agent/runner.py:20-64` |
| `invoke_with_self_repair`（self-repair 循环） | `src/agent/nodes/_share.py:237-348` |
| `detect_upstream_gap`（将被替换为 `_detect_backhop_request`） | `src/agent/nodes/_share.py:191-234` |
| `maybe_backhop`（将被废弃） | `src/agent/nodes/_share.py:402-449` |
| `build_upstream_specs`（复用，构造回跳 spec） | `src/agent/nodes/_share.py:351-399` |
| `earliest_phase`（取最早回跳目标） | `src/agent/nodes/_share.py:145-150` |
| `_MISSING_REF_TO_PHASE`（missing_ref→phase 映射） | `src/agent/nodes/_share.py:56-63` |
| `HOP_LIMIT=3` / `MAX_SELF_REPAIR_ROUNDS=2` | `src/agent/nodes/_share.py:46 / 38` |
| `cross_ref_complete_node`（模式 B 汇聚点） | `src/agent/nodes/cross_ref.py:13` |
| `_merge_upstream_request` reducer（请求合并） | `src/agent/state.py:77-98` |
| `merge_config_state` reducer（IDF 对象合并） | `src/agent/state.py:247-301` |
| inbound 消费块（各回跳目标 phase） | zone.py:52-55 / material.py:94-96 / schedule.py:138-141 / construction.py:94-96 / surface.py:88-90 |
