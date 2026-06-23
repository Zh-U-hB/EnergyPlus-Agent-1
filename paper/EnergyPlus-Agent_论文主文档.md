# EnergyPlus\-Agent\_论文主文档

# **EnergyPlus\-Agent：面向人机协同设计的 LLM 建筑能耗建模与仿真智能体**

## **EnergyPlus\-Agent：面向人机协同设计的 LLM 建筑能耗建模与仿真智能体**

## 摘要（待写）

本文提出 EnergyPlus\-Agent，一个面向建筑设计阶段的检索增强型建筑能耗模拟智能体系统。系统结合大语言模型、LangGraph 多阶段智能体流程、MCP 工具编排、RAG 专业知识库、Pydantic/IDF 校验、EnergyPlus 仿真执行和结果解析可视化，实现从自然语言建筑描述到仿真结果反馈的闭环。后续摘要需要补充案例设置、实验指标和主要结果。

## 关键词（暂定）

建筑能耗建模；EnergyPlus；大语言模型；多智能体系统；检索增强生成；Model Context Protocol；早期设计；人机协同

## 论文结构总览

1. Introduction：说明建筑能耗建模的重要性、EnergyPlus 使用门槛、LLM agent 的机会与不足，并提出本文系统。

2. Literature Review：梳理 LLM \+ BEM、EnergyPlus 自动建模、多智能体、MCP、RAG、BIM/早期设计优化等相关工作。

3. Methodology：说明系统架构、多节点 agent 编排、MCP 工具层、RAG 知识库、输入正确性保障、仿真执行和结果解析。

4. Results：通过案例展示从自然语言输入到 EnergyPlus 仿真结果的完整流程，对比传统流程、with/without RAG 和可能的自优化结果。

5. Discussion：讨论系统意义、为什么能够降低门槛和幻觉、当前局限与未来工作。

6. Conclusion：总结降低建模门槛、提升效率和减少参数幻觉的贡献。

7. References：整理引用文献和项目来源。

# 1\. Introduction

建筑行业是全球能源消耗和碳排放的重要来源。根据 GlobalABC/UNEP 发布的建筑与建造全球状态报告，建筑相关活动约占全球能源需求的 32%，并产生约 34% 的能源相关二氧化碳排放。因此，在建筑设计阶段引入可靠的能耗评估方法，对于降低运行能耗、优化围护结构与系统方案、支持低碳设计决策具有重要意义。建筑能耗建模（Building Energy Modeling, BEM）正是在这一背景下形成的关键技术路径。以 EnergyPlus 为代表的物理仿真引擎能够对建筑热过程、围护结构传热、人员与设备负荷、HVAC 系统以及气象条件进行较精细的模拟，是建筑性能分析和节能优化中的重要工具。

然而，EnergyPlus 的强大能力也伴随着较高的使用门槛。一个可运行的 EnergyPlus 模型通常需要同时定义建筑几何、热区、材料、构造层、窗户、运行时间表、人员与照明负荷、HVAC 系统、输出变量和气象文件等内容。这些对象之间存在大量跨引用关系，例如表面必须引用已有热区和构造，构造必须引用已有材料，HVAC 系统必须引用已有热区、恒温器和时间表。任何字段格式、对象命名或引用关系的错误，都可能导致模型无法通过校验或仿真失败。对于建筑师和早期设计者而言，这一过程不仅耗时，而且需要持续依赖能耗建模专家，限制了 BEM 在方案早期快速迭代中的使用。

近年来，大语言模型（Large Language Models, LLMs）的发展为自动化复杂工程建模任务提供了新的可能。早期研究已经开始探索从自然语言到 EnergyPlus 模型的自动生成。例如，EPlus\-LLM 将大型语言模型用于从建筑描述生成 EnergyPlus 模型，展示了 LLM 在减少人工建模工作量方面的潜力；也有研究提出面向几何无关 IDF 生成的 AI 自动化方法，利用 LLM、提示模板和 EnergyPlus 模型库，从自由文本中生成可仿真的建筑能耗模型。这类工作证明了 LLM 可以承担部分模型生成任务，但其重点通常在于把文本转换为模型文件或模板化对象，较少讨论设计者在多轮方案探索中如何持续修正模型、查询专业参数并理解仿真反馈。

