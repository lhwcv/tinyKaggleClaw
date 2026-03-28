# research_mvp 架构说明

本文档描述 `research_mvp` 当前的整体架构、运行机制、任务模型、Supervisor 控制环、四个 agent 的职责设计、通信契约、Web 看板定位，以及当前优点、局限与后续演进方向。

## 总体架构

`research_mvp` 现在是一套“本地 tmux 常驻多 agent runtime + 文件状态层 + Web 观察/交互层”的系统，而不是传统的单体后端。它的核心目标不是“把模型封成一个 HTTP chat 接口”，而是让 `leader / researcher / trainer` 三个角色长期在线、可观察、可恢复、可协作。见 `research_mvp/runtime_cli.py:38` 和 `research_mvp/runtime.toml:1`。

从分层上看，系统分 5 层：

- 配置层：`runtime.toml` 定义 session 名、工作目录、runtime 数据目录、启动命令、agent 列表、提交键和超时参数。见 `research_mvp/runtime.toml:1`
- 运行时控制层：`runtime_cli.py` 负责启动 tmux、派发消息、维护任务状态、执行 supervisor 循环、检测 stalled、推进闭环。见 `research_mvp/runtime_cli.py:509`
- 持久化状态层：所有状态都落到 `.research-mvp-data/runtime/` 下的文件，不依赖数据库；包括 `thread.jsonl`、`tasks.json`、`state.json`、`agents/*.json`、`inbox/<agent>/*.json`。这是控制面状态目录，不是实验产物目录。当前仓库默认工作目录结构应为 `baseline/`、`src/baseline/`、`data/`、`output/`、`docs/`，其中实验输出落到 `workdir/output/baseline_v*/`，版本设计与结果总结落到 `workdir/docs/`。见 `research_mvp/runtime_cli.py:116`
- 训练执行子系统：`research_mvp/train_service/` 负责排队、执行、跟踪真实训练任务，它是 `research_mvp` 内部的独立子服务，不包含 LLM；runtime 通过协议与它交互，而不是让 `trainer` 长时间占住 tmux pane 跑正式训练
- Web 展示层：FastAPI 提供 `/runtime` 单页讨论看板和 `/api/runtime/*` 接口，用于实时展示 shared thread、任务、agent 状态，并允许 human 给指定 agent 发消息。见 `research_mvp/app.py:95` 和 `research_mvp/app.py:214`

## 运行机制

系统的常驻实体是一个 tmux session。默认 session 叫 `research-runtime`，每个 agent 对应一个固定 window。`up` 会检查 session 是否存在，不存在则创建；已存在则补齐缺失 window；每个 window 中运行的实际命令由 `codex_command` 决定，目前默认是 `codex --dangerously-bypass-approvals-and-sandbox`。`up` 完成后会默认直接进入 `supervise` 控制环，除非显式使用 `--no-supervise`。见 `research_mvp/runtime.toml:1` 和 `research_mvp/runtime_cli.py:435`。

需要强调的是，tmux runtime 负责的是“智能协作层”，不是“长时间训练执行层”。正式训练不应长期占住 `trainer` 的 agent pane，否则 runtime 会很难区分“正常长跑”与“agent 停住”。当前推荐机制是：`researcher` 负责代码、脚本、配置和最小 dry run；`trainer` 只负责训练任务提交、回调处理和结果整理；真正的长时间训练由 `research_mvp` 内部的 `train_service` 子系统执行。

agent 启动后第一件事不是自由工作，而是接受 bootstrap prompt。这个 prompt 把运行环境、共享目录、thread、inbox、CLI 命令路径写死，并强制它先阅读仓库协作协议、通信 skill 和自己的 identity 文件。也就是说，这套系统把 agent 行为约束拆成了三层：

- `AGENTS.md`：仓库级运行规则与通信契约。见 `AGENTS.md:1`
- `skills/runtime-communication/SKILL.md`：runtime 通信方法和命令规范。见 `research_mvp/skills/runtime-communication/SKILL.md:11`
- `identities/*.md`：每个 agent 的职责、默认汇报对象、约束和边界。见 `research_mvp/identities/leader.md:1`、`research_mvp/identities/researcher.md:1`、`research_mvp/identities/trainer.md:1`

