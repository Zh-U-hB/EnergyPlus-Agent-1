# 鲁棒性测试诊断报告：残缺模型导致仿真假阳性

> **测试批次**：`agent_test/results/20260702_145517`（office/small 10 case 后台运行，因 10 分钟窗口超时被 SIGTERM，仅完成 case_01、case_02）
> **诊断日期**：2026-07-02
> **触发场景**：本次测试前刚提交了 commit `8245724`（SimpleGlazingSystem 单层规则 + WindowMaterial:Glazing + floor/roof 法线自动修复）。两个 case 都出现了"残缺模型（缺 zone 或缺 surface）却能跑通仿真并被判 first_pass=True"的假阳性。
> **与 commit `8245724` 的关系**：**无关**。这两个问题是既有的 agent graph 回环 / LLM 稳定性问题，在本次改动之前就已存在。相反，本次改动的正面信号在两个 case 的日志中都能观察到（LLM 正确使用 `create_glazing_layer_material` 构造真·双层窗；`eplusout.err` 中 `upside down` Warning = 0，证明 floor/roof 法线修复生效）。

---

## 摘要

| | case_01 | case_02 |
|---|---|---|
| 最终 IDF 缺失的对象 | **Zone、BuildingSurface**（0 zone / 0 surface） | **BuildingSurface、FenestrationSurface**（8 zone / 0 surface） |
| 仿真结果 | `Completed Successfully-- 0 Severe`（0.18 秒空跑） | `Fatal-- 8 Severe`（0.04 秒即终止） |
| 测试判定 | `first_pass=True`（**假阳性**） | `first_pass` 待定，但仿真确为 Fatal |
| 直接原因 | zone 并行分支 LLM 静默放弃（返回无 tool_calls 响应，零工具调用）；hvac 发现 missing Zone 后因**漏接 `maybe_backhop`** 无法回跳修复 | 第一轮 surface 在 `create_surface` 一次都没调用时就 back-hop 回 zone（surface 接了 maybe_backhop，回跳生效，但判定过激） |
| 共同根因 | ① phase-3 节点（hvac/people/lights）漏接回跳执行层 `maybe_backhop` ② LLM 异常响应时缺乏重试/兜底 ③ surface 回跳判定过激 ④ simulate 缺前置完整性校验 ⑤ 测试判定不查 zone 数量 |

**一句话**：两个 case 都是 agent graph 的某些阶段（zone / surface）在生产关键对象时"静默失败"（要么 LLM 放弃、要么过早 back-hop），本应由回跳机制修复，但 case_01 因 hvac 漏接 `maybe_backhop` 导致回跳从未发生、case_02 因回跳过激导致 surface 自身没机会创建。最终 IDF 缺失核心几何对象，但流程仍继续推进到仿真，产生无意义或误导性的结果。

---

## 现象

### 现象 1：case_01 只有一个 CSV，缺 PNG

`agent_test/results/20260702_145517/office/small/case_01/rep_0/` 的产物：

```
sim_out/
├── eplustbl.csv          ← 只有这一个 CSV（程序/输入校验类表格）
├── eplusout.err / .end / .eio / .audit / .bnd / .mdd / .mtd / .rdd / .rvaudit / .shd / .expidf
└── temp_20260702_145847.idf
# 缺失：eplusout.csv（时间序列）、eplusout.eso（原始数据）、top_view.png（建筑图）
```

run.log 末尾明确记录 PNG 渲染失败的原因：
```
2026-07-02 14:59:16.596 | WARNING | _render_case_top_view:571 -
  [office/small/case_01] top-view render failed:
  no zones/surfaces parsed from .../temp_20260702_145847.idf
2026-07-02 14:59:16.596 | INFO | run_one_case:641 -
  ===== CASE office/small/case_01 done: first_pass=True sim_ok=True rounds=0 (223.15s) =====
```

### 现象 2：case_02 的 IDF 有 zone 但没 surface

```
temp_20260702_150313.idf（83 对象）:
  Zone x8, People x8, Lights x8, HVACTemplate:Zone:IdealLoadsAirSystem x8,
  Construction x6, Schedule:Compact x6, Material x8 ...
  BuildingSurface:Detailed x0   ← 缺失
  FenestrationSurface:Detailed x0  ← 缺失
```