随着 agentic workflow 和工具调用能力的发展，研究重点进一步从“让 LLM 直接生成模型”转向“让 LLM 调用工具完成建模过程”。例如，有研究提出通过 agentic workflow 自动开发并调试建筑能耗模型，将传统 BEM 中反复修改、检查和运行的过程转化为可由 LLM agent 协调的工作流；LLM\-Agent\-UMI 则从 urban modeling interface 的角度，利用 LLM agent 的 schema 与工具库提升城市建筑能耗分析与建模任务的自动化程度。与此同时，面向 EnergyPlus 的 MCP 基础设施也开始出现。EnergyPlus\-MCP 将 EnergyPlus 建模、仿真和结果处理能力封装为 Model Context Protocol server，使 LLM 能够通过标准化上下文协议调用 EnergyPlus 相关工具；后续 MCP\-enabled agentic AI workflow 进一步说明了 MCP 在建筑能耗建模中的工具互操作潜力。这些研究表明，LLM 在 BEM 中的角色正在从“文本生成器”转向“工具协调者”。

多智能体系统也被用于更复杂的建筑性能分析任务。Data2BEM 通过多智能体框架从图纸、技术规格书和传感器数据中生成并校准既有建筑能耗模型，显著压缩了传统人工建模时间；AutoBEE 利用分层多智能体系统完成从自然语言指令到建筑能耗与环境性能报告的自动分析；BEM\-AI 进一步将 Agent\-to\-Agent 通信与 Model Context Protocol 结合，探索了动态多智能体建筑能耗建模流程。近期也有研究将 Retrieval\-Augmented Generation 与 MCP 结合，用于城市尺度建筑能耗仿真和韧性评估，说明检索增强和工具协议正在成为 LLM\-BEM 系统的重要发展方向。此外，Text2BIM 展示了自然语言到 BIM 模型生成的潜力，EnergAI 则将 LLM 引入早期建筑体量生成与能耗优化。这些研究共同表明，LLM agent 能够降低建筑性能分析的操作门槛，并在一定程度上缩短建模和分析时间。

尽管如此，现有研究仍存在若干不足。首先，许多工作主要面向既有建筑审计、改造分析、城市尺度分析或自动报告生成，而设计阶段的 BEM 需求并不只是一次性生成模型，更重要的是支持设计者在方案尚不确定时进行多轮交互、快速修改和反复试错。其次，LLM 在生成材料热工参数、构造层次和运行时间表时容易依赖语言模型内部知识或经验默认值，若缺少专业数据库检索，可能产生不真实或不符合 EnergyPlus 规范的参数。第三，EnergyPlus 输入文件具有强约束结构，仅依赖 LLM 直接生成 IDF 或配置文本难以保证对象字段、命名和跨引用关系的正确性。最后，仿真输出本身也较复杂，若缺少自动化结果解析和可视化反馈，设计者仍难以将仿真结果快速转化为下一轮设计决策。

针对上述问题，本文提出 **EnergyPlus\-Agent**，一个面向建筑设计阶段的检索增强型建筑能耗模拟智能体系统。该系统并不让 LLM 直接编写完整 IDF 文件，而是将自然语言建筑描述解析为结构化任务，再通过多阶段 agent 工作流逐步创建 EnergyPlus 配置对象。系统基于 LangGraph 构建了从 `intake` 到 `zone`、`material`、`schedule`、`construction`、`surface`、`fenestration`、`hvac`、`people`、`lights`、`validate`、`simulate` 和 `analyze` 的节点流程；通过 MCP 工具层对 Building、Zone、Material、Construction、Schedule、HVAC、People、Lights 等对象进行结构化创建和修改；通过 RAG 检索材料、构造、日程和设计日等 EnergyPlus 参考数据；并通过 Pydantic Schema、跨引用验证、agent 自修复、人机审查和 EnergyPlus 运行反馈共同保障模型输入的正确性。

