# Vision RSI Agent 使用说明

适用：Windows 源码版，项目目录 `F:\vision-rsi-agent`。更新日期：2026-10-12。

## 1. 当前能用到什么程度

这是开发预览版，可以试用自然语言需求澄清、任务接口定义、实验规划、SSH 训练、评测和记录追踪。COCO 是首个真实训练适配器，不是项目的能力边界。

当前真实结果：预训练基线完整 COCO val2017 box AP 为 46.7097；首轮微调为 45.5969，未达到目标 60。后续实验正在推进。尚无达标的 COCO 发布版本，不能仅凭任务代号获得满足 AP≥60 的推理能力。

通用研究与候选交付已有有限实现，但任意视觉任务的自动 harness 组装、真实多图/视频学习以及外层 RSI 的研究效率提升仍未完整验证。界面和模拟 Demo 不代表任务效果已达标。当前仅适合可信本地用户。

## 2. 启动与检查

打开 PowerShell：

```powershell
cd F:\vision-rsi-agent
.\vision-rsi.cmd --help
.\vision-rsi.cmd doctor --config config.local.json
```

使用 `vision-rsi.cmd`，无需修改 PowerShell 执行策略，也无需运行 `start-agent.ps1`。

启动器优先使用 `VISION_RSI_PYTHON`、项目虚拟环境或本机 Codex Python。需要指定环境时：

```powershell
$env:VISION_RSI_PYTHON = 'C:\你的Python目录\python.exe'
```

配置保存在本地 `config.local.json`，密钥通过 `DEEPSEEK_API_KEY` 读取；不要把密钥写入需求、配置示例、文档或 Git。已设置用户环境变量时无需再次输入。

`doctor` 只检查本地配置，不调用 API、不连接 SSH，也不证明训练或推理效果。显式运行 `llm-check`、`remote-check` 才会访问相应服务。

## 3. 第一次试用：只定义任务

建议使用新的任务代号，避免修改正在运行的 `my-vision-task`：

```powershell
.\vision-rsi.cmd training start --task-id my-first-trial --interactive --config config.local.json
```

出现输入提示后，直接用自然语言描述需求，例如：

> 我要实现 COCO 80 类目标检测。每个样本输入一张图片，输出检测框、COCO 类别 ID 和置信度，坐标为原图像素 xyxy。按完整 COCO val2017 的官方 box AP 验收，要求至少 60。保持数据集和评测协议固定，不使用隐藏测试做搜索反馈。请先整理任务接口、输入输出示例、需要的资源及仍缺少的信息，不要直接启动训练。

多图或视频任务也可在此描述，但需要明确“一次任务样本”的含义，例如：

> 每个样本包含同一对象的正面和侧面两张图片，需要联合判断并输出一个结果。

> 每个样本是一段视频，输出事件类别、开始时间和结束时间；请明确时间单位、是否使用音频及视频长度限制。

Agent 应整理这些需求；你无需手写 JSON Schema。查看它的理解，并用自然语言反复补充。不能把“接口已定义”理解为“对应模型后端已实现”。

交互界面每次只显示一个需要回答的问题，可以直接用中文回答；不确定时可以说“我不知道，请给我建议”。出现“待确认的新需求”时，界面优先显示新理解，输入“是”或“确认”接受，输入“否”保留原需求，也可以继续描述要修改的内容。这些确认只适用于当前需求草案，不会启动训练。预算和验收目标的变更会单独列出，请核对后再确认。`/show` 查看详细状态，`/contract` 查看完整接口。

首次启动无需填写示例占位目标 `--goal "Describe requirements"`；省略 `--goal` 后直接描述自己的任务即可。

常用交互命令：

| 命令 | 作用 |
| --- | --- |
| `/show` | 查看需求摘要 |
| `/contract` | 查看完整任务接口 |
| `/harness` | 生成冻结任务的执行规格，说明所需后端阶段；不启动训练 |
| `/budget 8` | 设置该任务初始 GPU 小时上限，示例为 8 |
| `/readiness` | 只读检查本地任务条件 |
| `/prepare` | 检查训练计划与资源；不启动训练，但可能访问 SSH |
| `/help` | 查看命令 |
| `/quit` | 保存并退出交互 |

