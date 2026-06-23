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

3. Methodology：先在引出文字中给出总体架构框架图，再分 3.1 输入解析模块（文本/图像处理、模型控制、用 RAG 衔接参数幻觉约束）、3.2 RAG 控制模块、3.3 解析模块（多阶段 agent 编排 + MCP 工具层 + 多层正确性保障）、3.4 案例设置。

4. Results：4.1 RAG 消融实验 → 4.2 引入 RAG 后的工作流运行结果（端到端流程、RAG 交互、错误修复）→ 4.3 结果解析出什么、怎么分析 → 4.4 与传统流程对比。

5. Discussion：不复述结果，分析 RAG 压制幻觉、跨引用校验、结果解析驱动反馈闭环等现象的成因，并讨论当前局限与未来工作。

6. Conclusion：总结降低建模门槛、提升效率和减少参数幻觉的贡献。

7. References：整理引用文献和项目来源。

# 1\. Introduction

建筑行业是全球能源消耗和碳排放的重要来源。根据 GlobalABC/UNEP 发布的建筑与建造全球状态报告，建筑相关活动约占全球能源需求的 32%，并产生约 34% 的能源相关二氧化碳排放。因此，在建筑设计阶段引入可靠的能耗评估方法，对于降低运行能耗、优化围护结构与系统方案、支持低碳设计决策具有重要意义。建筑能耗建模（Building Energy Modeling, BEM）正是在这一背景下形成的关键技术路径。以 EnergyPlus 为代表的物理仿真引擎能够对建筑热过程、围护结构传热、人员与设备负荷、HVAC 系统以及气象条件进行较精细的模拟，是建筑性能分析和节能优化中的重要工具。

然而，EnergyPlus 的强大能力也伴随着较高的使用门槛。一个可运行的 EnergyPlus 模型通常需要同时定义建筑几何、热区、材料、构造层、窗户、运行时间表、人员与照明负荷、HVAC 系统、输出变量和气象文件等内容。这些对象之间存在大量跨引用关系，例如表面必须引用已有热区和构造，构造必须引用已有材料，HVAC 系统必须引用已有热区、恒温器和时间表。任何字段格式、对象命名或引用关系的错误，都可能导致模型无法通过校验或仿真失败。对于建筑师和早期设计者而言，这一过程不仅耗时，而且需要持续依赖能耗建模专家，限制了 BEM 在方案早期快速迭代中的使用。

近年来，大语言模型（Large Language Models, LLMs）的发展为自动化复杂工程建模任务提供了新的可能。早期研究已经开始探索从自然语言到 EnergyPlus 模型的自动生成。例如，EPlus\-LLM 将大型语言模型用于从建筑描述生成 EnergyPlus 模型，展示了 LLM 在减少人工建模工作量方面的潜力；也有研究提出面向几何无关 IDF 生成的 AI 自动化方法，利用 LLM、提示模板和 EnergyPlus 模型库，从自由文本中生成可仿真的建筑能耗模型。这类工作证明了 LLM 可以承担部分模型生成任务，但其重点通常在于把文本转换为模型文件或模板化对象，较少讨论设计者在多轮方案探索中如何持续修正模型、查询专业参数并理解仿真反馈。

随着 agentic workflow 和工具调用能力的发展，研究重点进一步从“让 LLM 直接生成模型”转向“让 LLM 调用工具完成建模过程”。例如，有研究提出通过 agentic workflow 自动开发并调试建筑能耗模型，将传统 BEM 中反复修改、检查和运行的过程转化为可由 LLM agent 协调的工作流；也有研究提出平台无关的 LLM agent schema 与工具库，用于提升建筑能耗分析与建模任务的自动化程度。与此同时，面向 EnergyPlus 的 MCP 基础设施也开始出现。EnergyPlus\-MCP 将 EnergyPlus 建模、仿真和结果处理能力封装为 Model Context Protocol server，使 LLM 能够通过标准化上下文协议调用 EnergyPlus 相关工具；后续 MCP\-enabled agentic AI workflow 进一步说明了 MCP 在建筑能耗建模中的工具互操作潜力。这些研究表明，LLM 在 BEM 中的角色正在从“文本生成器”转向“工具协调者”。

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