在系统实现上，EnergyPlus\-Agent 维护一个中心化的 `ConfigState` 作为建筑配置状态。各个 agent 节点并行或顺序生成对应子系统对象，并将结果合并到共享状态中。系统在关键阶段执行跨引用检查：若发现构造引用不存在的材料、表面引用不存在的热区或构造、窗户引用不存在的表面、HVAC 引用不存在的日程等问题，会将错误反馈给对应 agent 进行自修复；若模型通过验证，则进入人工审查和 EnergyPlus 仿真阶段。仿真完成后，系统解析 `eplusout.end`、`eplusout.err`、`eplusout.csv` 和 `eplustbl.csv/html` 等输出文件，生成能耗、热舒适、峰值负荷、运行时间表、3D 热区能耗和外表面太阳辐照等结果图表，并将分析结果返回给设计者和 LLM，用于支持下一轮设计判断。

本文的主要贡献如下：

1. 提出一个面向设计阶段的 EnergyPlus 智能体框架，将自然语言交互、多节点任务分解、MCP 工具调用、模型验证、仿真执行和结果解析连接为闭环。

2. 构建检索增强的 BEM 参数生成机制，使 agent 能够主动查询材料、构造、日程和设计日等专业参考数据，减少 LLM 对关键物理参数的主观猜测。

3. 设计多层正确性保障机制，通过结构化输出、Schema 验证、跨引用检查、agent 自修复、人机审查和仿真错误反馈，提高 EnergyPlus 输入模型的一致性和可运行性。

4. 实现面向设计反馈的仿真结果解析与可视化，将复杂 EnergyPlus 输出转化为设计者可理解的能耗、舒适性和空间性能指标。

5. 通过案例研究展示 EnergyPlus\-Agent 如何降低 EnergyPlus 建模门槛、减少人工操作，并支持建筑设计阶段更高效的能耗方案探索。

# 2\. Literature Review

## 2\.1 自动化建筑能耗建模

传统 BEM 自动化研究主要关注从规则、模板、BIM、GIS、审计数据或传感器数据中自动生成建筑能耗模型。近期 Data2BEM 通过 LLM 多智能体框架从图纸、技术规格书和传感器数据中生成并校准既有建筑模型，证明了多源数据与 LLM agent 可以显著压缩人工建模时间。知识工程驱动的多智能体 BEM 服务则说明，将规范、流程和领域知识结构化后，可以提升城市尺度既有建筑自动建模能力。

本节需要强调：这些工作证明了自动化 BEM 的可行性，但主要面向既有建筑、城市尺度建模或改造分析；本文更关注设计阶段与设计者共同迭代的交互式建模。

## 2\.2 LLM 与多智能体建筑性能分析

EPlus\-LLM、LLM\-driven BEM generation 和 agentic BEM workflow 表明，LLM 可以从自然语言中提取建筑信息、生成 EnergyPlus 对象或调试 IDF 文件。AutoBEE、BEM\-AI 等研究进一步展示了多智能体系统在任务分解、工具调用和性能分析报告生成中的价值。EnergyPlus\-MCP 和 MCP\-enabled BEM workflow 则说明，MCP 正在成为 LLM 与 EnergyPlus 工具交互的重要技术基础。

本节需要强调：现有研究已经从“LLM 直接生成文本”走向“LLM 调用工具完成任务”，但仍需要更系统地解决 EnergyPlus 输入对象正确性、跨引用错误修复、RAG 专业参数检索和设计反馈闭环。

## 2\.3 LLM 辅助设计生成与 BIM 建模

