# 保留当前回跳机制的渐进修复计划

> **目的**：在暂不重构 `Command(goto=...)` 回跳机制的前提下，先修复当前 agent graph 中与残缺模型、测试假阳性、过早回跳、LLM 静默结束相关的问题。
>
> **策略**：不改 graph 拓扑，不引入 interrupt/new-thread 回跳。继续使用现有 `maybe_backhop`，但加强阶段完成度校验、仿真/测试兜底、自动回跳触发阈值和 ReAct 响应鲁棒性。

---

## 一、当前约束

本轮不处理 `Command(goto=...)` 造成的双时间线问题。也就是说：

- `construction/surface/fenestration/hvac/people/lights` 仍可通过 `maybe_backhop()` 发起现有回跳。
- `validate_node` 的 directed rollback 保持不变。
- `graph.py` 拓扑保持不变。
- 本轮重点是降低残缺模型进入仿真的概率，并让测试结果真实暴露失败。

---

## 二、已存在的 zone 校验基础

代码中已经有一个符合目标方向的 zone 校验模块：

- `src/agent/nodes/zone_validator.py`
- `src/agent/nodes/zone.py`

当前机制：

1. `zone_agent` 先运行主 ReAct agent，使用 `create_zone/list_zones/...` 修改 `local ConfigState`。
2. 主 ReAct 结束后，调用 `run_zone_validator(zone_specs, local, llm)`。
3. validator 是独立 LLM，只能调用 `approve` 或 `reject`，不创建/修改 zone。
4. 如果 reject，validator 返回具体 reasons。
5. `zone_agent` 把 reasons 作为 `HumanMessage` 反馈给主 ReAct agent，要求主 agent 使用 `update_zone/delete_zone/create_zone` 修复。
6. 最多重试 `MAX_ZONE_VALIDATION_ROUNDS = 3`。

这和目标方案一致：**审计模块只判断，不动手；主模块负责修复。**

本轮不需要从零实现 zone validator，而是补强它的测试与失败兜底。

---

## 三、实施计划

### P0：simulate 前置完整性校验

**目标**：任何残缺 IDF 都不能进入 EnergyPlus。

**位置**：

- `src/mcp/tools/workflow.py`
- `WorkflowTool.run_simulation()`

**新增校验**：

在 `save_idf` 和 `EnergyPlusRunner.run_idf()` 之前检查：

- 至少存在 1 个 `Zone`
- 至少存在 1 个 `BuildingSurface:Detailed`
- 每个 `Zone` 至少有 1 个关联 surface
- 推荐更严格：每个普通建筑 zone 至少有 4 个 surface；但第一版可以先用 `>=1`，避免误伤非常规模型

**错误信息要求**：

错误必须具体，可被 `simulate_node -> revise_node` 作为修复提示使用，例如：

```text
Model geometry incomplete: Zone 'Office_North' has 0 BuildingSurface:Detailed objects. Create wall/floor/roof surfaces before simulation.
```

**预期效果**：

- 0 zone 空建筑不会被 EnergyPlus 空跑成 success。
- 8 zone / 0 surface 这种中间态不会进入仿真。
- 即使双时间线暂时存在，simulate 抢跑也会被前置校验拦住。

---

### P1：测试判定加几何门槛

**目标**：robustness 测试不再把空建筑或残缺模型判为成功。

**位置**：

- `agent_test/run_robustness_test.py`
- `CaseHarness.finalize()`
- `_check_simulation_output()`

**修改建议**：

在 `simulation_ok` 判定中加入 IDF 几何检查：

- 从 simulate message 中解析 `idf=...`
- 加载该 IDF
- 统计：
  - `Zone` 数量
  - `BuildingSurface:Detailed` 数量
  - 每个 zone 的 surface 数量
- 若 `zone_count == 0` 或 `surface_count == 0`，`simulation_ok=False`

同时，输出物判定不要只接受 `eplustbl.csv`：

- `eplustbl.csv` 可以作为辅助产物
- 成功仿真最好要求存在 `eplusout.csv` 或 `eplusout.eso`
- 如果 EnergyPlus 成功但没有时间序列输出，需要明确记录为 `no_timeseries_output`

**预期效果**：

- case_01 这类 0 zone 空跑不再 `first_pass=True`
- pass rate 能真实反映建模质量

