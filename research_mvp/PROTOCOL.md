# research_mvp 协议说明

本文档描述 `research_mvp` runtime 当前的通信协议、文件协议、任务协议和状态迁移规则。

## 1. 协议目标

协议层存在的目的，是把“多 agent 聊天”变成“多 agent 可持续协作”。

核心目标：

- 明确谁对谁说话
- 明确哪些消息只是可见性更新，哪些消息会触发执行
- 明确一个任务如何被创建、推进、阻塞、完成和催办
- 明确 human、leader、worker、system 在文件层各写什么

## 2. 运行时文件协议

runtime 根目录通常是：

`/.research-mvp-data/runtime/`

关键文件：

- `thread.jsonl`
- `tasks.json`
- `state.json`
- `agents/<agent>.json`
- `inbox/<agent>/*.json`
- `workflow_state.json`

补充说明：

- `research_mvp/train_service/` 负责维护正式训练 job 的详细状态
- `research_mvp` runtime 不直接托管长时间训练进程，只保留与训练 job 相关的任务、通知和结果摘要
- 当前仓库默认工作目录结构应为：
  - `recipe/`
  - `baseline/`
  - `src/baseline/`
  - `data/`
  - `eda/`
  - `output/`
  - `docs/`
- 其中：
  - `recipe/<name>/data.md`、`recipe/<name>/overview.md`、`recipe/<name>/start_prompt.md` 是 recipe 启动资料
  - `eda/` 用于前期 EDA 脚本、笔记和图表
  - `docs/baseline_v*_exp*.md` 用于版本设计文档
  - `docs/baseline_v*_exp*_result.md` 用于训练结果总结文档

### 2.1 `thread.jsonl`

作用：

- shared visible discussion log
- 人类可读
- 全局上下文
- 审计记录

单行事件的典型字段：

- `timestamp`
- `from`
- `to`
- `type`
- `content`
- `task_id`，如果该消息属于某个 task
- `parent_task_id`，如果该消息有上游任务关系

### 2.2 `inbox/<agent>/*.json`

作用：

- 面向特定 agent 的可执行消息
- 由 `supervise` 投递到 tmux pane

典型字段：

- `timestamp`
- `from`
- `to`
- `type`
- `content`
- `task_id`
- `parent_task_id`
- `delivered_at`
- `delivery_status`

### 2.3 `tasks.json`

`tasks.json` 仍可能存在于运行时目录中，但当前主控制路径已经不再强依赖复杂任务状态机。当前更重要的是：

- shared thread
- per-agent inbox
- workflow_state
- `research_mvp/train_service/` 的文件队列状态

## 3. 通信协议

当前通信协议采用“双通道”。

### 3.1 shared thread

shared thread 用于：

- 可见性
- 计划说明
- 跨 agent 上下文同步
- milestone 更新
- blocker 记录
- completion 记录
- 面向 human 的训练提交摘要和训练结果摘要
- 版本设计文档和结果文档的落盘说明
- `recipe/<name>/` 启动阶段的理解结论和 EDA 里程碑说明

shared thread 不负责真正唤醒 worker。

### 3.2 targeted inbox

inbox 用于：

- 可执行任务
- 明确 owner 的派工
- 系统催办
- leader 跟进
- system 升级
- `train_service` 完成后对 `trainer` 的结果通知

如果希望某个 agent 真正行动，必须给它定向 inbox message。

### 3.3 为什么不能只靠 `leader -> all`

因为 shared thread 是广播流，不是 delivery queue。

`leader -> all` 的价值在于：

- human 能看到
- 其他 agent 能理解当前局面

但 worker 是否真的被唤醒，取决于：

- 是否有 inbox message
- `supervise` 是否正在运行
- 消息是否被投递到 tmux pane

## 4. actor 角色协议

### 4.1 human

human 可以：

- 发起顶层请求
- 直接给 leader 发任务
- 必要时给特定 worker 或 leader 发纠偏消息