Text2BIM 展示了自然语言到可编辑 BIM 模型的生成潜力，EnergAI 将 LLM 引入早期建筑体量生成和能耗优化，Sketch\-to\-Energy 结合多模态 LLM、计算机视觉和 RAG，从草图与自然语言要求生成 EnergyPlus 模型。这些工作说明 LLM 正在进入建筑设计生成阶段。

本节需要强调：BIM 或体量生成并不等同于可运行、可验证、可解析的 EnergyPlus 仿真闭环。本文的差异在于把设计意图、专业参数、模型校验、仿真执行和结果反馈连接起来。

## 2\.4 研究缺口

现有研究已经证明 LLM 可以生成模型、多智能体可以执行分析、MCP 可以封装工具、RAG 可以增强专业知识，但面向设计阶段的 BEM 仍存在以下缺口：

1. 交互式多轮方案探索支持不足。

2. 材料、构造和时间表等专业参数容易出现 LLM 幻觉。

3. EnergyPlus 对象字段、命名和跨引用关系缺少多层正确性保障。

4. 仿真输出难以直接转化为设计者可理解的反馈。

5. 从自然语言输入到仿真结果分析的完整闭环仍不充分。

# 3\. Methodology

## 3\.1 系统总体架构

EnergyPlus\-Agent 的总体流程为：

用户输入建筑自然语言描述和可选图像/天气文件；`intake` 节点解析建筑意图；多个专业 agent 节点生成热区、材料、日程、构造、表面、窗户、HVAC、人员和照明对象；MCP 工具层将 agent 行为限制为结构化 CRUD 操作；RAG 工具提供材料、构造、日程和设计日等参考参数；`ConfigState` 维护全局配置状态；验证节点执行跨引用检查和人工审查；仿真节点生成 IDF 并运行 EnergyPlus；分析节点解析输出文件并生成报告和图表。

## 3\.2 多阶段 Agent 编排

项目当前使用 LangGraph 构建如下拓扑：

`intake -> [zone, material, schedule] -> cross_ref_foundations -> construction -> surface -> fenestration -> [hvac, people, lights] -> cross_ref_complete -> validate -> simulate -> analyze`

该流程的关键特点是：

1. 将复杂 BEM 任务拆分为多个专业节点。

2. 基础对象和负荷系统可并行生成。

3. 在关键阶段执行 cross\-reference 检查。

4. 验证失败时可以回到 intake 或局部自修复。

5. 验证通过后再进入 EnergyPlus 仿真和结果分析。

## 3\.3 MCP 工具层与配置状态

系统不让 LLM 直接拼接 IDF，而是通过 MCP 工具创建和修改结构化对象。工具覆盖 Building、Location、Zone、Surface、Material、Construction、Fenestration、Schedule、HVAC、People、Lights 和 workflow 操作。中心状态 `ConfigState` 保存所有 EnergyPlus 配置对象，并支持导出 YAML、加载 YAML、验证引用、生成摘要和运行仿真。

## 3\.4 EnergyPlus 输入正确性保障

系统通过多层机制保证输入正确性：

1. Intake 使用结构化输出 `IntakeOutput`。

2. Pydantic Schema 校验字段类型、枚举值、几何和基础参数。

3. `ConfigState.validate_references()` 检查材料、构造、表面、窗户、热区、HVAC 和日程之间的跨引用关系。

4. 每个阶段 agent 执行后强制验证；发现错误则将错误反馈给 agent 自修复。

5. 完整验证后进入人机协同审查。

6. EnergyPlus 运行后读取 `.err` 和 `.end` 文件，将 severe/fatal errors 反馈给系统。

## 3\.5 RAG 专业知识库