GPU 预算必须由你明确设置，不能从示例自动推定。8 卡运行 1 小时计为 8 GPU 小时。已冻结的任务预算不能通过 `/budget` 重置。当前 COCO 任务的 192 GPU 小时授权不自动分配给新任务。

已有要求发生变更时，模型可能生成草案。核对差异后使用 `/accept` 接受，或 `/reject` 保留原要求；不要为消除提示而盲目接受。

## 4. 保存、退出和恢复需求交互

记下程序显示的 `session_id`。任务代号标识能力，会话 ID 标识这一次需求与研究记录，二者不能混用。

```powershell
.\vision-rsi.cmd training list
.\vision-rsi.cmd training show --session-id SESSION_ID --interactive --config config.local.json
```

将 `SESSION_ID` 替换为真实值。也可一次性说明目标：

```powershell
.\vision-rsi.cmd training start --task-id my-goal-trial --goal "这里直接写完整目标、输入、输出和验收要求" --config config.local.json
.\vision-rsi.cmd training reply --session-id SESSION_ID --message "这里补充或修正需求" --config config.local.json
```

这些需求交互会调用 LLM，产生 API 用量；本身不启动 GPU 训练。任务需求、实验指标、训练配置和预算可能被发送给配置中的 LLM 服务。

## 5. 开始训练和有界迭代

仅在需求、数据、权重、远端配置和预算齐全，且准备检查通过后执行：

```powershell
.\vision-rsi.cmd training prepare --session-id SESSION_ID --config config.local.json
.\vision-rsi.cmd training watch --session-id SESSION_ID --research-rounds 2 --watch-seconds 3600 --poll-seconds 60 --config config.local.json
```

第二条命令会产生真实 API/GPU 用量。`research-rounds 2` 是最多两次后续方法提案，不是两个训练 epoch，也不保证一定有两个成功实验。`watch-seconds` 是本地控制器观察时限，不是远端训练超时；远端作业受已冻结计划的独立时限约束。当前方法搜索固定检测器和预训练权重，只允许有限配方变更。

在交互会话中也可使用 `/run` 推进有界步骤，或 `/watch` 持续推进。启动交互时提供的研究轮数和观察时限会被沿用。

不要同时启动多个控制器操作同一会话。退出终端、Ctrl+C、`/pause` 都不会自动取消已提交的远端作业。

## 6. 如何观测、暂停和取消

```powershell
# 查看控制记录，取得 CAMPAIGN_ID
.\vision-rsi.cmd training campaigns --session-id SESSION_ID --config config.local.json
# 查看该任务的作业，取得 RUN_ID
.\vision-rsi.cmd training runs --session-id SESSION_ID --json
# 实时远端状态和日志
.\vision-rsi.cmd training status --session-id SESSION_ID --run-id RUN_ID --config config.local.json --json
.\vision-rsi.cmd training logs --session-id SESSION_ID --run-id RUN_ID --config config.local.json --json
```

`CAMPAIGN_ID` 是一次控制流程，`RUN_ID` 是一个具体训练作业。恢复或查询已有流程时使用其原始配置和确切 ID，不要随意新建流程。

```powershell
# 暂停后续决策，已有作业继续运行
.\vision-rsi.cmd training agent-pause --session-id SESSION_ID --campaign-id CAMPAIGN_ID --config config.local.json
# 请求停止一个具体远端作业
.\vision-rsi.cmd training cancel --session-id SESSION_ID --run-id RUN_ID --config config.local.json --json
# 再次查询，直到确认终态并结算资源
.\vision-rsi.cmd training status --session-id SESSION_ID --run-id RUN_ID --config config.local.json --json
```

取消请求返回时作业可能仍是 `running`，不能立即当作已经停止。网络观察超时也不代表任务失败，不要因此重新提交。

训练完成后需收集正式报告：

```powershell
.\vision-rsi.cmd training collect --session-id SESSION_ID --run-id RUN_ID --config config.local.json --json
```

看正式报告的 `box_AP`、完整覆盖及验收结果。loss 下降、进程 `completed` 或日志中出现“训练完成”，均不等于效果达标。低于阈值的版本不能作为达标能力发布。

## 7. Test：验收后的单输入与批量推理

先查询是否已有可用版本：

```powershell
.\vision-rsi.cmd capabilities
.\vision-rsi.cmd training release-status --session-id SESSION_ID --config config.local.json --json
```