human 不应该频繁微操每个细小任务，否则会削弱 leader 的编排价值。

### 4.2 leader

leader 的协议职责：

- 接 human 顶层请求
- 拆分成 direct delegation
- review `researcher` 产出的代码、配置和训练脚本
- 决定是否批准把训练任务交给 `trainer`
- 通过 inbox 派工
- 在 shared thread 中做简短总结
- 接收 worker 进展与 blocker
- 必要时由 leader 自己完成结果审查与收口判断
- 负责最终收口
- 如果 human 的请求是开始 `recipe/<name>/` 任务，leader 应先组织 recipe 阅读和 EDA，再进入 baseline 迭代
- 每逢 5 个 baseline 版本节点，leader 应主动对比当前路线与参考方案、历史强方案或新检索到的方案，并总结差异与可借鉴点
- 如果这些对比中出现值得吸收的思路，leader 应把它们进一步转成具体实验或后续委派，而不是停留在抽象复盘

### 4.3 researcher / trainer

worker 的协议职责：

- 收到 inbox 消息后开始执行
- 默认向 `leader` 汇报
- 只在需要共享里程碑或高价值审查时使用 `all`
- 若收到的消息含 `task_id`，后续每条 progress / blocker / completion 都必须带同一个 `task_id`

补充职责分工：

- `researcher` 负责训练代码、配置、脚本和实验设计
- `researcher` 负责训练代码、配置、脚本、版本设计文档和最小 dry run
- `researcher` 在 `recipe/<name>/` 任务中应先阅读 recipe 资料并完成 EDA，再提出训练和实验迭代方案
- `trainer` 负责提交正式训练到 `train_service`、接收结果并整理回报
- `trainer` 不应长期把正式训练挂在自己的 tmux pane 中执行
- `researcher` 应在每个版本设计完成后写 `docs/` 下符合现有基线命名的设计文档，例如 `docs/baseline_v11_1_exp.md`
- `trainer` 应在每次结果返回后写 `docs/` 下符合现有基线命名的结果文档，例如 `docs/baseline_v11_1_exp_result.md`
- `leader` 自行判断训练结果是否足以支撑下一轮决策或最终综合

## 5. 消息创建协议

消息主要由以下入口创建：

- `send`
- `thread send`
- `delegate`
- `system` 自动催办与升级
- workflow automation 自动补发

统一入口是 `queue_message()`。

### 5.1 human 顶层请求

当 sender 是 `human` 且启用 task record：

- 会创建一条 thread 记录
- 会写入目标 inbox
- 会创建一个顶层 task
- 该 task 的 `kind` 为 `human_request`

### 5.2 leader delegate

当 leader 派工时：

- 会写入目标 worker inbox
- 会追加一条 thread 记录
- 会创建一个 `delegation` task

训练前置链路通常是：

- `leader -> researcher`：准备 `src/baseline/` 代码、`baseline/` 下配置与训练脚本，以及 `docs/baseline_v*_exp*.md` 风格的设计文档
- `researcher -> leader`：提交候选训练包，并说明最小 dry run 已通过
- `leader -> trainer`：要求提交正式训练

### 5.3 system nudge / escalation

当 system 检测到 stalled 或 workflow 缺口时：

- 可以给 owner 发催办
- 可以给 leader 发升级提醒
- 会尽量保持同一个 `task_id`

system 催办的目标不是创造新的业务任务，而是推动原任务恢复执行。

### 5.4 `train_service` 完成通知

当正式训练完成后，推荐由 `research_mvp/train_service/` 通过 runtime 协议向 `trainer` 发送一条消息：

- `from = system` 或 `from = train_service`
- `to = trainer`
- `content` 包含 job 标识、结果摘要、关键指标、产物路径或失败原因
- 如果能映射回原任务，应尽量附带同一个 `task_id`

这条消息的作用是重新唤醒 `trainer`，让它：

