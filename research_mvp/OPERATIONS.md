# research_mvp 运维手册

本文档描述 `research_mvp` runtime 的日常启动、停止、观察、排障、恢复和推荐操作流程。

## 1. 目标

`research_mvp` 的运维目标不是“部署一个 Web 服务”这么简单，而是保证以下三件事同时成立：

- tmux 中的三个 agent 持续在线
- supervisor 循环持续推进任务，不让系统静止
- human 能通过 CLI 或 `/runtime` 页面观察并介入

## 2. 关键组件

运行时涉及以下核心组件：

- tmux session：承载 `leader / researcher / trainer`
- `python -m research_mvp.runtime_cli up`：启动 tmux runtime，并默认进入控制环
- `train_service`：`research_mvp` 内部的训练队列与执行子服务，负责正式训练作业
- `python -m uvicorn research_mvp.app:app --port 8090`：Web 看板
- `.research-mvp-data/runtime/`：运行时状态目录，仅用于 thread/inbox/state 等控制面数据，不用于实验产物
- `<workdir>/docs/`：baseline 版本设计文档和结果总结文档
- `recipe/<name>/`：任务入口资料目录；如果 human 明确要求“开始 `recipe/<name>/` 任务”，应先读其中的 `data.md`、`overview.md`、`start_prompt.md`
- `<workdir>/eda/`：对 recipe/Kaggle 任务做前期数据理解时的脚本、分析笔记和图表输出目录

如果系统“停了”，通常不是所有组件都坏了，而是其中一层停止推进：

- tmux 不在
- agent pane 活着但不再工作
- `up`/控制环没跑
- 正式训练已提交到外部服务，但 runtime 把等待训练结果误认为 stalled
- Web 只是看板没刷新，但 runtime 实际还在

## 3. 标准启动流程

推荐启动顺序：

1. 启动 tmux runtime
2. 启动 train_service
3. 启动 Web 看板

命令：

```bash
python -m research_mvp.runtime_cli up
python -m uvicorn research_mvp.train_service.app:app --port 8100
python -m uvicorn research_mvp.app:app --port 8090
```

说明：

- `up` 负责启动或补齐 tmux runtime，并默认直接进入 `supervise`
- 如需只启动不进入控制环，可使用 `python -m research_mvp.runtime_cli up --no-supervise`
- `research_mvp/train_service/` 不属于 tmux runtime 生命周期的一部分，应作为单独 FastAPI 子服务启动和维护
- `train_service` 使用 `.research-mvp-data/train-service/jobs.json` 作为文件队列，重启后会把残留 `running` 任务重新排回 `queued`
- 如果训练队列非空但 shared thread 长时间无新活动，supervisor 会按 `train_queue_idle_reminder_seconds` 周期提醒 leader 不要空等训练结束，而要继续安排 trainer 巡检训练、researcher 并行补充研究文档
- Web 看板不是必须，但建议常开，方便观察 `/runtime`

## 4. 标准停止流程

停止 runtime：

```bash
python -m research_mvp.runtime_cli down
```

这会：

- kill 配置里的 tmux session
- 将 runtime 状态中的 agent 标记为 `offline`

如果只想停止控制环，不想停掉 tmux agent，则直接停止 `supervise` 所在进程即可。

## 5. 日常观察命令

### 5.1 查看 tmux/runtime 状态

```bash
python -m research_mvp.runtime_cli status
```

关注点：

- agent 是否 `online`
- `target` 是否正确
- `last_event` 是否异常

### 5.2 查看 shared thread

```bash
python -m research_mvp.runtime_cli thread tail -n 50
```

关注点：

- 最新 human 请求是什么
- 是否有带 `task_id` 的进展或完成消息
- 是否有 system 级催办和升级消息

### 5.3 查看 inbox

```bash
python -m research_mvp.runtime_cli inbox list leader
python -m research_mvp.runtime_cli inbox list researcher
python -m research_mvp.runtime_cli inbox list trainer
```

关注点：

- 是否有大量未送达消息
- 是否出现异常积压
- 某个 agent 是否一直收消息但没有后续进展

### 5.4 进入 tmux 观察现场