消息流分成两条：

- `shared thread`：全局可见的讨论流，保存在 `thread.jsonl`，面向 human 可读性、跨 agent 上下文和审计记录。见 `research_mvp/runtime_cli.py:746`
- `per-agent inbox`：可执行消息队列，保存在 `inbox/<agent>/msg-*.json`，只有目标 agent 会被 `supervise` 投递到 tmux pane。见 `research_mvp/runtime_cli.py:208` 和 `research_mvp/runtime_cli.py:673`

`queue_message()` 是统一入口。无论是 human 发给 leader、leader delegate 给 worker、还是 system 触发催办，都会走这个函数：它负责写 inbox 和 thread。见 `research_mvp/runtime_cli.py:842`。

## 任务模型

`research_mvp` 早期曾尝试维护更强的结构化任务表，但当前主运行逻辑已经收敛为更轻的消息驱动控制环。`tasks.json` 仍可能存在于运行时目录中，但当前主路径依赖的是 shared thread、per-agent inbox、workflow_state 和 train_service 队列状态，而不是复杂的 task 状态机。

## Supervisor 机制

`supervise` 现在已经不是单纯投递 inbox，而是 runtime 的控制环。当前主逻辑聚焦于两类事情：

- 投递未送达 inbox 到 tmux pane
- 当已经有 human 首条消息、train_service 队列为空、且 runtime 长时间无动作时，提醒 leader 继续编排

入口在 `research_mvp/runtime_cli.py:956`。

这意味着系统不再依赖 agent 自己永远主动继续推进，而是让 runtime 在“人类任务已开始且训练服务为空闲”时催 leader 重新检查 thread、worker 进展和下一步派工。

## 闭环推进机制

当前系统的运行控制逻辑是“双层控制”：

- `runtime workflow`：负责任务拆分、review、dry run、结果汇总
- `training workflow`：负责训练排队、运行、完成、失败、取消、结果回传

## 四个 Agent 的设计

这套系统不是把四个 agent 当成“同质 worker”，而是明确做了非对称分工。

### leader

- 系统的编排者和收敛者
- 负责读取 human 请求、拆任务、派工、催办、请求 review、最终汇总
- 默认不是基础设施管理员，不应该去碰 `up / attach / supervise`
- 设计上它拥有 `closure ownership`：任务不是“有人产出文件了”就算完成，而是“最终报告产出并宣告完成”才算完成。见 `research_mvp/identities/leader.md:5`

### researcher

- 面向认知和分析产出
- 负责方案、矩阵、研究笔记、实现建议、源码阅读、`src/baseline/` 下训练代码、`baseline/` 下配置与脚本，以及最小 dry run
- 每设计完一个版本，应按当前仓库命名写出设计文档，例如 `docs/baseline_v11_1_exp.md`
- 它的输出通常是“可被整合的研究资产”，不是最终交付。见 `research_mvp/identities/researcher.md:5`

### trainer

- 面向训练任务提交和结果整理
- 不再承担长时间正式训练执行器的职责，也不再默认承担 dry run
- 负责训练任务提交、结果回收、训练证据链汇总和结果文档沉淀
- 每次训练结果回来后，应按当前仓库命名写出结果文档，例如 `docs/baseline_v11_1_exp_result.md`
- 它强调 reproducibility 和可验证性，而不是抽象结论。见 `research_mvp/identities/trainer.md:5`

这四个角色背后的设计理念是：

- `leader` 管 flow
- `researcher` 管认知资产
- `trainer` 管执行资产
- `leader` 也负责最终质量判断与闭环

其中真实训练执行不再由这四个 agent 之一长期承担，而是交给 `research_mvp/train_service/`。这意味着 `trainer` 更像“训练任务管理员”和“训练结果解释者”，而不是“GPU 长任务宿主”。

## 通信契约