只有已验收、完成服务检查并发布的版本才能用于正式 Test。没有可用版本时，先完成交付链；不要绕过验收注册失败模型。

以下命令中的 `TASK_ID`、`VERSION` 和输入文件均需替换为真实值：

```powershell
# 单个任务样本
.\vision-rsi.cmd test --task-id TASK_ID --version VERSION --input F:\data\sample.json --output F:\data\result.json
# 多个独立任务样本
.\vision-rsi.cmd test --task-id TASK_ID --version VERSION --manifest F:\data\samples.jsonl --output-dir F:\data\results
# 恢复同一个批量输出目录
.\vision-rsi.cmd test --task-id TASK_ID --version VERSION --manifest F:\data\samples.jsonl --output-dir F:\data\results --resume
```

输入必须符合 training 阶段冻结的合同，不能把任意图片路径直接当作所有任务通用的样本格式。单图合同若把输入字段命名为 `image`，样本通常形如：

```json
{
  "sample_id": "image-001",
  "inputs": {
    "image": {"type": "image", "uri": "F:/data/image-001.jpg"}
  }
}
```

字段名以实际合同为准，建议媒体路径使用绝对路径。JSONL 每行是一个完整样本，`sample_id` 唯一。

**联合多图与批量不同**：联合多图是在一个样本的某个 `image_list` 字段中放多张图片，产生一个任务结果；批量是多行独立样本。视频使用合同声明的 `video` 字段。格式示例见 `examples/multimodal-sample.json` 和 `examples/multimodal-batch.jsonl`，它们只说明协议，不证明真实模型理解能力。当前 COCO 适配器仅接受一张图，不能直接套用多图/视频示例。

## 8. 通用研究入口与当前边界

源码版新增后端代码生成与协议烟测入口（尚未接通 GPU 训练）：

```powershell
.\vision-rsi.cmd training harness-generate --session-id SESSION_ID --request-id backend-001 --repository . --output runs/task-harnesses --config config.local.json
.\vision-rsi.cmd training harness-smoke --bundle runs/task-harnesses/requests/backend-001/candidate.json --repository . --config config.local.json
```

生成调用LLM并创建独立Git候选，需先提交主仓库源码变更。烟测仅在成功生成 `candidate.json` 后执行，复用远端CPU隔离程序；固定检查ID防止重复执行不确定请求。`backend_protocol_smoke_passed` 不允许直接GPU训练，不证明阶段训练代码、依赖、数据或模型质量已验证。当前GPU执行连接仍待实现。生成拒绝会保存原因，不能通过改写历史响应绕过；API结果不确定时不自动重试。

交互中的 `/research`、`/research-watch` 属于通用任务研究；`/run`、`/watch` 属于 COCO 训练控制流程，不应混用。通用研究要求绑定合同、开发验证集和研究配置，并非定义任意任务后就能直接训练。

当前通用候选一体化交付 `/deliver "独立验收集路径" 最大延迟秒数` 仅覆盖已实现的事件 F1/有界 CPU bundle。需要先 `/research-pause`；不能用于发布 COCO AP 模型，也不能代表通用视频模型已达标。详细开发接口见 README。

## 9. 文件与常见问题

需求记录默认在 `runs/training-sessions`，训练账本与收集产物在 `runs/training-runs`，控制流程在 `runs/campaigns`，能力版本在 `runs/capabilities`。保留这些目录和验收依赖的原始媒体/标注，不要为“重试”删除账本或改写冻结记录。数据、权重、密钥与训练产物不提交 Git。

- **PowerShell 禁止脚本**：运行 `.\vision-rsi.cmd`。
- **需求还在 clarifying**：用 `/show` 查看真正缺少的信息，用自然语言补充；无需逐个手写内部字段。
- **prepare 被阻断**：根据 blocker 补齐资源/合同；不要将模拟指标当作真实检查结果。
- **test 找不到能力**：确认已发布版本和注册目录；创建任务本身不会产生推理能力。
- **源代码或配置变化后拒绝恢复**：保留原记录，核对冻结来源；不要强改哈希或覆盖旧计划。
- **共享服务器有正在运行的任务**：先观测，避免重复启动训练抢占 GPU。

推荐首次体验只走第 2～4 节。确认需求理解符合预期后，再显式进入第 5 节的真实训练。