- 检查结果
- 写 `docs/baseline_v*_exp*_result.md` 风格的结果文档
- 向 `leader` 汇报摘要

## 6. `task_id` 协议

`task_id` 是 runtime 早期结构化设计里使用过的锚点，但当前主路径已弱化了对它的依赖。

### 6.1 生成时机

以下情况通常会产生新的 `task_id`：

- human 发起新的任务
- leader 或 system 创建新的委派任务

### 6.2 传播时机

当消息属于某个 task：

- inbox JSON 写入 `task_id`
- thread 事件写入 `task_id`
- agent 收到投递 envelope 时会看到 `Task ID: ...`

### 6.3 回报规则

worker 如果正在处理某个带 `task_id` 的任务，必须：

- 在 progress update 中带 `task_id`
- 在 blocker report 中带 `task_id`
- 在 completion message 中带 `task_id`

### 6.4 设计意义

这样 `sync_task_progress()` 就可以：

- 精确找到对应 task
- 准确更新 status
- 不再主要依赖自然语言猜测

## 7. `task_marker` 协议

`task_marker` 用于标识当前人类任务轮次。

设计原因：

- runtime 是长期运行的
- thread 会持续增长
- 多轮任务会混在一条 shared thread 中

所以系统用最近一条 human 消息时间戳作为“当前轮次锚点”，把当前 human request 下的 tasks 聚合起来。

这不是完美方案，但足够把“当前轮任务”和“历史轮任务”大体区分开。

## 8. 任务状态协议

当前系统更依赖轻量消息驱动和 train_service 队列状态，而不是完整的任务状态集合。

### 8.1 `assigned`

表示任务已经创建，并指派给 owner，但还没有足够证据表明 owner 已经开始推进。

进入方式：

- human request 创建
- leader delegate 创建
- workflow automation 创建

### 8.2 `in_progress`

表示 owner 已经开始推进，但还未完成，也未进入明确 blocked。

进入方式：

- owner 用带 `task_id` 的消息汇报进展
- 或兼容模式下，系统从 owner 的后续消息推断其已开始处理

### 8.3 `blocked`

表示 owner 明确表示无法继续，或者需要额外输入、批准或条件。

进入方式：

- owner 的 thread update 含 blocker 语义
- 优先通过带 `task_id` 的消息触发

### 8.4 `completed`

表示 owner 明确表示该 task 已完成。

进入方式：

- owner 的带 `task_id` completion message
- 兼容模式下，系统也会用 completion 关键词做兜底判断

### 8.5 `stalled`

表示任务长时间没有进展，runtime 主动判定需要催办或升级。

进入方式：

- 当前状态仍处于活动态
- 没有完成
- 超过 stall timeout
- 不在 nudge cooldown 期间

重要限制：

- `stalled` 只应用于 runtime 内 agent 本应继续响应却没有响应的情况
- 如果某任务已经提交到 `research_mvp/train_service/` 并在正常排队或运行，不应继续按普通 stalled 处理

### 8.6 `waiting_external_job`

表示 runtime 内的智能体阶段已经完成，后续在等待外部训练服务返回结果。

进入方式：

- `trainer` 完成 dry run
- `trainer` 成功把正式训练提交给 `train_service`

离开方式：

- `train_service` 返回完成通知，转回 `in_progress`
- `train_service` 返回失败通知，转到 `blocked` 或触发新的训练委派

## 9. 状态迁移规则

当前状态迁移的优先级是：

1. 显式 `task_id` 驱动
2. 兼容性 owner-message 推断
3. system stalled 判定

### 9.1 显式更新优先

如果 thread 中的消息包含 `task_id`，并且 sender 与 task owner 一致：

- blocker 语义：转到 `blocked`
- completion 语义：转到 `completed`
- 其他正常进展：转到 `in_progress`

### 9.2 兼容推断

如果某个 task 还没有任何显式 `task_id` 进展：

- 系统会回退到按 owner、assigned_at 之后的消息进行推断