`eplusout.end`：`EnergyPlus Terminated--Fatal Error Detected. 42 Warning; 8 Severe Errors; Elapsed Time=0.04sec`

8 个 Severe 对应 8 个 zone 没有任何围护结构表面。

---

## case_01 详细诊断：zone 分支 LLM 静默放弃

### 证据 1：zone 阶段在整个 run.log 中零 trace

对 case_01 的 run.log 按阶段统计首次 tool trace：

| 阶段 | case_01（本次失败） | case_01（之前成功 run 20260701_202722） |
|---|---|---|
| intake | 有（含 1 次 empty reply 重试） | 有 |
| **zone** | **（完全没有任何 trace）** | ✅ 8 次 `create_zone -> True` + 1 次 `list_zones` |
| material | ✅ | ✅ |
| schedule | ✅ | ✅ |
| construction | ✅ | ✅ |
| surface | ✅（list_zones 返回空） | ✅ |
| fenestration | ✅（list_surfaces 返回空） | ✅ |
| hvac / people / lights | ✅（但发现 missing Zone） | ✅ |

zone 阶段连一次工具调用都没有，而同一 case 在之前的成功 run 里正常创建了 8 个 zone。

### 证据 2：graph 没有崩溃，说明 zone 分支没有抛异常

agent graph 的拓扑（`src/agent/graph.py:195-201`）是并行 fan-out：
```
intake → [zone, material, schedule]  (并行) → cross_ref_foundations (barrier 汇聚)
```

通过最小复现实验确认（LangGraph 1.1.8）：

```python
# 并行 fan-out，其中一个分支抛异常
def bad_b(state): raise RuntimeError('ZONE_LLM_CRASHED')
g.add_edge(START, 'a'); g.add_edge(START, 'b'); g.add_edge(START, 'c')
g.add_edge(['a','b','c'], 'join')
app.invoke(...)  # → GRAPH 崩溃: RuntimeError（无论有无 checkpointer）
```

**结论**：如果 zone 分支抛了异常，整个 graph 会崩溃，根本跑不到 analyze。但本次 run 正常跑完（run.log 第 993 行 `done: first_pass=True`），所以 **zone 分支绝对没有抛异常**。

### 证据 3：zone 的 ReAct agent 在 LLM 返回无 tool_calls 时会立即结束

zone 的 ReAct 子图（`src/agent/react.py:46-61`）：
```python
def llm_node(state):
    response = llm_with_tools.invoke(messages)  # ← 无 try/except，无重试
    return {"messages": [response]}

builder.add_conditional_edges("llm", tools_condition, ["tools", END])
# tools_condition: 最后一条 AIMessage 含 tool_calls → "tools"；否则 → END
```

如果 LLM 返回一条**不含 tool_calls 的 AIMessage**（空内容、纯文本、或被 API 干扰的异常响应），`tools_condition` 直接路由到 `END`，ReAct 子图立即结束，**零工具调用、零 trace、不抛异常**。

这完美解释了"zone 既没执行（无 trace）又没让 graph 崩溃"的现象。

### 证据 4：zone_specs 本身不为空（排除 specs 缺失）

复现 intake 调用，确认 case_01 的 zone_specs 正常产出（1809 字符，详细列出 8 个 zone 的名字、尺寸、位置）。所以 zone agent 拿到的是有效 specs，是 **LLM 在 zone 分支的首次调用就放弃了工具调用**。

### 证据 5：eio 证实仿真跑的是空建筑

```
本次 case_01 eio:  Zone Summary,0,0,0      （0 zone / 0 surface）
正常 case_01 eio:  Zone Summary,8,63,4     （8 zone / 63 surface）
```

仿真耗时 0.18 秒（正常 case 约 2.27 秒），本质是空建筑空跑。因为没有 zone，没有热平衡计算，EnergyPlus 自然不报 Severe/Fatal，输出 `Completed Successfully-- 0 Severe`。

### 证据 6：intake 有过 empty LLM reply 重试（根因线索）