RAG 工具 `search_energyplus_reference` 用于检索 EnergyPlus 参考数据库，覆盖标准材料、无质量材料、构造、ScheduleTypeLimits、ScheduleCompact 和设计日等数据。Agent 在生成材料热工参数、构造层次或日程模式时，可先查询 RAG，再使用返回记录中的 `full_data` 作为参数依据。若 Qdrant 或 Gemini Embedding 不可用，RAG 工具会优雅降级，并提示使用 ASHRAE 默认值继续流程。

## 3\.6 IDF 转换与仿真执行

系统由 `ConverterManager` 将结构化配置转换为 IDF。转换器覆盖 settings、building、schedules、zones、materials、constructions、surfaces、fenestrations、hvac、lights 和 people。`WorkflowTool.run_simulation()` 先验证配置，再生成临时 IDF，并调用 `EnergyPlusRunner` 使用 EPW 文件执行仿真。

## 3\.7 结果解析与可视化

结果解析模块读取 `eplusout.end`、`eplusout.err`、`eplusout.csv`、`eplustbl.csv/html` 和必要时的 `eplusout.eso`。当前可生成的分析包括：

1. 仿真状态、警告和严重错误。

2. 年度终端用途能耗和 EUI。

3. 分区月度 HVAC 能耗。

4. 分区温度热力图。

5. 热舒适小时数。

6. HVAC 峰值需求曲线。

7. 温湿度散点与 PMV 舒适区。

8. 3D 热区能耗图。

9. 3D 外表面太阳辐照图。

10. 人员和设备运行时间表热力图。

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YzhhOTU3MDAzMTEyM2FhMzE3ZjRiMDQyNGNhZmFjYzRfM2FjZDI1M2RjYjFkNTJiYmYzZDEzOTFhYzUwNTUyYjdfSUQ6NzY0OTYyNTQzMjY3NzE0MTczNl8xNzgyMTkxNjgzOjE3ODIyNzgwODNfVjM)

# 4\. Results

## 4\.1 案例设置

建议设置两个主要案例：

1. 简单办公室案例：深圳单层 5\-zone office，包含基本围护、窗户、人员、照明和 ideal loads HVAC。

2. 复杂中庭办公楼案例：深圳 5 层办公楼，含中央中庭、天窗、多功能空间、服务器机房、差异化日程和 HVAC 设置。

## 4\.2 端到端运行流程展示

需要展示从 0 开始的完整流程：

1. 用户输入建筑描述。

2. Intake 生成结构化 specs。

3. Zone/material/schedule 节点生成基础对象。

4. RAG 查询材料、构造或日程。

5. Construction/surface/fenestration 节点生成围护结构。

6. HVAC/people/lights 节点生成系统和内部负荷。

7. Cross\-reference 发现或确认引用关系。

8. Validate 节点进行人工审查。

9. Simulate 节点生成 IDF 并运行 EnergyPlus。

10. Analyze 节点输出报告和图表。

## 4\.3 RAG 交互示例

建议展示材料、构造、日程和设计日四类查询。

|阶段|查询意图|RAG 返回|Agent 使用方式|
|---|---|---|---|
|Material|查询混凝土、岩棉、石膏板参数|导热系数、密度、比热等|创建 Material 对象|
|Construction|查询外墙构造|层次顺序和材料引用|创建 Construction 对象|
|Schedule|查询办公日程|工作日/周末时间段|创建 Schedule:Compact|
|HVAC|查询设计日参数|干球温度、湿球温度等|用于 sizing 或默认设置|

## 4\.4 错误修复与回退案例

需要记录实际运行中出现的错误，例如：

1. Construction 引用了不存在的 material。

2. Surface 引用了不存在的 zone 或 construction。

3. Fenestration 引用了不存在的 surface。

4. Thermostat 引用了不存在的 schedule。

5. EnergyPlus 运行产生 severe/fatal error。

结果部分应展示系统如何发现错误、反馈给 agent、完成修复，并最终进入仿真。

## 4\.5 结果解析与设计反馈

应展示仿真完成后返回的结果：

1. 仿真状态。

2. 热环境与舒适性。