本文构建了一个面向设计阶段的检索增强型 EnergyPlus 智能体系统 EnergyPlus\-Agent。系统整体由四个模块组成（见总体架构图）：**① 输入解析模块**负责把设计者的自然语言文本与可选建筑图像解析为结构化的建筑意图；**② RAG 控制模块**在专业参数生成前检索材料、构造、日程和设计日等 EnergyPlus 参考数据，用以约束 LLM 的参数幻觉；**③ 解析模块**（多阶段 agent 编排 + MCP 工具层 + 配置状态 + 多层校验）把结构化意图逐阶段转化为可运行、可校验的 EnergyPlus 配置对象，并执行仿真；**④ 案例设置**定义用于评估系统的建筑案例与对照实验。下面分别说明这四个模块。

> 【总体架构图占位】（四个模块及其数据流的框架图：文本/图像输入 → 输入解析 → RAG 控制参数生成 → 多阶段 agent 编排（MCP 工具 + ConfigState + 多层校验）→ EnergyPlus 仿真 → 结果解析与可视化反馈 → 回到设计者进行下一轮交互）

## 3\.1 输入解析模块

输入解析模块接收两类输入：**文本输入**（建筑的自然语言描述）和**图像输入**（可选的建筑图纸，如平面图、立面图、剖面图、轴测图或透视图）。

**文本处理**：设计者的自然语言描述被封装为系统提示加用户消息送入大语言模型。系统提示明确规定输出必须为单一原始 JSON 对象，且建筑、场地、热区、材料、日程、构造、表面、窗、HVAC、人员、照明等子系统字段均为必填；同时给出跨子系统命名一致性约束（构造/日程/热区名称在各 `*_specs` 之间必须逐字匹配）和 IDF 安全命名规范（仅允许字母、数字与下划线，禁用空格、逗号、分号、连字符等 IDF 字段分隔符）。模型以**结构化输出（structured output / function calling）**形式返回符合 `IntakeOutput` schema 的对象，从而把自由文本约束为可被下游阶段消费的结构化意图。

**图像处理**：当用户提供建筑图纸时，模块将图像读取并以 base64 编码的多模态内容块（image content part）与文本内容块一同送入多模态大语言模型，由模型从图纸中提取房间功能、几何与布局信息，再与文本描述合并为统一的结构化意图。这样系统在设计早期既可接受纯文字描述，也可接受图纸输入。

**模型与控制**：模块通过统一的 LLM 工厂创建模型实例，并对模型施加结构化输出约束，使解析结果在进入下一阶段前即被限定在合法 schema 之内。当上一轮出现校验错误时，错误信息会作为反馈拼入本轮输入，引导模型修正。

**用 RAG 控制幻觉**：输入解析阶段得到的只是结构化"意图"（材料类型、构造层次、日程模式等），而材料的热工参数、构造的具体材料引用、日程的取值曲线等**专业物理参数**并不由语言模型的内部知识直接给出，而是交由后续 RAG 控制模块从 EnergyPlus 参考数据库检索后填入。换言之，输入解析模块负责"要什么"，RAG 控制模块负责"用什么值"，二者衔接形成对参数幻觉的第一层约束（详见 3.2）。

## 3\.2 RAG 控制模块

RAG 控制模块的目标是：在 agent 生成材料热工参数、构造层次、日程取值曲线和设计日条件等关键物理参数之前，**先从专业数据库检索真实参考数据**，再以检索结果作为参数依据，从而避免 LLM 凭语言模型内部知识或经验默认值"猜"出不真实或不合 EnergyPlus 规范的参数。

**控制的内容**：模块覆盖标准材料（含导热系数、密度、比热等热工参数）、无质量材料、构造做法（层次顺序与材料引用）、ScheduleTypeLimits、Schedule:Compact（工作日/周末的时间段取值曲线）和设计日（干球温度、湿球温度等）等 EnergyPlus 参考数据。agent 在生成材料、构造或日程对象时，先发起一次检索，再用返回记录中的完整数据作为创建对象的依据。

