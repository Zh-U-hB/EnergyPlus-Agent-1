# 保留当前回跳机制下的待修复问题清单

> **文档目的**：记录在**暂不重构回跳机制**（暂时容忍 `Command(goto=)` 双时间线问题）的前提下，仍然独立存在、需要修复的问题。这些问题与双时间线无关，无论是否保留当前回跳机制都该修。
> **状态**：待实现。
> **关联**：`agent_test/DIAGNOSTICS.md`（根因分析）、`docs/BACKHOP_REDESIGN.md`（回跳机制目标框架）、`docs/BACKHOP_IMPLEMENTATION_SPEC.md`（回跳重实现规格）。

---

## 背景：当前已修复 vs 仍存在

### ✅ 已修复（commit `60e74a2`，无需再动）

| 诊断根因 | 问题 | 修复 |
|---------|------|------|
| 根因 F | hvac/people/lights 漏接 `maybe_backhop` 执行层 → 检测到 missing Zone 却不发 Command，回跳从未发生（case_01 直接原因） | 三节点都接了 maybe_backhop + `Command[_Route]` |
| 工具缺失检查 | create_people/create_lights 不检查 zone/schedule 引用就 add → 即使接 maybe_backhop 也触发不了 detect_upstream_gap | 补了 missing_ref 引用检查 |
| 根因 A（zone 部分） | zone 分支 LLM 静默放弃（0 zone），无校验拦截 | 加了 zone_validator 独立校验模块（approve/reject + 3 轮重试） |

### 🔁 双时间线相关（本文档假设暂不管）

| 诊断根因 | 问题 | 本文档态度 |
|---------|------|----------|
| 根因 B/C 交集 | `Command(goto=)` 触发下游并发直冲 simulate（case_02 直接原因） | **暂时容忍**——靠下方"问题 1（simulate 前置校验）"兜底：即使 simulate 抢跑用残缺 IDF 跑了，前置校验拒绝并报错，不会假阳性 |

---

## 待修复问题（按优先级）

### 问题 1（P0，最高优先级）：simulate 缺少前置完整性校验

**诊断根因**：C（`agent_test/DIAGNOSTICS.md`）

**现状**：
`WorkflowTool.run_simulation`（`src/mcp/tools/workflow.py:71-104`）跑 EnergyPlus 前（line 85 `save_idf` 之前）只调 `validate_references()`（line 58，检查引用完整性），**不检查 IDF 是否含足够的几何对象**。

**危害**：
即使回跳机制失效（双时间线导致 surface 没建完，或 zone 静默放弃），残缺 IDF（0 zone 或 0 surface）也能进 EnergyPlus，产生：
- case_01 那种"0.18 秒空建筑空跑 → Completed Successfully 0 Severe → first_pass=True 假阳性"
- case_02 那种"8 zone / 0 surface → 8 Severe Fatal"

**这是最关键的兜底防线**——无论回跳机制怎样、无论 LLM 是否静默放弃，simulate 前确认"有 zone、有 surface"能拦住所有残缺模型假成功。

**修复方向**：
在 `run_simulation`（`workflow.py:71`，`save_idf` 之前）加完整性门槛，复用 `_idf_values`（`src/mcp/state.py:141`）统计对象数：
```python
def run_simulation(self, ...):
    errors = self.state.validate_references()
    # 【新增】几何完整性校验：至少要有 zone 和 surface
    zones = _idf_values(self.state.idf, "Zone")
    surfaces = _idf_values(self.state.idf, "BuildingSurface:Detailed")
    if len(zones) == 0:
        errors.append("Model has 0 Zone objects — cannot simulate an empty building.")
    if len(surfaces) == 0:
        errors.append("Model has 0 BuildingSurface:Detailed objects — zones have no envelope.")
    # 也可加：每个 zone 至少要有若干 surface（可选，更严格）
    if errors:
        return SimulationResponse(success=False, message="; ".join(errors), ...)
    # 继续原有 save_idf + run_idf 流程
```

**改动量**：小（workflow.py 加 ~10 行）
**风险**：低
**收益**：确定——拦住所有残缺模型假成功，case_01/case_02 都会正确报失败而非假阳性

---

### 问题 2（P1）：测试判定假阳性（不检查 zone/surface 数量）

**诊断根因**：D（`agent_test/DIAGNOSTICS.md`）

**现状**：
`run_robustness_test.py:476-480` 的 `simulation_ok` 判定：
```python
simulation_ok = produced_output and has_idf_in_msg and (not err_has_error_level)
```
- `produced_output`（`_check_simulation_output`，line 513-533）：只要存在 `eplusout.end`/`.sql`/`eplustbl.csv` 任一即 True（空建筑也会生成）
- `err_has_error_level`：case_01 空跑 0 Severe → False
- 三者全过 → case_01 判 `first_pass=True`（假阳性）