---

### P2：zone validator 测试与兜底补强

**目标**：验证你提出的“zone 节点后置判断 LLM”机制稳定工作。

现有 `zone_validator` 逻辑可以保留，但需要补测试和少量兜底。

**建议新增测试**：

1. `zone_specs` 要求 2 个 zone，实际 0 个 zone  
   预期：validator reject，reason 包含 “0 zones” 或 missing zone。

2. `zone_specs` 要求 `F1_Office` / `F1_Corridor`，实际只创建 `F1_Office`  
   预期：validator reject，指出 `F1_Corridor` missing。

3. `zone_specs` 要求 2 个 zone，实际 zone 名完全匹配  
   预期：validator approve。

4. 主 zone agent 第一次创建不全，validator reject 后主 agent 被再次调用  
   预期：第二轮能收到具体 feedback。

**测试方式**：

尽量不要真实调用外部 LLM。用 fake chat model 或 monkeypatch `run_zone_validator()` / `build_react_agent()` 验证控制流：

- validator reject 时，`zone_agent` 会向主 agent 注入 `HumanMessage`
- 达到最大轮数后不会死循环
- `upstream_request` 被消费时仍会清空

**兜底建议**：

如果 `MAX_ZONE_VALIDATION_ROUNDS` 耗尽仍 reject：

- 当前逻辑是 warning 后继续 pipeline
- 保留这个行为可以，但必须依赖 P0 simulate 前置校验兜底
- 可以额外写入 `validation_errors`，让后续 validate/日志更容易定位

---

### P3：自动回跳改为“延迟回跳”

**目标**：保留当前 `maybe_backhop`，但避免工具第一次返回 `missing_ref` 就立刻回跳。

**当前位置**：

- `src/agent/nodes/_share.py`
- `invoke_with_self_repair()`
- `detect_upstream_gap()`
- `maybe_backhop()`

**当前问题**：

`invoke_with_self_repair()` 在每轮 agent invoke 后立刻调用 `detect_upstream_gap(result, phase)`。一旦发现工具返回 `missing_ref`，就短路返回 `hop_request`，LLM 没机会根据工具错误自愈。

**修改方向**：

把回跳检测推迟到 self-repair 失败之后：

1. agent 第一次调用工具返回 `missing_ref`
2. 不立即 `return result`
3. 继续执行 `validate_references()` / scoped errors 检查
4. 如果存在 in-scope error，把错误反馈给 LLM，让它尝试修正引用
5. 最多 `MAX_SELF_REPAIR_ROUNDS` 轮
6. 仍失败时，再扫描最近结果中的 `missing_ref`，生成 `hop_request`
7. 节点继续调用现有 `maybe_backhop()`

**简化原则**：

本轮不新增 `request_backhop` 工具。  
完整 “LLM 主动 request_backhop” 留给未来回跳机制重构。

**预期效果**：

- zone 名拼写不一致时，surface/hvac 等节点有机会通过 `list_zones` 找到正确名字。
- construction/fenestration 有机会换用已有 construction/material。
- 减少不必要回跳，从而降低双时间线触发频率。

---

### P4：surface 过早回跳保护

**目标**：避免 surface 在 0 个 surface 创建时就直接回跳。

P3 延迟回跳已经能缓解这个问题，但 surface 可以额外加更明确的保护。

**建议策略**：

在 surface phase 判断是否允许发起 backhop 时，检查本阶段产出：

- 如果当前 `local` 中没有任何 `BuildingSurface:Detailed`
- 且 `surface_specs` 明确要求创建 surfaces
- 则不要在第一轮 missing zone/construction 时立即 backhop
- 先给主 surface LLM 一条强反馈：

```text
You have not created any BuildingSurface:Detailed objects yet. Use list_zones and list_constructions to map the available names, then create all surfaces that can be created. Only request/back-hop if a required upstream object is truly absent after this repair attempt.
```

**实现方式**：

可以放在 `_share.py` 的延迟回跳逻辑中做 phase-specific guard，也可以在 `surface_agent` 中检测。

建议第一版放在 `_share.py`，集中处理：

- `phase == "surface"`
- `local` 里 surface count 为 0
- 还有 repair rounds 可用
- 继续 repair，不生成 `hop_request`