```
run.log 第 5 行: intake_node: empty LLM reply (attempt 1/4), retrying in 2s
```

同一次测试的 case_02 直接抛了 `openai.BadRequestError: assistant message with 'tool_calls' must be followed by tool messages`（LLM 提供方消息序列错乱）。这强烈提示本次测试期间 **LLM 提供方那侧存在请求序列错乱 / 限流**，zone 分支的并发 LLM 调用很可能也受此影响，返回了无 tool_calls 的异常响应。

### 证据 7（决定性）：hvac 节点没有调用回跳机制，回跳从未真正发生

> **这一条纠正了报告早期版本里"回跳后 zone 仍没创建"的不准确表述。实际情况是：回跳根本没有发生。**

run.log 第 491 行看起来像是一次成功的回跳：
```
2026-07-02 14:58:47.795 | INFO | src.agent.nodes._share:invoke_with_self_repair:301 -
  [hvac] upstream gap detected (missing Zone 'Office_North') -> hop to zone
```

但这句日志**极具误导性**。它来自 `invoke_with_self_repair`（`_share.py:301`），该函数检测到 gap 后只是**记日志 + 把 `hop_request` 塞进返回的 result 字典**（`_share.py:300`），**并不发起 `Command(goto=...)`**。真正把 `hop_request` 转成 `Command(goto=<earlier phase>)` 的是另一个函数 `maybe_backhop`（`_share.py:402-449`），它会打印一句不同的日志 `issuing back-hop Command -> ...`（`_share.py:435`）。

case_01 run.log 统计：
- `upstream gap detected`（invoke_with_self_repair 记录）：**1 次**
- `issuing back-hop Command`（maybe_backhop 真正发起）：**0 次**

也就是说，hvac 检测到了 `missing Zone 'Office_North'`，但**从未真正回跳到 zone**。

**根因是 hvac 节点（以及 people / lights 节点）缺失了 `maybe_backhop` 调用。** 回跳机制分两层：

| 层 | 函数 | 职责 | 在哪 |
|---|---|---|---|
| 检测层 | `invoke_with_self_repair` 内的 `detect_upstream_gap` | 发现缺失的上游对象 → 记日志 + 把 `hop_request` 放进 result 字典 | `_share.py:298-305` |
| 执行层 | `maybe_backhop` | 读 result 里的 `hop_request` → 发起 `Command(goto=<earlier phase>)` | `_share.py:402-449` |

**只有两层都接上，回跳才会真正发生。** 对照各节点：

| 节点 | 调用 `invoke_with_self_repair`？ | 调用 `maybe_backhop`？ | 回跳能否生效？ |
|---|---|---|---|
| construction | ✅ | ✅（`construction.py:110`） | ✅ 能 |
| surface | ✅ | ✅（`surface.py:106`） | ✅ 能 |
| fenestration | ✅ | ✅（`fenestration.py:104`） | ✅ 能 |
| **hvac** | ✅ | ❌ **缺失** | ❌ **不能** |
| **people** | ✅ | ❌ **缺失** | ❌ **不能** |
| **lights** | ✅ | ❌ **缺失** | ❌ **不能** |

`surface.py:106-108` 的正确写法（对照参考）：
```python
hop = maybe_backhop(result, state, local, "surface")
if hop is not None:
    return hop   # ← 真正发起 Command(goto=...)，回跳生效
```

而 `hvac.py:73` 直接 `return AgentStateUpdate(...)`，**完全没有这两行**，导致 hvac 检测到的 `hop_request` 被无声丢弃。people / lights 同理。

> **注**：construction / surface / fenestration 之所以接了 `maybe_backhop`，是因为它们引用的上游（material / zone / surface / construction）可能缺失；而 hvac / people / lights 引用的上游（zone / schedule）同样可能缺失，却漏接了。这是一个对称性遗漏——很可能是当初实现回跳机制时，只覆盖了 phase-2 的三个节点（construction/surface/fenestration），忘了 phase-3 的 hvac/people/lights。

所以回答标题的问题"为什么 hvac 引用不存在的 zone 时返回到 zone 却没执行 create_zone"——**因为根本没返回到 zone**。回跳机制的设计目的是解决这种情况，但 hvac 节点漏接了执行层（`maybe_backhop`），导致检测层发现的 gap 被丢弃，流程直接往下走到 simulate，带着 0 个 zone 跑了空建筑仿真。