这是过渡期兼容设计，不是最终理想方案。

### 9.3 stalled 转移

当 active task 超时：

- 转到 `stalled`
- 记录 `last_nudge_at`
- 增加 `stall_count`
- 给 owner 发同 task 的催办
- 如果 owner 不是 leader，再给 leader 发升级提醒

如果 task 已处于 `waiting_external_job`，stalled 判定应跳过，或者切换到独立的外部 job 健康检查逻辑。

## 10. Supervisor 协议

`supervise_once()` 当前协议上承担四个职责：

1. deliver inbox
2. sync task progress
3. detect stalled tasks
4. advance workflow

未来应补充第 5 步：

5. reconcile external training jobs

这意味着 supervisor 不再只是送信，而是 runtime 的最小控制环。

## 11. workflow 协议

`advance_workflow()` 目前不是通用 DAG，只是少量闭环兜底规则。

当前已有的两条：

- trainer 报告结果后而 leader 未收尾：请求 leader `final synthesis`

训练拆层后的推荐闭环：

- `researcher` 提交训练代码包后，`leader` 必须先 review 是否批准训练
- `trainer` dry run 通过后，才允许把正式训练提交给 `train_service`
- `train_service` 完成后，必须唤醒 `trainer`
- `trainer` 检查结果后，必须把结果摘要汇报给 `leader`
- 必要时由 `leader` 自行补做结果审查

协议意义：

- 它不替代 task 状态机
- 它补的是业务闭环缺口

## 12. Web 协议

Web board 使用的是 runtime 文件状态，不是单独的业务存储。

### 12.1 `GET /api/runtime/board`

返回：

- runtime 配置路径
- session 名
- workdir
- runtime 根目录
- thread 路径
- workflow_state
- task_summary
- agents
- messages

### 12.2 `POST /api/runtime/messages`

human 通过该接口发消息：

- 写入 thread
- 写入 inbox
- 必要时创建 task

### 12.3 页面展示协议

`/runtime` 页面当前展示：

- thread 消息流
- `task_id` 标签
- agent 卡片
- task 列表

页面的协议作用，是帮助 human 把“消息、任务、owner”三者关联起来。

## 13. 并发与容错协议

因为系统是文件驱动的，所以文件并发安全非常重要。

### 13.1 普通 JSON

普通 JSON 文件采用：

- 临时文件写入
- flush + fsync
- replace

### 13.2 JSONL

`thread.jsonl` 使用文件锁和 flush/fsync，尽量减少并发追加问题。

### 13.3 inbox 损坏处理

如果 inbox 文件解析失败：

- 改名为 `*.corrupt.json`
- supervisor 继续运行

这保证单条坏消息不会拖垮整个控制环。

## 14. 当前协议的优点

- 简单，易调试
- 可审计
- 本地优先
- 能区分可见性消息和执行消息
- 已经具备最小结构化任务能力
- 已经具备最小 stalled recovery 能力

## 15. 当前协议的局限

- 仍然有部分状态迁移依赖 heuristics
- `task_marker` 仍然比较粗糙
- 没有正式的 heartbeat / lease 协议
- 没有标准化 artifact 协议
- 没有标准化 review decision schema
- 还没有正式的 runtime 与 `train_service` 回调协议

## 16. 推荐协议演进

建议按下面顺序继续收紧协议：

1. 明确 `status intent` 字段，而不是只靠文本内容表达
2. 引入 `waiting_external_job` 一类的外部执行状态
3. 引入 `heartbeat` 或 `lease` 文件协议
4. 引入标准化 `artifact` 引用字段
5. 引入按 task 层级表达依赖关系的 schema
6. 引入 `runtime doctor / repair` 协议

## 17. 总结

`research_mvp` 当前协议的核心可以概括为：

- thread 管可见性
- inbox 管执行
- tasks 管状态
- supervisor 管推进
- `task_id` 管精确关联

这套协议层是整个 runtime 能持续运行的基础。