---

### P5：ReAct 首轮无工具调用/空响应重试

**目标**：降低任意 phase LLM 静默结束导致 0 产出的概率。

**位置**：

- `src/agent/react.py`
- `build_react_agent()`
- 内部 `llm_node()`

**当前问题**：

如果 LLM 首轮返回：

- 空 content
- 无 tool_calls
- 或纯文本解释但没有调用工具

`tools_condition` 会直接 END。该 phase 可能 0 工具调用但 graph 不报错。

**修改策略**：

只针对“首轮无工具调用”重试，避免破坏正常 ReAct 收尾。

判定逻辑：

- 当前 ReAct state 中没有任何 ToolMessage
- 本次 AIMessage 没有 tool_calls
- 且 content 为空或明显只是解释/拒绝执行

处理：

1. 向消息中追加 HumanMessage：

```text
You have not called any tools yet. This phase must modify or inspect the model using the available tools. Call the appropriate create/list/update tools now; do not finish with text only.
```

2. 重新 invoke LLM
3. 最多重试 2 次
4. API 异常按指数退避重试

**不要做的事**：

- 不要在已经调用过工具后强制继续调用工具。此时无 tool_calls 是正常结束信号。
- 不要无限重试。

**预期效果**：

- 降低 zone/material/schedule/surface 等阶段 “0 trace 但正常结束” 的概率。
- zone validator 仍作为 zone 专属二次兜底。

---

## 四、建议执行顺序

### Step 1：先做 P0 + P1

原因：

- 改动小
- 风险低
- 立刻消除假成功
- 为后续优化提供可信测试指标

交付：

- `WorkflowTool.run_simulation()` 几何完整性校验
- `run_robustness_test.py` 几何判定
- 对应单元测试

### Step 2：补 P2 zone validator 测试

原因：

- 机制已有，但缺测试证明
- 与你的方案直接对应

交付：

- validator approve/reject 测试
- zone_agent reject 后重跑控制流测试

### Step 3：做 P3 + P4 延迟自动回跳

原因：

- 在不改 graph 的前提下减少过早回跳
- 直接针对 surface 0 产出问题

交付：

- `_share.py` 延迟 `detect_upstream_gap`
- surface 0 产出保护
- missing_ref 自愈后才 `maybe_backhop`

### Step 4：做 P5 ReAct 首轮重试

原因：

- 影响所有 phase，需要更谨慎测试
- 可以在 P0/P1 兜底存在后再引入

交付：

- `react.py` 首轮无 tool_calls 重试
- API 异常退避重试
- 不破坏正常 ReAct 收尾的测试

---

## 五、测试计划

### 单元测试

新增/补充：

- `WorkflowTool.run_simulation()` 在 0 zone 时失败
- `WorkflowTool.run_simulation()` 在 zone 无 surface 时失败
- robustness 判定遇到 0 zone IDF 时 `simulation_ok=False`
- zone validator approve/reject
- `invoke_with_self_repair()` 首轮 missing_ref 不立即生成 hop_request
- self-repair 耗尽后才生成 hop_request
- ReAct 首轮无 tool_calls 会重试
- ReAct 已有工具调用后无 tool_calls 会正常结束

### 集成/回归测试

用最小 prompt 或 mock LLM 验证：

- zone 第一次少建，validator 反馈后补建
- surface 第一次引用错误 zone，不立即回跳，先尝试自愈
- 残缺模型进入 simulate 时被前置校验拒绝

### robustness 测试观察指标

修改后重点观察：

- `simulation_ok` 是否不再出现 0 zone/0 surface 假成功
- `phase_tool_stats.zone.calls` 是否减少 0-call case
- `surface` 是否仍出现 0 surface 进入 simulate
- `rollback_rounds` 和 `sim_rounds` 是否能真实反映失败和恢复

---

## 六、不在本轮处理

以下问题保留到后续回跳重构：

- `Command(goto=...)` 双时间线根因
- interrupt/new-thread 回跳
- `request_backhop` 工具化主动回跳
- 多 backhop request 聚合
- active phase mask / 局部重跑

本轮目标是：**即使继续使用当前回跳机制，也不再让残缺模型假成功，并显著减少阶段静默失败和过早回跳。**