### case_01 因果链（修正版）

```
intake 阶段 LLM empty reply 重试（LLM 提供方状态不稳定）
        │
        ▼
zone 并行分支的 LLM 调用受波及，返回无 tool_calls 的 AIMessage
        │
        ▼
tools_condition 判定"无 tool_calls → END"，zone ReAct 立即结束（零工具调用）
        │
        ▼
zone 返回空 config（0 zone），汇合到 cross_ref_foundations
        │
        ▼
construction / surface / fenestration 全部基于"0 zone"往下走（list_zones 返回空）
（注：surface 虽然接了 maybe_backhop，但因 surface 自身也没创建任何对象、
 且 detect_upstream_gap 在 surface 阶段没触发 gap，所以 surface 没 back-hop）
        │
        ▼
hvac 创建 IdealLoads 时引用 Office_North（来自 hvac_specs），发现 missing Zone
        │
        ▼ 14:58:47.795
invoke_with_self_repair 检测到 gap，记日志 "[hvac] upstream gap ... -> hop to zone"，
把 hop_request 放进 result 字典
        │
        ▼
【BUG】hvac 节点没有调用 maybe_backhop，hop_request 被丢弃，
返回普通 AgentStateUpdate（无 Command）—— 回跳从未真正发生
        │
        ▼
流程继续：people → lights → cross_ref_complete → validate → simulate
（run.log 14:58:47.797 之后只见重复 add 上游对象，无 create_zone，因为没回到 zone）
        │
        ▼ 14:58:47.839
保存最终 IDF（52 对象，0 zone / 0 surface）
        │
        ▼ 14:58:47.845
启动 EnergyPlus → 0 zone 空建筑 → 0.18 秒空跑 → Completed Successfully, 0 Severe
        │
        ▼
测试判定 simulation_ok=True（只检查"有输出文件 + 无 Severe"，不检查 zone 数量）
        │
        ▼
first_pass=True（假阳性）
```

### 现象解释

| 现象 | 成因 |
|---|---|
| 只有一个 CSV（`eplustbl.csv`） | 0 zone → 无时间序列变量可记录 → 不生成 `eplusout.csv`/`eplusout.eso`；`eplustbl.csv` 是输入校验类表格，空建筑也会生成表头占位 |
| 缺 `top_view.png` | 渲染器 `parse_idf_geometry` 解析最终 IDF，发现 0 zone/surface，抛 `no zones/surfaces parsed`（best-effort，不影响判定） |
| `first_pass=True` | 测试的 `simulation_ok` 判定（`run_robustness_test.py:476-480`）只检查 `produced_output and has_idf_in_msg and not err_has_error_level`，**不检查 zone/surface 数量**，空跑被误判成功 |

---

## case_02 详细诊断：surface 过早 back-hop + 中间状态被仿真

### 证据 1：第一轮 surface 一个 surface 都没创建就 back-hop 回 zone

run.log 第 206 行（核心证据）：
```
2026-07-02 15:01:33.849 | INFO | src.agent.nodes._share:maybe_backhop:434 -
  [surface] issuing back-hop Command -> zone (hop_count 0->1)
```

统计第一轮 surface 阶段（15:01:24 ~ 15:01:33）创建的 BuildingSurface 数量：**0 个**。
而第一轮 surface 之前 zone 已经创建过（但名字与下游 specs 预期的不一致）。

surface 阶段的 `detect_upstream_gap` / `maybe_backhop` 检测到"引用的 zone 名不存在"，**立即回跳，根本没尝试创建任何 surface**。

### 证据 2：完整时间线（关键证据）