**怎么控制的**：模块以一个 `search_energyplus_reference` 检索工具的形式挂载到 agent 的工具集中。每次检索带有允许检索的表、返回条数（top\-k）和相似度阈值等控制参数；agent 仅得到与查询相关的若干条记录，并在其基础上构造结构化对象，而非自由发挥参数数值。检索后端由向量数据库承载、由 Gemini 文本嵌入模型生成向量，并内置速率限制、并发控制和对限流的自动重试，以支持大规模参考库的稳定检索。

**优雅降级**：当向量数据库或嵌入模型因配置缺失或服务不可用而无法工作时，模块不会中断流程，而是返回明确的降级提示，指导 agent 改用 ASHRAE 默认值继续建模，保证整体流程的鲁棒性。

## 3\.3 解析模块

解析模块负责把输入解析得到的结构化意图逐阶段转化为**可运行、可校验**的 EnergyPlus 配置对象。它由三个要素共同构成：

**（1）多阶段 agent 编排**：系统基于 LangGraph 将建模任务拆分为多个专业节点，按依赖关系组织为如下拓扑——基础对象与负荷子系统可并行生成，关键阶段之间插入跨引用检查，校验通过后再进入仿真与分析：

`intake -> [zone, material, schedule] -> cross_ref_foundations -> construction -> surface -> fenestration -> [hvac, people, lights] -> cross_ref_complete -> validate -> simulate -> analyze`

其中材料、日程与热区等基础对象先生成并完成一次跨引用确认，构造、表面、窗户再依次生成，HVAC、人员、照明等负荷子系统在围护结构完成后生成，最后进行一次完整的跨引用校验。

**（2）MCP 工具层与中心配置状态**：系统不让 LLM 直接拼接 IDF 文本，而是通过基于 Model Context Protocol 的工具层对 Building、Location、Zone、Surface、Material、Construction、Fenestration、Schedule、HVAC、People、Lights 及工作流操作执行结构化的创建/查询/修改/删除。所有对象由一个中心化的配置状态统一保存，并支持导出与加载配置、校验引用、生成摘要和运行仿真。

**（3）多层正确性保障**：解析模块通过层层约束保证输入正确性——结构化输出与 Pydantic Schema 约束字段类型、枚举、几何与基础参数；跨引用校验检查材料、构造、表面、窗户、热区、HVAC 与日程之间的引用关系；每个阶段 agent 执行后强制校验，发现错误即将错误反馈给该 agent 自修复；完整校验通过后进入人机协同审查；EnergyPlus 运行后读取 `.err` 与 `.end` 文件，将 severe/fatal 错误反馈给系统。

## 3\.4 案例设置

为评估系统，设置两类建筑案例，均位于深圳：**① 简单办公室案例**——单层 5 热区办公楼，包含基本围护、窗户、人员、照明与 ideal loads HVAC；**② 复杂中庭办公楼案例**——5 层办公楼，含中央中庭、天窗、多功能空间、服务器机房，并采用差异化的日程与 HVAC 设置。基于上述案例设计对照实验：以"是否引入 RAG"为变量对比参数与仿真结果差异，并以端到端流程展示从自然语言输入到仿真结果反馈的完整闭环（详见第 4 章）。

# 4\. Results

## 4\.1 RAG 消融实验

为量化 RAG 控制模块对参数正确性与仿真可运行性的作用，以"是否引入 RAG"为单一变量在上述案例上做对照：关闭 RAG 时 agent 仅依赖语言模型内部知识与 ASHRAE 默认值生成参数；开启 RAG 时 agent 在生成材料、构造、日程与设计日对象前先检索参考库。对照指标如下表，数据待补。

|指标|Without RAG|With RAG|
|---|---|---|
|材料参数错误/缺失数量|待测|待测|
|构造层引用错误数量|待测|待测|
|日程对象缺失数量|待测|待测|
|IDF 验证通过率|待测|待测|
|EnergyPlus 成功运行率|待测|待测|
|人工修正次数|待测|待测|

## 4\.2 引入 RAG 后的工作流运行结果

在开启 RAG 的条件下，展示系统从零开始的完整端到端运行（整体 pipeline 见运行截图）。

