# Train Service API

## 设计目标

`train_service` 是一个纯后端训练队列服务。提交任务时，你只需要告诉它：

- shell 脚本路径
- 这次实验关键的技术点
- 可选的脚本参数、工作目录、回调信息

服务会按队列顺序逐个执行脚本，并返回 `train_task_id`。

## `POST /jobs`

提交一个训练任务。

请求体：

```json
{
  "title": "birdclef baseline run",
  "script_path": "research_mvp/train_service/demo_scripts/delay_echo.sh",
  "technical_focus": [
    "cnn14 baseline",
    "specaugment",
    "mixup ablation"
  ],
  "script_args": ["5"],
  "workdir": ".",
  "runtime_task_id": "task-1234567890",
  "notify_agent": "trainer",
  "callback_url": "http://127.0.0.1:8090/api/runtime/training-callback",
  "notes": "dry run passed and ready for queue"
}
```

返回：

```json
{
  "ok": true,
  "train_task_id": "train-abcdef1234",
  "status": "queued"
}
```

## `GET /jobs`

返回全部训练任务、状态计数和队列摘要。

## `GET /jobs/{train_task_id}`

返回指定训练任务详情。

## `GET /jobs/{train_task_id}/logs?lines=120`

返回指定训练任务当前日志文件的尾部片段，适合前端或 agent 轮询查看正在运行的训练输出。

返回：

```json
{
  "job_id": "train-abcdef1234",
  "status": "running",
  "log_path": "/abs/path/to/train_log.txt",
  "exists": true,
  "lines": [
    "[train] startup {...}",
    "[train] epoch_progress {...}"
  ],
  "line_count": 2
}
```

说明：

- `lines` 参数范围是 `1..2000`
- 如果日志文件还没创建，`exists` 会是 `false`
- 该接口返回的是日志尾部若干行，不依赖直接访问 subprocess 句柄

## `GET /queue`

返回当前队列信息：

- `queued_count`
- `running_count`
- `queued_ids`
- `running_ids`
- `recent`

## `POST /jobs/{train_task_id}/cancel`

取消一个 `queued` 状态的任务。

## `GET /api/board`

供前端看板使用的聚合接口，返回：

- 数据目录
- 回调地址
- 状态计数
- 队列摘要
- 全部任务

## Shell 脚本执行约定

服务会按如下方式执行脚本：

```bash
bash <script_path> <script_args...>
```

并注入环境变量：

- `TRAIN_SERVICE_JOB_ID`
- `TRAIN_SERVICE_OUTPUT_DIR`
- `TRAIN_SERVICE_LOG_PATH`
- `TRAIN_SERVICE_TECHNICAL_FOCUS`
- `TRAIN_SERVICE_RUNTIME_TASK_ID`

服务不会解析结果文件，也不关心 artifact 或 summary。

它只做三件事：

1. 运行 shell 脚本
2. 把 stdout/stderr 追加到脚本同目录下的 `train_log.txt`
3. 约定训练脚本把正式输出写到 `<workdir>/output/baseline_v*/`
4. 回调 `research_mvp`

## `POST /callbacks/research-mvp`

这是一个辅助接口，用于模拟“外部执行器已经有结果，现在需要继续回调 `research_mvp`”。

默认情况下，`train_service` 自己在任务完成后就会自动回调 `research_mvp`，通常不需要手动调用这个接口。

## `research_mvp` 回调接口约定

默认回调到：

```text
POST /api/runtime/training-callback
```

请求体：

```json
{
  "job_id": "train-abcdef1234",
  "status": "succeeded",
  "title": "birdclef baseline run",
  "script_path": "/abs/path/to/train.sh",
  "technical_focus": ["cnn14 baseline", "specaugment"],
  "script_args": ["--epochs", "1"],
  "workdir": "/abs/path/to/workdir",
  "runtime_task_id": "task-1234567890",
  "notify_agent": "trainer",
  "log_path": "/abs/path/to/script_dir/train_log.txt",
  "notes": "dry run passed and ready for queue"
}
```