```bash
python -m research_mvp.runtime_cli attach
```

适用场景：

- 需要直接看 pane 输出
- 怀疑 agent 被 prompt 卡住
- 怀疑命令没有真正触发

## 6. Web 看板使用方式

打开：

```text
http://127.0.0.1:8090/runtime
```

建议用它观察三块信息：

- shared thread：现在系统正在讨论什么
- agent 卡片：谁在线、谁有 pending inbox、最近在处理什么
- task 视图：当前 human request 下有哪些 task、谁是 owner、谁 stalled

如果已经拆出训练服务，还应同时观察：

- 哪些 runtime task 正在等待外部训练结果
- 哪些训练 job 处于 queued / running / succeeded / failed

建议用它做两类操作：

- human 给某个 agent 发定向消息
- 人工确认系统是否已经停住，是否需要干预

## 7. 常见运行模式

### 7.1 最小工作流

适合手动控制：

```bash
python -m research_mvp.runtime_cli up
```

然后通过 `/runtime` 或 `thread send` 给 `leader` 发任务。

### 7.2 CLI 主导工作流

```bash
python -m research_mvp.runtime_cli thread send --to leader "你的任务"
python -m research_mvp.runtime_cli thread tail -n 50
python -m research_mvp.runtime_cli inbox list leader
```

适合在终端里观察和调试。

### 7.3 `recipe/<name>/` 启动工作流

如果 human 的请求是开始某个 `recipe/<name>/` 任务，推荐按下面的顺序启动：

1. 先阅读 `recipe/<name>/data.md`
2. 再阅读 `recipe/<name>/overview.md`
3. 再阅读 `recipe/<name>/start_prompt.md`
4. 先做 EDA，而不是立刻改 baseline 或开训
5. 把 EDA 脚本、分析结果和图表统一放到 `eda/`
6. 只有在任务目标、数据结构、评测方式和主要风险都明确后，才进入 baseline 与迭代阶段

### 7.4 Web 主导工作流

适合 human 在页面中观察 thread、task、agent 三个视角，并通过单页面发送消息。

### 7.5 训练服务协同工作流

推荐的训练闭环：

1. `researcher` 编写代码、配置和训练脚本
2. `researcher` 输出 `docs/` 下符合现有命名模式的设计文档，例如 `docs/baseline_v11_1_exp.md`，并完成最小 dry run
3. `leader` review 是否批准训练
4. `trainer` 把正式训练提交给 `train_service`
5. `train_service` 独立排队和运行
6. `train_service` 完成后通知 `trainer`
7. `trainer` 输出 `docs/` 下符合现有命名模式的结果文档，例如 `docs/baseline_v11_1_exp_result.md`，并把结果摘要同步给 `leader`
8. `leader` 基于结果决定是否进入下一轮

## 8. 故障排查

### 8.1 `status` 全部 offline

可能原因：

- tmux session 已经退出
- session 名和配置不一致
- agent 进程启动后立即退出

建议排查：

```bash
python -m research_mvp.runtime_cli status
python -m research_mvp.runtime_cli up
python -m research_mvp.runtime_cli attach
```

如果 `up` 失败，优先看 tmux pane 最后的输出。

### 8.2 thread 有消息，但 agent 不干活

可能原因：

- `supervise` 没有运行
- 消息只写进了 thread/inbox，没有持续投递
- agent pane 在线但被卡住

排查顺序：

1. 确认 `supervise` 常驻在跑
2. 看 inbox 是否积压
3. attach tmux 看 agent pane 是否真的在响应

### 8.3 大家都停了

这是最重要的故障场景。

先判断是哪一层停了：

- thread 是否还有新消息
- task 是否出现 `stalled`
- leader 是否收到 escalation
- tmux pane 是否还在线
- `supervise` 是否还在跑

推荐检查：

```bash
python -m research_mvp.runtime_cli thread tail -n 80
python -m research_mvp.runtime_cli status
python -m research_mvp.runtime_cli inbox list leader
python -m research_mvp.runtime_cli attach
```

如果只是任务停滞，通常不需要重启整个 runtime，先给 `leader` 或具体 stalled owner 发一条纠偏消息。