| 时间 | 事件 | 对象数 / 结果 |
|------|------|--------|
| 15:00 ~ 15:01 | 第一轮 zone/material/schedule 并行 | zone 创建（名字与下游预期不符） |
| 15:01:24 | 第一轮 surface 启动，调 list_zones | - |
| **15:01:33.849** | **`[surface] issuing back-hop Command -> zone`** | **surface 创建数 = 0，直接回跳** |
| 15:01:35 | fenestration 启动 | list_surfaces 空，也没创建（create_fenestration 总次数 = 0） |
| 15:02:42 | 回跳后第二轮 zone 重建 | OpenPlan_Office / Private_Office_1..3 / Meeting_Room 等 8 个 zone |
| 15:02:46 | hvac / people / lights | 基于这些 zone 创建 HVAC |
| 15:03:13.318 | 保存 IDF → 50 对象 | 50 |
| 15:03:13.336 | 保存 IDF → 66 对象 | 66 |
| **15:03:13.390** | **保存最终 IDF → 83 对象 → 启动 EnergyPlus** | **83 对象，0 surface** |
| 15:03:13.399 | `Starting EnergyPlus simulation...` | - |
| 15:03:13.665 | `Program terminated: EnergyPlus Terminated--Error(s) Detected` | 退出码 1 |
| 15:03:13.665 | `EnergyPlus exited with code 1` | 8 Severe（每个 zone 无表面） |
| 15:03 ~ 15:05:54 | **第二轮 surface 还在创建**（Corridor_West_Wall / OpenPlan_Office_Roof 等，共 12 个） | 但仿真早已结束失败 |

### 证据 3：仿真用的 IDF 是 surface 第二轮还没开始的中间状态

`temp_20260702_150313.idf`（83 对象，保存于 15:03:13.390）内容：
- Zone x8 ✅、People x8 ✅、Lights x8 ✅、HVACTemplate:IdealLoads x8 ✅
- Construction x6 ✅、Schedule x6 ✅、Material x8 ✅
- **BuildingSurface x0 ❌、FenestrationSurface x0 ❌**

而第二轮 surface 一直创建到 15:05:51（run.log 最后一行）——**保存 IDF 时 surface 远未完成**。

### 证据 4：graph 拓扑本不该让 simulate 与 surface 并行

`src/agent/graph.py:209-221` 拓扑是严格串行：
```
surface → fenestration → [hvac, people, lights] → cross_ref_complete → validate → simulate → analyze → END
```

正常情况下 simulate 在 validate 之后才跑，不可能与 surface 并行。本次 simulate 在 15:03:13 跑、surface 在 15:05 才建完，**是因为 simulate 跑的是第一轮回环链路中那个"surface 已 back-hop、surface 还没重建"的残缺状态**。这是回环（back-hop）机制与 simulate 触发时序的冲突。

### case_02 因果链

```
第一轮 zone 创建（名字与 surface_specs/hvac_specs 预期的不一致）
        │
        ▼
第一轮 surface 启动，detect_upstream_gap 发现引用的 zone 名不存在
        │
        ▼ 15:01:33.849
[surface] issuing back-hop Command -> zone
（surface 一次 create_surface 都没调用，直接回跳）
        │
        ▼
回环链路重新触发 zone（15:02:42 重建 8 个 zone）→ hvac/people/lights
        │
        ▼
回环链路推进到 validate → simulate
（此时第二轮 surface 还没开始）
        │
        ▼ 15:03:13.390
simulate 保存残缺 IDF（83 对象，8 zone 但 0 surface）→ 启动 EnergyPlus
        │
        ▼ 15:03:13.665
EnergyPlus Fatal（8 Severe，每个 zone 无围护表面），退出码 1
        │
        ▼
（同时）第二轮 surface 在 15:03~15:05:54 继续创建 12 个 surface，但为时已晚
```

### 现象解释

| 现象 | 成因 |
|---|---|
| IDF 有 zone 但没 surface | 第一轮 surface 在 back-hop 前 0 创建；最终保存的 IDF 处于"zone 已重建、surface 第二轮未开始"的中间状态 |
| 仿真 Fatal（8 Severe） | 8 个 zone 没有任何 BuildingSurface，EnergyPlus 无法构建热平衡 |
| 中间状态被仿真 | simulate 节点在回环链路推进到它时立即跑，没有"等待 surface 完成"或"前置校验 IDF 完整性"的机制 |

---

## 共同根因

两个 case 表现不同（case_01 缺 zone，case_02 缺 surface），但根因同源，都属于 **agent graph 在阶段失败时的容错/恢复机制不足**：