**危害**：
空建筑空跑被判成功，pass rate 数据失真，掩盖真实问题，误导优化方向。

**修复方向**：
在 `_check_simulation_output`（`agent_test/run_robustness_test.py:513`）或 `simulation_ok`（line 476）加门槛——要求仿真用的 IDF 至少含 1 个 Zone（或解析 `eplusout.eio` 的 `Zone Summary` 行，要求 Number of Zones > 0）：
```python
def _check_simulation_output(output_dir):
    ...
    # 【新增】检查 eplusout.eio 的 Zone Summary 行
    eio = output_dir / "eplusout.eio"
    has_real_zones = False
    if eio.exists():
        for line in eio.read_text(errors="ignore").splitlines():
            if line.strip().startswith("Zone Summary,"):
                # 形如 "Zone Summary,8,63,4"
                parts = line.split(",")
                if len(parts) > 1 and int(parts[1]) > 0:
                    has_real_zones = True
                break
    return bool(artifacts) and has_real_zones, artifacts, err_path
```

**改动量**：极小（测试脚本加 ~10 行）
**风险**：无（纯测试脚本，不影响 agent）
**收益**：让 pass rate 数据真实，暴露而非掩盖问题

---

### 问题 3（P2）：工具发现缺失立即自动回跳，不让 LLM 自愈

**诊断关联**：BACKHOP_IMPLEMENTATION_SPEC 第三节第 3 步

**现状**：
`invoke_with_self_repair`（`src/agent/nodes/_share.py:298-305`）里，`detect_upstream_gap` 检测到工具返回的 `missing_ref` 后**立即短路回跳**：
```python
gap = detect_upstream_gap(result, phase)
if gap:
    result["hop_request"] = gap
    return result   # 立即返回，错误信息没回 LLM
```
工具的 `missing_ref` 错误信息**根本没作为 ToolMessage 回到 phase 的 LLM**让它尝试自愈。

**危害**：
很多时候 LLM 本可以用别的现有对象替代（zone 名拼错了，list_zones 能发现正确的；或换个等价 schedule），但当前机制直接跳走，剥夺了自愈机会。这导致不必要的回跳，**放大了双时间线问题的触发频率**（回跳越频繁，双时间线竞态越多）。

**独立于双时间线**：即使保留回跳机制，也应该让错误先回 LLM 自愈。这是减少回跳次数的有效手段。

**修复方向**：
移除 `_share.py:298-305` 的自动短路，让 `missing_ref` 错误信息走正常的 self-repair 循环（`MAX_SELF_REPAIR_ROUNDS=2`）——先作为 HumanMessage 反馈给 LLM，让 LLM 尝试用现有对象替代。只有 LLM 自己调 `request_backhop` 工具（需新增）确认无法解决时才回跳。

注：完整实现需要新增 `request_backhop` 工具（详见 `BACKHOP_IMPLEMENTATION_SPEC.md` 第三节）。**精简版**（仅让 LLM 自愈、暂不引入 request_backhop）：把自动短路改成"错误进入 self-repair 反馈"，LLM 若 2 轮自愈后仍失败，再走现有的 detect_upstream_gap 回跳。

**改动量**：中（_share.py 改自动短路逻辑 + 各 phase prompt 提示 LLM 自愈）
**风险**：中（涉及 self-repair 核心逻辑，需测试）
**收益**：减少不必要回跳，降低双时间线触发频率，提升 LLM 自主解决问题能力

---

### 问题 4（P3）：surface 回跳判定过激

**诊断根因**：B（`agent_test/DIAGNOSTICS.md`）

**现状**：
surface 的 `detect_upstream_gap` 只要发现引用的 zone 名不匹配就立即回跳。case_02 第一轮 surface **一次 `create_surface` 都没调用**就 back-hop 了（run.log 行 206：`[surface] issuing back-hop Command -> zone`，而 15:01-15:02 区间 `Added BuildingSurface` = 0）。

**危害**：
surface 阶段的核心职责就是创建表面，但它因为"zone 名暂时对不上"就放弃整个阶段。即便没有双时间线，surface 也会因过激回跳而经常 0 产出。

**独立于双时间线**：这是回跳**判定阈值**问题，不是回跳**执行机制**问题。

**修复方向**：
surface（及其它 phase-2 节点）在 `detect_upstream_gap` 触发回跳前，加保护：若该阶段自身尚未创建任何对象（如 surface 的 `create_surface` 调用次数 = 0），**先尝试至少创建一批对象**（基于 surface_specs 里能匹配的 zone），而不是立刻回跳。只有"确实创建了部分但发现某 zone 缺失"才回跳。