这是系统稳定性的核心，不是附属文档。

现在已经明确的通信契约是：

- `shared thread` 用于可见性，不用于真正唤醒 worker
- 真正让某个 agent 开始工作的是 `targeted inbox delegation`
- worker 默认汇报给 `leader`，而不是 `all`
- `all` 只用于里程碑、共享产物、风险广播
- `train_service` 完成后，应通过 runtime 协议回发一条给 `trainer` 的消息，触发它继续汇总和上报
- 该回调消息会明确要求 `trainer`：
  - 分析结果
  - 落到 `docs/baseline_v*_exp*_result.md` 风格的结果文档
  - 再把摘要同步给 `leader`

这些规则分别编码在：

- `AGENTS.md:19`
- `research_mvp/skills/runtime-communication/SKILL.md:30`
- bootstrap prompt `research_mvp/runtime_cli.py:291`

也就是说，`research_mvp` 的“协议”不是口头约定，而是：

- 启动 prompt
- 仓库级规则
- role identity
- runtime skill
- 文件载荷结构

这 5 层共同塑造了系统行为。

## Web 看板设计

`/runtime` 单页不是业务前台，而是运行态控制台。它直接读取 runtime 文件状态，不走旧的 project abstraction。当前它主要展示三类信息：

- 消息流：shared thread 中最近的消息，带 `sender / recipient / timestamp / task_id`
- agent 卡片：在线状态、target、pending inbox、last event、latest message
- task 视图：当前 human request 下的任务列表、owner、status、due、stall_count

对应后端接口是：

- `/api/runtime/board`
- `/api/runtime/messages`

实现见 `research_mvp/app.py:214` 和 `research_mvp/static/runtime_board.html:279`。

这套 UI 的定位不是替代 tmux，而是：

- 给 human 一个“理解系统是否卡住”的窗口
- 给 human 一个“点对点发消息给某 agent”的入口
- 把 `thread / task / agent` 三个视角并排给出来

这是对 tmux 的补充，而不是取代。

## 当前优点与局限

### 优点

- 完全本地，无外部依赖数据库
- 对 tmux 和 CLI agent 友好
- 状态可审计，所有关键事件都落盘
- 控制环简单，行为更可预测
- Web 与 CLI 共用同一套 runtime 状态
- 已明确把“智能协作”和“正式训练执行”分层，后续更容易扩展独立训练服务

### 局限

- leader 的编排策略仍主要依赖 prompt，不是独立 planner
- workflow automation 仍然是少量规则，不是可配置 DAG
- 没有真正的 heartbeat / lease 文件更新协议
- 没有真正的任务依赖图和 artifact-level lineage
- `train_service` 已经作为 `research_mvp` 内部子系统落地，但训练协议和状态语义仍在继续收敛

## 建议的后续演进

如果要把 `research_mvp` 从“强原型”继续推成“稳定 runtime”，优先级建议如下：

1. 让 `docs/baseline_v*_exp*.md` 与 `docs/baseline_v*_exp*_result.md` 的模板更标准化
2. 继续完善 `research_mvp/train_service/`，提供更稳定的训练队列、运行态、日志与结果回调
3. 给 `/runtime` 增加更清晰的 train_service 协同视图
4. 把 leader 的版本收尾动作进一步自动化，例如收尾检查和提交前 checklist
5. 增加 `runtime doctor / runtime repair` 命令，专门处理坏 inbox、卡死 pane、异常 state

## 总结

`research_mvp` 当前最准确的定位是：

- 一个基于 tmux 的本地常驻多 agent runtime
- 一个以文件系统作为控制面的协作系统
- 一个由 supervisor 驱动的最小控制环
- 一个以 shared thread、inbox 和轻量控制环为核心的强原型
- 一个把正式训练执行下沉到 `research_mvp/train_service/` 的智能编排层
- 一个用 Web 看板辅助 human 理解和介入的运行态系统

它已经不是“几个 agent 在聊天”，而是在朝“可持续推进、可恢复、可审计的本地多 agent runtime”演进。