3. 总能耗、EUI 和分项能耗。

4. 峰值负荷与关键时段。

5. 3D 热区能耗和太阳辐照。

6. 设计建议。

## 4\.6 与传统流程对比

|对比项|传统 EnergyPlus 流程|EnergyPlus\-Agent 流程|
|---|---|---|
|输入方式|手动填写 IDF 或 OpenStudio 建模|自然语言/图片/天气文件|
|参数来源|人工查规范、材料库、经验值|RAG 检索 \+ 默认值|
|对象创建|手动创建各类 IDF 对象|多节点 agent 调用工具创建|
|错误处理|人工阅读 err 文件修复|Schema \+ cross\-reference \+ self\-repair|
|结果解析|人工查看 CSV/HTML|自动统计、图表和报告|
|设计迭代|修改成本高|对话式修改并重新仿真|

## 4\.7 RAG 消融实验

|指标|Without RAG|With RAG|
|---|---|---|
|材料参数错误/缺失数量|待测|待测|
|构造层引用错误数量|待测|待测|
|日程对象缺失数量|待测|待测|
|IDF 验证通过率|待测|待测|
|EnergyPlus 成功运行率|待测|待测|
|人工修正次数|待测|待测|

## 4\.8 自优化结果（可选）

如果后续实现自动优化，可记录：

1. EUI 降低情况。

2. 舒适小时比例提升。

3. 峰值负荷降低。

4. PV 或太阳辐照利用效率提升。

5. 年运行成本或生命周期成本变化。

若当前系统尚未完整实现自优化，应将该部分放入未来工作，而不是作为当前结果。

# 5\. Discussion

## 5\.1 系统意义

EnergyPlus\-Agent 的意义不是单纯自动生成 IDF，而是将 BEM 从专家主导的手动建模流程，转化为设计者可以通过自然语言参与的人机协同流程。系统使早期设计阶段可以更频繁地获得能耗和热舒适反馈，从而支持更快的方案探索。

## 5\.2 降低幻觉和错误的原因

系统通过结构约束、工具约束、知识约束和反馈约束减少 LLM 幻觉：

1. 结构约束：IntakeOutput 和 Pydantic Schema。

2. 工具约束：MCP 工具层和 CRUD 操作。

3. 知识约束：RAG 检索材料、构造和日程。

4. 反馈约束：cross\-reference、自修复、人机审查和 EnergyPlus 错误反馈。

## 5\.3 对设计流程的影响

系统可能使 BEM 从“设计完成后的验证工具”转变为“设计过程中的协同反馈工具”。设计者不需要在每次方案变更后从头手动建模，而可以通过对话式修改快速进入下一轮仿真。

## 5\.4 当前局限

1. 复杂几何、复杂 HVAC 系统和详细控制策略仍可能需要专家介入。

2. LLM 生成的空间划分和表面几何仍需要人工检查。

3. RAG 数据库质量、覆盖范围和地区适用性会影响结果可靠性。

4. 当前验证主要关注字段和跨引用，尚不能完全保证工程合理性。

5. EnergyPlus 结果依赖输入假设，agent 不能替代专业校准。

6. 自优化功能若尚未完整实现，应作为未来工作。

## 5\.5 未来工作

1. 接入 BIM、CAD、平面图和剖面图，实现更稳定的多模态几何理解。

2. 扩展 HVAC 系统类型和控制策略。

3. 加入规范合规检查。

4. 建立系统 benchmark，比较不同 LLM、agent 拓扑和 RAG 配置。

5. 引入多目标优化算法。

6. 加入版本管理，记录每轮方案修改和仿真结果。

7. 将结果摘要压缩为更适合 LLM 决策的结构化指标。

# 6\. Conclusion