或者：放宽 `detect_upstream_gap` 的触发条件——只在 self-repair 循环耗尽（`MAX_SELF_REPAIR_ROUNDS`）后才检测 gap，给 LLM 充分机会用现有 zone 建表面。

**改动量**：中（surface 节点 + 可能涉及 _share.py 的 detect 逻辑）
**风险**：中（回跳判定改动需充分测试）
**收益**：减少 surface 因过激回跳而 0 产出

---

### 问题 5（P4）：react.py llm_node 无重试，LLM 静默放弃无兜底

**诊断根因**：A 的源头（`agent_test/DIAGNOSTICS.md`）

**现状**：
`src/agent/react.py:46-49` 的 `llm_node`：
```python
def llm_node(state):
    messages = [SystemMessage(content=effective_prompt), *state.messages]
    response = llm_with_tools.invoke(messages)   # 无 try/except，无重试
    return {"messages": [response]}
```
LLM 返回无 tool_calls 的空响应（LLM 提供方偶发空回复、消息序列错乱）时，`tools_condition`（line 61）判定"无 tool_calls → END"，ReAct 子图立即结束，**阶段零工具调用静默结束**。

**危害**：
这是 zone 静默放弃（0 zone）的源头。zone_validator 能兜住 zone，但**其它 phase（material/schedule/construction/surface/fenestration/hvac/people/lights）同样可能静默放弃，没有校验模块兜底**。任一 phase 静默放弃都会导致模型残缺。

**独立于双时间线**：这是 LLM 调用鲁棒性问题，与回跳机制无关。

**修复方向**：
在 `llm_node`（`react.py:46`）加重试 + 异常处理：
- LLM 返回无 tool_calls 的空/纯文本响应时，注入一条 HumanMessage（"你必须调用工具完成当前阶段的任务，请重试"）并重新 invoke，最多 N 次
- LLM 抛 API 异常（`BadRequestError`/`RateLimitError`/`APITimeoutError`）时按指数退避重试

**改动量**：中（react.py 的 llm_node）
**风险**：中（需控制重试次数防死循环，配合 recursion_limit）
**收益**：减少所有 phase 的 LLM 静默放弃，从源头降低模型残缺概率

---

## 优先级总览与建议执行顺序

| 优先级 | 问题 | 改动量 | 收益 | 建议顺序理由 |
|--------|------|--------|------|------------|
| **P0** | 问题 1：simulate 前置完整性校验 | 小 | 确定——拦住所有残缺模型假成功 | **最该先做**：唯一能同时兜住 case_01（0 zone）和 case_02（0 surface）的防线，完全独立于回跳机制 |
| **P1** | 问题 2：测试判定加 zone 数量检查 | 极小 | 让 pass rate 数据真实 | 紧随 P0：让测试结果真实，才能客观评估后续修复效果 |
| **P2** | 问题 3：移除自动回跳短路，让 LLM 自愈 | 中 | 减少不必要回跳 | P0/P1 落实后：减少回跳次数 = 降低双时间线触发频率 |
| **P3** | 问题 4：surface 回跳判定加保护 | 中 | 减少 surface 0 产出 | 与 P2 相关（都是回跳判定优化） |
| **P4** | 问题 5：react.py llm_node 重试 | 中 | 减少 LLM 静默放弃 | 从源头降低残缺概率，可作为长期鲁棒性提升 |

**核心建议**：**P0（simulate 前置校验）+ P1（测试判定）是最该先做的一组**。它们改动最小、风险最低、收益最确定，且完全独立于回跳机制。落实后，即使暂时容忍双时间线：
- 残缺模型进不了 EnergyPlus（P0 拦住）
- 测试结果真实反映问题（P1 不再假阳性）
- 后续优化（P2-P4）的效果可以被客观度量

---

## 与回跳机制重构的关系

本文档的 5 个问题都**独立于** `docs/BACKHOP_IMPLEMENTATION_SPEC.md` 描述的回跳机制重构（方式 A：interrupt + 外层新 thread 重跑）。两者的关系：

- **如果先做本文档的 P0-P5，后做回跳重构**：P0（simulate 校验）和 P1（测试判定）会保留不变（它们与回跳无关）；P2-P4 的部分改动（如 request_backhop 工具、移除自动短路）会被回跳重构复用或替代。
- **如果先做回跳重构**：本文档的问题 1/2/5 仍需独立修复（它们与回跳无关）；问题 3/4 会被回跳重构自然解决（重构本身就把"自动回跳短路"改成"LLM 自愈 + request_backhop"）。

**建议**：先做 P0 + P1（独立、确定、低风险），再决定是否投入回跳重构（大改）还是继续做 P2-P4（在当前机制上渐进优化）。