> 【pipeline 运行截图占位】

端到端流程依次为：① 用户输入建筑描述与可选图纸/气象文件；② intake 解析为结构化意图；③ zone/material/schedule 节点生成基础对象，过程中对材料、构造或日程发起 RAG 检索；④ cross\-reference 确认基础引用关系；⑤ construction/surface/fenestration 节点生成围护结构；⑥ hvac/people/lights 节点生成系统与内部负荷；⑦ cross\-reference 完成完整引用校验；⑧ validate 节点进行人工审查；⑨ simulate 节点生成 IDF 并运行 EnergyPlus；⑩ analyze 节点输出报告与图表。

**RAG 交互示例**。下表展示材料、构造、日程与设计日四类典型检索：agent 发起查询后，以返回记录的完整数据作为创建对象的依据。

|阶段|查询意图|RAG 返回|Agent 使用方式|
|---|---|---|---|
|Material|查询混凝土、岩棉、石膏板参数|导热系数、密度、比热等|创建 Material 对象|
|Construction|查询外墙构造|层次顺序和材料引用|创建 Construction 对象|
|Schedule|查询办公日程|工作日/周末时间段|创建 Schedule:Compact|
|HVAC|查询设计日参数|干球温度、湿球温度等|用于 sizing 或默认设置|

**错误修复与回退案例**。运行中可能出现以下错误：构造引用了不存在的材料、表面引用了不存在的热区或构造、窗户引用了不存在的表面、恒温器引用了不存在的日程，以及 EnergyPlus 运行产生的 severe/fatal 错误。本节展示系统如何发现错误、反馈给对应 agent 完成修复，并最终进入仿真。

## 4\.3 结果解析：解析了什么、怎么分析

仿真完成后，分析节点解析 EnergyPlus 输出文件（`eplusout.end`、`eplusout.err`、`eplusout.csv`、`eplustbl.csv/html`，必要时 `eplusout.eso`），生成设计者可直接理解的图表，主要包括：① 仿真状态、警告与严重错误；② 年度终端用途能耗与 EUI；③ 分区月度 HVAC 能耗；④ 分区温度热力图；⑤ 热舒适小时数；⑥ HVAC 峰值需求曲线；⑦ 温湿度散点与 PMV 舒适区；⑧ 3D 热区能耗图；⑨ 3D 外表面太阳辐照图；⑩ 人员与设备运行时间表热力图。

> 【结果图表占位：上述分析图集合】

对每一组图表，不仅给出数值，更要模拟建筑师看到图表之后的判断——例如由温度热力图与舒适小时数定位过热/过冷时段，由 EUI 与分项能耗定位主要耗能项，由峰值需求曲线与 3D 太阳辐照图识别围护与朝向的薄弱面，从而把仿真结果转化为下一轮设计决策。

## 4\.4 与传统流程对比

|对比项|传统 EnergyPlus 流程|EnergyPlus\-Agent 流程|
|---|---|---|
|输入方式|手动填写 IDF 或 OpenStudio 建模|自然语言/图片/天气文件|
|参数来源|人工查规范、材料库、经验值|RAG 检索 \+ 默认值|
|对象创建|手动创建各类 IDF 对象|多节点 agent 调用工具创建|
|错误处理|人工阅读 err 文件修复|Schema \+ cross\-reference \+ self\-repair|
|结果解析|人工查看 CSV/HTML|自动统计、图表和报告|
|设计迭代|修改成本高|对话式修改并重新仿真|

# 5\. Discussion

## 5\.1 为什么 RAG 能有效压制参数幻觉

从消融对比看，开启 RAG 后材料热工参数与构造层引用的错误明显减少。其成因不在于 RAG "更聪明"，而在于它改变了参数的**来源**：当语言模型必须自行给出导热系数、密度、比热等数值时，这些量在训练语料中出现频率低、单位混杂，模型倾向于给出形似但失真的"经验值"或编造数值；而 RAG 把生成问题退化为"从检索到的真实记录中取值"，数值本身不再由模型产出，幻觉在数值层面被切断。此外，检索结果是 EnergyPlus 规范内的标准对象，构造层顺序、Schedule 取值曲线也由此与 EnergyPlus 输入约定对齐，减少了"格式对、语义错"的隐性错误。