本文提出 EnergyPlus\-Agent，一个面向建筑设计阶段的检索增强型建筑能耗模拟智能体系统。系统通过 LLM 解析设计意图，通过 LangGraph 将任务分解为多个专业节点，通过 MCP 工具创建结构化 EnergyPlus 配置对象，通过 RAG 检索现实材料、构造和日程参数，并通过多层验证、自修复和仿真结果解析形成闭环。

案例研究将进一步验证该系统能否降低 EnergyPlus 建模门槛，提高建模和仿真流程的一致性，减少 LLM 参数幻觉，并帮助设计者更快理解能耗、热舒适、峰值负荷和太阳辐照等关键结果。未来，系统可进一步扩展到多模态图纸输入、复杂 HVAC、自动优化和规范合规检查，为人机协同的建筑性能设计提供更完整的工具链。

# 7\. References 

正式参考文献格式后续需要统一整理。当前建议引用来源包括：

1. GlobalABC / UNEP, Global Status Report for Buildings and Construction\.

2. EnergyPlus official documentation / U\.S\. Department of Energy\.

3. EPlus\-LLM: A large language model\-based computing platform for automated building energy modeling\.

4. User\-friendly AI\-driven automation for rapid building energy model generation\.

5. Automatic building energy model development and debugging using large language models agentic workflow\.

6. LLM\-Agent\-UMI / Large language model\-based agent Schema and library for automated building energy analysis and modeling\.

7. Data2BEM: Automated building energy modeling for energy retrofits using a large language model\-based multi\-agent framework\.

8. AutoBEE: A hierarchical multi\-agent approach for energy and environmental parameter analysis\.

9. BEM\-AI: Development of a dynamic multi\-agent network for building energy modeling\.

10. EnergyPlus\-MCP: A model\-context\-protocol server for AI\-driven building energy modeling\.

11. MCP\-enabled agentic AI workflow for building energy modelling\.

12. RAG \+ MCP urban\-scale building energy simulation / resilience assessment work\.

13. Sketch\-to\-Energy\.

14. Text2BIM: Generating Building Models Using a Large Language Model\-Based Multiagent Framework\.

15. EnergAI: A Large Language Model\-Driven Generative Design Method for Early\-Stage Building Energy Optimization\.



## Todo

### 6\-16

方法论不用那么多。大概到3\.4就行

方法论不用说方法具体怎么实现

方法论内容（你认为这个研究中创新的比较关键的内容）：总体架构（整篇论文的总体框架，不用单独开一章，写到方法论大标题下的引出文本里，作为一个框架图）

方法论具体内容：

先说我们做了一个……，有哪些模块……。

1、3\.1文本输入模块，怎么处理文本输入、怎么处理图像输入、经过哪些模型、怎么控制、使用rag来控制幻觉（接3\.2）；

2、RAG控制模块，怎么控制的，具体有哪些东西；

3、3\.3解析模块，怎么去解析的

4、3\.4案例设置

案例设置归到方法论里去



![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MmRhOTU1MWZlODM5MDcxZWFkNzdhMzVhMGFlNjQxNGRfY2NiYWJhMjU3NzI5NDJkYTcxODZmMjhhODA2MmZmMTdfSUQ6NzY1MTk2Mzc3OTg5NDgwNzc0OV8xNzgyMTkxNjgzOjE3ODIyNzgwODNfVjM)

上面都是案例展示——归到pipeline运行结果，对结果的一个说明或者是评估

4\.5解析部分主要是说明我们解析了什么东西出来，怎么去分析，模型输出了一个图表，模拟建筑师看到图表之后的判断。

4\.6流程对比继续保留

4\.7部分放到result的第一部分。

---

4\.1RAG

4\.2引入RAG之后的workflow的结果展示

4\.3结果解析出来了什么，怎么分析

4\.4与传统流程对比

---

discussion

不能复述result，对于结果进行分析之后，哪些问题比较有趣可以分析成因。

---

node组内报错自循环——当node不能自愈的时候应该回到那个节点。

前端

自优化

需要视频来描述过程——描述agent如何工作。

---