### 根因 A：并行 fan-out 分支的 LLM 调用缺乏重试/兜底（case_01 上游诱因）

`src/agent/react.py:46-49` 的 `llm_node`：
```python
def llm_node(state):
    response = llm_with_tools.invoke(messages)  # 无 try/except，无重试
    return {"messages": [response]}
```

LLM 返回无 tool_calls 的异常响应（空内容、纯文本、API 序列错乱）时，`tools_condition` 直接 END，阶段零工具调用静默结束。没有任何机制检测"该阶段是否真的完成了它的任务（创建了一定数量的对象）"。这是 zone 分支产出 0 个 zone、进而触发下游 hvac 发现 `missing Zone` 的源头。

### 根因 B：surface 阶段 back-hop 判定过于激进（case_02 主因）

`src/agent/nodes/_share.py` 的 `detect_upstream_gap` / `maybe_backhop`：surface 阶段只要发现引用的 zone 名不存在就立即回跳，**不留任何机会让 surface 自己创建表面**。但 surface 的核心职责就是创建表面，它的 zone 引用是通过 surface_specs 间接来的，不应该因为"zone 名暂时不匹配"就放弃整个 surface 阶段。

> 注：case_02 里 surface **正确**调用了 `maybe_backhop`（run.log 有 `issuing back-hop Command -> zone`），回跳机制本身生效了，问题在于"判定阈值过激"。这与 case_01 的根因 F（hvac 漏接 maybe_backhop）是两个不同的缺陷。

### 根因 F（决定性）：hvac / people / lights 节点漏接了回跳执行层 `maybe_backhop`（case_01 回跳失效的真凶）

回跳机制分两层（见 case_01 证据 7 的详述）：
- **检测层** `invoke_with_self_repair` 内的 `detect_upstream_gap`（`_share.py:298-305`）：发现缺失的上游对象 → 记日志 + 把 `hop_request` 放进 result 字典。
- **执行层** `maybe_backhop`（`_share.py:402-449`）：读 result 里的 `hop_request` → 发起 `Command(goto=<earlier phase>)`。

**只有两层都接上，回跳才会真正发生。** 但 phase-3 的三个节点（hvac / people / lights）只调用了 `invoke_with_self_repair`（检测层），**全部漏接了 `maybe_backhop`（执行层）**：

| 节点 | 检测层 `invoke_with_self_repair` | 执行层 `maybe_backhop` | 回跳能否生效 |
|---|---|---|---|
| construction | ✅ | ✅ `construction.py:110` | ✅ |
| surface | ✅ | ✅ `surface.py:106` | ✅ |
| fenestration | ✅ | ✅ `fenestration.py:104` | ✅ |
| **hvac** | ✅ `hvac.py:58` | ❌ **缺失** | ❌ |
| **people** | ✅ | ❌ **缺失** | ❌ |
| **lights** | ✅ | ❌ **缺失** | ❌ |

case_01 里 hvac 检测到了 `missing Zone 'Office_North'`，日志也打印了 `-> hop to zone`，但因为 hvac 节点（`hvac.py:45-78`）直接 `return AgentStateUpdate(...)` 而没有 `maybe_backhop` 那两行，**`hop_request` 被无声丢弃，回跳从未发生**。流程带着 0 个 zone 一路走到 simulate，跑了空建筑仿真。

这是一个**对称性遗漏**：当初实现回跳机制时只覆盖了 phase-2（construction/surface/fenestration），漏掉了结构对称的 phase-3（hvac/people/lights）。phase-3 节点同样会引用可能缺失的上游（zone / schedule），却无法发起回跳去修复。

### 根因 C：simulate 缺少前置完整性校验（两个 case 共同）

`simulate` 节点（`src/agent/nodes/simulate.py`）/ `WorkflowTool.run_simulation`（`src/mcp/tools/workflow.py`）在跑 EnergyPlus 前只调用 `validate_references()`（检查引用完整性），**不检查 IDF 是否含足够的几何对象（≥1 zone、每个 zone ≥ N surface）**。导致残缺中间状态（0 zone 或 0 surface）也能进 EnergyPlus，产生无意义的空跑或误导性 Fatal。

