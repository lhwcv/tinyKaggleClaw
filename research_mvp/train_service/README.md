# Train Service

`train_service` 是 `research_mvp` 内部的最小训练执行子服务。

它的目标不是做 LLM 编排，而是做三件事：

- 接收训练 shell 脚本任务
- 排队并执行一个个脚本
- 在任务完成后回调 `research_mvp`

## 当前能力

- `POST /jobs` 提交 shell 脚本训练任务
- `GET /jobs` / `GET /jobs/{train_task_id}` 查询任务
- `GET /jobs/{train_task_id}/logs?lines=120` 查看当前日志尾部片段
- `GET /queue` 查看队列里还有多少任务
- `POST /jobs/{train_task_id}/cancel` 取消任务
- 后台 worker 自动消费队列
- 使用 `.research-mvp-data/train-service/jobs.json` 作为文件队列
- 服务重启后会把残留的 `running` 任务重新排回 `queued`，继续消费剩余任务
- 完成后通过 HTTP 回调 `research_mvp`
- 自带单页看板 `/`

## Demo Scripts

- `research_mvp/train_service/demo_scripts/hello_world.sh`
- `research_mvp/train_service/demo_scripts/delay_echo.sh`

这两个脚本当前只用于验证队列、执行和回调链路。

## 运行

```bash
python -m uvicorn research_mvp.train_service.app:app --port 8100
```

打开：

```text
http://127.0.0.1:8100/
```

默认回调地址：

```text
http://127.0.0.1:8090/api/runtime/training-callback
```

可通过环境变量覆盖：

```bash
TRAIN_SERVICE_CALLBACK_URL=http://127.0.0.1:8090/api/runtime/training-callback
TRAIN_SERVICE_DATA_ROOT=/path/to/.research-mvp-data/train-service
```

## 与 research_mvp 的关系

- `research_mvp`：智能编排层
- `train_service`：正式训练执行层

推荐职责分工：

- `researcher` 写代码、配置、脚本
- `leader` review 是否批准训练
- `researcher` 完成最小 dry run
- `trainer` 负责把已验证通过的训练提交到 `train_service`
- `train_service` 负责排队、运行和回调结果
- `trainer` 收到结果后再向 `leader` 汇报

## Shell 脚本协议

服务会使用：

```bash
bash <script_path> <script_args...>
```

并注入这些环境变量：

- `TRAIN_SERVICE_JOB_ID`
- `TRAIN_SERVICE_OUTPUT_DIR`
- `TRAIN_SERVICE_LOG_PATH`
- `TRAIN_SERVICE_TECHNICAL_FOCUS`
- `TRAIN_SERVICE_RUNTIME_TASK_ID`

服务不会解析结果文件，也不关心 artifact/summary。

当前约定是：

- 脚本正常执行即可
- `train_service` 会把 stdout/stderr 追加到脚本所在目录的 `train_log.txt`
- 训练脚本的正式输出应写到当前 `workdir/output/baseline_v*/`
- 回调 `research_mvp` 时只带 `train_task_id` 和原始请求元信息