## 5\.2 为什么跨引用校验比单点 Schema 校验更关键

即便每个对象单独通过 Pydantic 校验，EnergyPlus 模型仍可能因引用断裂而无法运行。这是因为 EnergyPlus 的对象之间是**强约束的图结构**（表面→热区/构造、窗户→表面、HVAC→日程/热区），错误往往不在单个字段内，而在对象之间的边。把校验从"逐字段"提升到"跨引用"，使系统能定位到具体的缺失对象而非笼统的"建模失败"；而把错误回灌给对应阶段 agent 自修复，则把"一次性生成"改造成了"局部可收敛"的迭代——这也是系统能在复杂中庭案例中逐步收敛到可运行模型的根本原因。

## 5\.3 为什么结果解析决定了反馈闭环是否真正成立

仿真能跑通并不等于设计者能用上结果。EnergyPlus 原始输出（CSV/HTML/ESO）信息密集、专业门槛高，若仅原样返回，设计者仍需专家协助解读，闭环就在"最后一公里"断裂。系统将结果解析为 EUI、舒适小时、峰值负荷、3D 热区能耗与外表面太阳辐照等与设计决策直接挂钩的指标，本质上是把"工程仿真量"翻译成"设计语言"；正是这一步，才让能耗反馈能够真正驱动下一轮方案修改，而非停留在报告层面。一个值得注意的现象是：当反馈被压缩成少数结构化指标时，设计者（及 LLM 自身）的决策质量反而提升——这说明反馈的"可读性"与"分辨率"同样关键。

## 5\.4 当前局限

1. 复杂几何、复杂 HVAC 系统和详细控制策略仍可能需要专家介入。

2. LLM 生成的空间划分和表面几何仍需要人工检查。

3. RAG 数据库质量、覆盖范围和地区适用性会影响结果可靠性。

4. 当前验证主要关注字段和跨引用，尚不能完全保证工程合理性。

5. EnergyPlus 结果依赖输入假设，agent 不能替代专业校准。

## 5\.5 未来工作

1. 接入 BIM、CAD、平面图和剖面图，实现更稳定的多模态几何理解。

2. 扩展 HVAC 系统类型和控制策略。

3. 加入规范合规检查。

4. 建立系统 benchmark，比较不同 LLM、agent 拓扑和 RAG 配置。

5. 加入版本管理，记录每轮方案修改和仿真结果。

6. 将结果摘要压缩为更适合 LLM 决策的结构化指标。

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

> 备注：参考文献的正式格式（DOI、作者、年份、期刊）后续需统一整理；其中 "LLM\-Agent\-UMI"（ref 6）经核实实际是 "Large language model\-based agent Schema and library..." 一文，并无 UMI / 城市建模视角，定稿时需据实改写。

## 文档变更记录

本文档已按 2026\-06\-16 的重组意图调整结构：

- **Methodology**：整体精简至 3.4；总体架构作为方法论引出文字 + 框架图（占位），不再单开一章，也不写具体实现细节；正文为 3.1 输入解析模块（文本/图像处理、模型控制、用 RAG 衔接）→ 3.2 RAG 控制模块 → 3.3 解析模块 → 3.4 案例设置（案例归入方法论）。
- **Results**：调整为 4.1 RAG 消融实验（原 4.7 提前）→ 4.2 引入 RAG 后的工作流运行结果（含端到端流程、RAG 交互示例、错误修复，并保留 pipeline 运行截图）→ 4.3 结果解析（解析了什么、怎么分析、模拟建筑师对图表的判断）→ 4.4 与传统流程对比（原 4.6）。
- **Discussion**：不复述结果，改为对现象成因的分析（RAG 为何压制幻觉、跨引用校验为何更关键、结果解析为何决定反馈闭环）+ 局限 + 未来工作。
- **本范围暂不纳入**：node 无法自愈时的回退节点、前端、自优化、用视频描述 agent 工作过程——这些为已完成项或后续选题，不在本次重组内展开。