### 根因 D：测试判定的假阳性（两个 case 共同）

`run_robustness_test.py:476-480` 的 `simulation_ok` 判定：
```python
simulation_ok = produced_output and has_idf_in_msg and (not err_has_error_level)
```
- `produced_output`：只要存在 `eplusout.end`/`.sql`/`eplustbl.csv` 任一即 True（空建筑也会生成）
- `err_has_error_level`：case_01 空跑 0 Severe → False

三者全过 → 假阳性。**判定逻辑没检查"有 zone / 有真实能耗数据"**。

### 根因 E：LLM 提供方状态不稳定（外部诱因）

本次测试期间 intake 出现 empty reply 重试（case_01），case_02 直接抛 `openai.BadRequestError: assistant message with 'tool_calls' must be followed by tool messages`。这表明 LLM 提供方那侧存在请求序列错乱 / 限流，是触发根因 A（zone 静默放弃）的外部诱因。

---

## 验证方法（可复现）

### 复现 case_01 的"zone 静默放弃"

1. 在 `src/agent/react.py:llm_node` 临时加入日志，打印每次 LLM 响应的 `tool_calls` 和 `content` 长度。
2. 重跑 `python agent_test/run_robustness_test.py --only "office/small/case_01"`。
3. 观察 zone 分支的 LLM 响应是否为无 tool_calls 的空/纯文本消息。

### 复现 case_02 的"surface 过早 back-hop"

1. 在 `src/agent/nodes/_share.py:maybe_backhop` 加日志，打印 back-hop 时的 `gap` 详情和当前阶段已创建的对象数。
2. 重跑 `python agent_test/run_robustness_test.py --only "office/small/case_02"`。
3. 观察第一轮 surface 在 back-hop 时 `create_surface` 调用次数是否为 0。

### 复现 LangGraph 并行分支异常行为

```python
from langgraph.graph import StateGraph, START, END
from typing import Annotated, TypedDict
from operator import add

class S(TypedDict):
    vals: Annotated[list, add]

def good_a(state): return {'vals': ['A_ok']}
def bad_b(state): raise RuntimeError('ZONE_LLM_CRASHED')
def good_c(state): return {'vals': ['C_ok']}

g = StateGraph(S)
g.add_node('a', good_a); g.add_node('b', bad_b); g.add_node('c', good_c)
g.add_edge(START, 'a'); g.add_edge(START, 'b'); g.add_edge(START, 'c')
# 结果：GRAPH 崩溃: RuntimeError（无论有无 InMemorySaver checkpointer）
# → 证明 zone 分支若抛异常，整个 graph 会崩；本次没崩 ⇒ zone 没抛异常
```

---

## 建议修复方向（按优先级，待评审）

### 方向 1（最高优先级）：给 hvac / people / lights 接上 `maybe_backhop`（根因 F，case_01 回跳失效的真凶）

这是最小、最直接、最对症的修复。当前 `hvac.py` / `people.py` / `lights.py` 在 `invoke_with_self_repair` 之后直接 `return AgentStateUpdate(...)`，丢弃了 `hop_request`。只需补上和 surface/construction/fenestration 完全一致的两行：

```python
# hvac.py / people.py / lights.py，在 invoke_with_self_repair 之后、return AgentStateUpdate 之前
hop = maybe_backhop(result, state, local, "<phase>")
if hop is not None:
    return hop
```

- **收益**：让 hvac/people/lights 检测到缺失的 zone/schedule 时能真正回跳到对应上游阶段重建，而不是带着残缺状态硬走到 simulate。直接修复 case_01 的"回跳从未发生"。
- **改动位置**：`src/agent/nodes/hvac.py`、`src/agent/nodes/people.py`、`src/agent/nodes/lights.py`，各加 2-3 行 + import `maybe_backhop` + 把返回类型签名改成 `Command[...] | AgentStateUpdate`（参考 `surface.py:71`）。
- **风险**：极低，纯补齐对称性，与已验证的 surface/construction/fenestration 写法完全一致。需确认这三个节点的 `_Route` Literal 包含其回跳目标（zone / schedule）。