如果 `trainer` 只是等待外部训练结果，不应直接按 stalled 处理。先确认：

- `researcher` 是否已经完成最小 dry run
- `trainer` 是否已经完成正式训练提交
- 正式训练是否已经进入 `train_service`
- 当前等待的是外部 job 完成，而不是 agent 响应

### 8.4 inbox JSON 损坏

当前 runtime 已具备基础容错：

- 损坏的 inbox 文件会被改名为 `*.corrupt.json`
- supervisor 会跳过损坏文件继续跑

建议检查目录：

```bash
ls .research-mvp-data/runtime/inbox/leader
ls .research-mvp-data/runtime/inbox/researcher
ls .research-mvp-data/runtime/inbox/trainer
```

如果 `.corrupt.json` 频繁出现，优先检查是否有外部脚本并发写同一目录。

### 8.5 Web 正常，tmux 不正常

说明：

- Web 只是读取 runtime 文件状态
- 它不保证 tmux 一定健康

处理：

- 以 CLI 和 tmux 实际状态为准
- attach 到 tmux 看真实 pane 行为

### 8.6 tmux 正常，Web 看板不更新

说明：

- runtime 可能还在工作
- 问题只是 Web 服务或浏览器轮询

处理：

```bash
python -m uvicorn research_mvp.app:app --port 8090
```

同时看 `/runtime` 页面和 `thread tail` 是否一致。

### 8.7 `trainer` 被频繁催办，但其实训练正在跑

这是训练职责未拆分前最常见的误报场景。

正确处理方式：

1. 先判断 `researcher` 是否已经完成最小 dry run，以及 `trainer` 是否已经提交正式训练
2. 如果正式训练已经在外部运行，不要继续把 `trainer` 视为 stalled owner
3. 训练状态应以 `train_service` 队列和 job 看板为准
4. runtime 只在训练结束、失败、取消或需要人工介入时重新唤醒 `trainer`

## 9. 恢复策略

### 9.1 轻恢复

适用于：

- 某个 task stalled
- leader 没继续派工
- worker 没按协议汇报

建议动作：

- 先通过 `/runtime` 或 `thread send` 给 `leader` 一个纠偏消息
- 如有明确 owner stalled，则给 owner 或 leader 直接发一条带 `task_id` 的恢复指令

### 9.2 中恢复

适用于：

- supervisor 停掉了
- inbox 不再投递

动作：

```bash
python -m research_mvp.runtime_cli supervise
```

### 9.3 重恢复

适用于：

- tmux session 已死
- agent CLI 全部退出
- pane 状态异常且不可恢复

动作：

```bash
python -m research_mvp.runtime_cli down
python -m research_mvp.runtime_cli up
```

如果还需要 Web：

```bash
python -m uvicorn research_mvp.app:app --port 8090
```

## 10. 推荐操作原则

- 不要把 Web 看板当成唯一真相，tmux 现场和 runtime 文件状态同样重要
- 不要让 runtime 在 `up --no-supervise` 后长期无人接管控制环
- 不要把所有问题都归因于 prompt，先看 task、inbox、stalled 状态
- 不要让 worker 默认发 `all` 代替对 leader 的汇报
- 优先通过 `task_id` 追踪任务，而不是只看自然语言摘要
- 不要把正式训练长期挂在 `trainer` pane 中跑，正式训练应下沉到 `research_mvp/train_service/`

## 11. 推荐日常流程

建议的日常操作习惯：

1. `up`
2. `supervise`
3. 打开 `/runtime`
4. 给 `leader` 发 human 任务
5. 观察 task 视图和 thread
6. 看到 stalled 时优先做精确纠偏，而不是直接全局重启

## 12. 当前缺失的运维能力

当前还没有正式实现，但非常值得补：

- `runtime doctor`
- `runtime repair`
- 按 `task_id` 过滤 thread
- pane 输出级健康检查
- per-task heartbeat / lease
- runtime 与 `train_service` 的正式回调协议
- 独立训练 job 看板与 runtime task 的映射

这些能力补齐后，`research_mvp` 会从“可操作原型”进一步变成“可维护 runtime”。