### 方向 2（高优先级）：simulate 前置完整性校验（根因 C）
在 `WorkflowTool.run_simulation`（`src/mcp/tools/workflow.py:71-104`）跑 EnergyPlus 前，加一道门槛：要求 IDF 至少含 1 个 Zone、且每个 Zone 至少有若干 BuildingSurface。不满足则不仿真，直接返回失败并附带缺什么对象的明确错误，触发正常的回环修复。
- **收益**：作为兜底防线，即使回跳机制（方向 1）或 LLM 稳定性（方向 3）失效，残缺模型也不会进 EnergyPlus 产生假阳性；同时拦住 case_02 的"中间状态被仿真"。
- **改动位置**：`src/mcp/tools/workflow.py` 的 `run_simulation`，复用 `_idf_values` 统计对象数。

### 方向 3（高优先级）：react.py llm_node 鲁棒性增强（根因 A）
在 `src/agent/react.py:46-49` 的 `llm_node` 加重试 + 异常处理：
- LLM 返回无 tool_calls 的空/纯文本响应时，注入一条 HumanMessage（"你必须调用工具完成当前阶段的任务，请重试"）并重新 invoke，最多 N 次。
- LLM 抛 API 异常（`BadRequestError`/`RateLimitError`/`APITimeoutError`）时按指数退避重试。
- **收益**：减少 zone 分支"静默放弃"的源头（根因 A），从源头降低 hvac 发现 missing Zone 的概率。
- **改动位置**：`src/agent/react.py` 的 `llm_node`。

### 方向 4（中优先级）：back-hop 判定加保护（根因 B）
在 `src/agent/nodes/_share.py` 的 `maybe_backhop` / `detect_upstream_gap` 加保护：surface 等阶段在 back-hop 前，若该阶段自身尚未创建任何对象，则**先尝试至少创建一批对象**，而不是立刻回跳。
- **收益**：命中 case_02 的"surface 过早 back-hop"。
- **风险**：改动涉及回环核心逻辑，需谨慎，建议配合充分的回环测试。

### 方向 5（中优先级）：intake 输出校验
在 `src/agent/nodes/intake.py` 的 structured-output 解析成功后，检查关键字段（`zone_specs`/`material_specs`/`surface_specs` 等）非空且非占位符，否则视为失败重试。
- **收益**：避免"intake 成功但 specs 残缺"导致下游名字不一致。
- **改动位置**：`src/agent/nodes/intake.py:204-212`。

### 方向 6（低优先级）：测试判定加固
在 `run_robustness_test.py` 的 `_check_simulation_output`（513-533 行）或 `simulation_ok`（476-480 行）加门槛：要求 IDF 至少含 1 个 Zone，或 `eplusout.eio` 的 `Zone Summary` 行 Number of Zones > 0，否则判 `simulation_ok=False`。
- **收益**：让假阳性在测试报告中显式暴露，便于及早发现上游失败。

---

## 附：本次 commit `8245744` 的正面验证信号

尽管两个 case 出现了与本次改动无关的残缺模型问题，但日志中能观察到本次修复（SimpleGlazingSystem 单层规则 + WindowMaterial:Glazing + floor/roof 法线修复）的正面效果：

1. **case_01 run.log 第 40-42 行**：LLM 正确调用了新工具 `create_glazing_layer_material`（创建 `Glass_Clear_3mm`）和 `create_airgap_material`（创建 `Air_Gap_13mm`），用于构造真·双层窗。这正是 commit `8245744` 的设计目标——让 LLM 用真·逐层玻璃（WindowMaterial:Glazing）+ AirGap 合法构造双层窗，而不是把 SimpleGlazingSystem 当成单片玻璃拼层。
2. **case_01 `eplusout.err`**：`upside down` Warning 数 = 0（之前每个 case 都有十几个 "Floor/Roof is upside down" Warning），证明 floor/roof 法线自动修复（`src/mcp/state.py` validate_references 中新增的自动反转逻辑）生效。

这两个信号说明 commit `8245744` 的三处修复本身工作正常，本报告诊断的两个 case 问题属于独立的、既有的 agent graph 稳定性缺陷。
