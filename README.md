# Vision RSI Agent

Windows 本地研究控制器，通过 SSH 调度独立 8 卡 H20 服务器；LLM 服务独立且可替换。
项目目标是通用视觉递归自我改进（RSI）研究 Agent，支持逐步扩展到不同视觉任务、数据集和评测协议。COCO 目标检测 box AP 只是第一个验证实验，不定义 Agent 的能力边界。当前版本只有确定性模拟闭环，**没有真实训练、COCO 指标计算；LLM 客户端已支持真实 API 调用**。

## 本地运行

需要 Python 3.10+ 和 Git；没有第三方依赖。从仓库根目录执行：

```powershell
python -m unittest discover -s tests -v
python -m vision_rsi doctor
python -m vision_rsi run --run-dir runs/demo
python -m vision_rsi run --run-dir runs/demo
```

第二次运行恢复相同结果，不重复消耗模拟预算。更改配置或提交版本后使用新 run-dir。
配置示例是模拟专用；`synthetic_box_ap` 不是检测性能，`spent_gpu_hours` 是模拟成本。
状态保存在忽略的 runs/ 中。当前单进程顺序执行，不支持多个控制器同时写同一目录。

## 配置与秘密

复制 config.example.json 到本地配置文件并填写 SSH 主机别名、远端目录、COCO 路径、准确模型 ID 和 Base URL。示例默认使用官方 `deepseek-flash` 与 `https://api.deepseek.com`。
API Key 仅从 DEEPSEEK_API_KEY 环境变量读取，doctor 只报告是否存在，绝不打印值。
不将密钥放入配置、Git 或聊天。OpenAI-compatible HTTP 客户端已接入；远程训练执行待实现；当前真实模式主动报错。
检测器、预训练权重、数据划分尚未选定，不推断 DeepSeek Flash 的准确模型名或服务地址。

## 项目范围

通用核心负责实验规划、候选追踪、预算、调度、恢复、记忆和策略改进。具体视觉任务通过任务适配器提供数据、训练配方、评测指标和错误分析；首个适配器计划用于 COCO 检测，当前模拟指标仍是该实验的占位数据。后续任务无需以 COCO 或 box AP 为前提。

## 研究约束

- 首先锁定检测器、权重校验和、数据版本、训练配方和评测协议，建立可复现基线。
- 内层规划实验、修改候选代码、训练、验证、分析错误；候选代码使用独立 Git 提交记录。
- 外层比较相同 GPU、LLM token 和时间预算下旧策略与新策略的研究效率。
- 调度、成本、恢复和指标计算由确定性程序负责。远端执行须记录真实 GPU 数量乘运行时间。
- 研究反馈使用固定本地验证集；隐藏测试不参与反复搜索。
- 数据集、模型权重、训练输出、SSH 私钥和 API Key 不进入 Git；不配置远端、不推送。

详见 PLAN.md。当前记录仅包含配置哈希、Git 提交、候选和模拟结果；尚无代码修改执行器。

## LLM 连通性验证

设置环境变量后执行 `python -m vision_rsi llm-check --config config.local.json`。该命令会发起一次付费真实请求，输出回复和服务端 token 使用量，不输出 Key。当前只验证模型连通性，尚未用于自动规划或代码修改；不自动重试，避免重复计费。`config.local.json` 已被 Git 忽略。

## 策略对照骨架

`python -m vision_rsi compare --run-dir runs/comparison` 运行顺序搜索与基于历史最优结果的局部搜索，使用相同种子、候选空间和模拟预算。结构化产物保存在 `comparison.json`，含 Git 版本、候选配方、指标与模拟成本。该命令当前使用固定 fixture 参数，不读取配置中的预算或任务；不代表真实研究效率，也尚未整合进可恢复调度器。

## 远端只读检查

`python -m vision_rsi remote-check --config config.local.json --run-dir runs/remote-check` 检查 SSH、GPU 占用、Python 包可发现性和挂载盘空间，保存 `remote-environment.json`。使用已信任的 SSH 主机密钥和非交互认证；不会安装依赖或启动训练。`remote.python` 可指定解释器，`remote.ssh_port` 默认为 22。包可发现不等于导入或 CUDA 运行成功。

## 持久 CPU 任务验证

远端配置需要专用绝对 `workspace`。任务文件保存在 `<workspace>/jobs/<job-id>/`；提交只写入该项目目录。

```powershell
python -m vision_rsi job-submit --config config.local.json --job-id cpu-smoke-001
python -m vision_rsi job-status --config config.local.json --job-id cpu-smoke-001
python -m vision_rsi job-logs --config config.local.json --job-id cpu-smoke-001
python -m vision_rsi job-cancel --config config.local.json --job-id cpu-smoke-001
```

默认是约 2 秒的真实 CPU 测试。`--job-spec` 可提供 JSON 文件，包含命令参数列表 `argv` 和 `timeout_seconds`（不超过 300 秒）。命令按参数执行，不经过 shell；任务环境隐藏 CUDA 设备，但这不是安全沙箱，不应执行不可信命令。当前成本记录仅适用于 CPU 测试，不可用于 GPU 训练。

任务脱离 SSH 会话运行，保存状态、退出码、耗时和日志；相同 ID/规格重复提交返回已有任务，不会重跑，规格冲突报错。取消通过文件请求由 worker 处理，超时和取消先向子进程组发送 SIGTERM，3 秒后必要时 SIGKILL。日志读取最多返回末尾 16 KiB，远端日志总量尚未限制。

控制器退出后可凭任务 ID 恢复查询。服务器重启、worker 丢失和提交中途崩溃不自动重新执行：运行进程身份失配返回 lost；提交不完整报错，queued 状态也可能需要人工检查。尚未接入 GPU 准入、训练产物传输、调度队列和研究状态机。此版本只验证持久执行协议。

## 一键端到端 Demo

```powershell
python -m vision_rsi demo --config config.local.json --run-dir runs/live-demo
```

真实调用 DeepSeek 最多 2 次，在远端运行 3 个 CPU 合成实验（固定基线 + 两个候选），生成 `demo-state.json` 和 `report.html`。指标是确定性合成分数，实际 GPU 小时为 0，不进行 COCO 训练、不执行 LLM 代码。配置中的训练预算不用于此 demo；实验数固定为 3，每任务超时 15 秒，每次 LLM 输出上限 1024 tokens，记录真实 API token 用量，但不设总 token 成本硬上限。

LLM 只能选择未使用的白名单候选，并给出解释。远端指标需通过配方哈希、有限数值及 fixture 一致性校验。按同一目录重跑恢复已记录任务；完成后不再调用 API 或 SSH。配置、源码或 Git 版本改变后需新目录。API 请求中途崩溃会保留 requesting 状态并停止自动重试，避免重复计费；进程硬退出遗留的 demo.lock 需确认控制器已退出后手动移除。当前为闭环连通性演示，不是完整 RSI 算法或检测基线。


## 长程研究记录与观测台

主线已调整为长程自主视觉研究，早期固定配方 demo 是基础设施测试。当前新增 SQLite 持久事件库与只读交互观测台，尚未实现后台自主研究执行器。

```powershell
python -m vision_rsi research-import --source runs/demo-final/demo-state.json --run-dir runs/observatory
python -m vision_rsi research-view --run-dir runs/observatory
python -m vision_rsi research-event --run-dir runs/observatory --event-file event.local.json
```

事件文件格式为 `{"key":"唯一请求ID","kind":"evidence","payload":{"summary":"可核查摘要","refs":["已有事件key"]}}`。支持 objective、evidence、hypothesis、action、result、reflection、self_change、paused、resumed。新研究可用 objective 事件初始化；已有研究的目标不可覆盖。result 必须引用已有 action，并提供终态 status，每个行动仅一个结果。self_change 仅接受 proposed；尚无采用协议。

同 key/内容重试不增加记录，内容冲突报错。SQLite 是事实来源，HTML 是生成快照；CLI 更新后需生成并刷新。事件时间为记录入库时间，导入历史动作的原始执行时间见 remote_result。导入不发 API 请求或重跑远端任务。暂停只阻止新增假设、行动和自我修改提案，已有任务的结果仍可入库，不会取消远端任务。

观测台支持时间线、证据与假设、行动与结果、自我改进筛选，以及关键词搜索、引用导航和 JSON 详情。当前演示状态与阻塞说明针对既有 Demo，不是通用实时调度状态；预算调度与自动采集仍待接入。数据库和 HTML 均位于忽略的 runs 目录，请保留数据库以恢复研究记录；本地 SQLite 不提供防恶意篡改保证。

## 有界研究行动循环

```powershell
python -m vision_rsi research-step --config config.local.json --run-dir runs/observatory --steps 2
```

读取目标与最近 16 条事件，真实调用模型选择下一行动，执行后自动生成观测台。当前支持 inspect_repository（固定跟踪源码摘录）、remote_environment（SSH 只读检查）、synthesize（模型解释，不是验证后的科学结论）。每次推进 1–3 步，每研究目录最多 6 次规划请求，单次输出上限 1536 tokens；尚无输入 token 或费用总预算。DeepSeek Flash 的结构化规划按官方 thinking 参数关闭思考模式；其他 provider 保持默认行为。

成功完成的工具不重复选择，先收集观察再开放总结。所有结果记录自动关联行动；模型引用必须指向已存在记录。网络响应不确定时停止自动重试，非法/空响应记录为规划拒绝，下次显式推进可发新请求。恢复尚未完成的只读行动时可能重新读取环境，但不会重新请求已保存的规划；只读观察重做不等于 GPU 任务重试。已暂停研究不会启动新行动；外部同时写入暂停与行动启动之间仍存在竞争窗口，当前控制器是单实例有界执行。

本地 controller.lock 防止两个控制器同时运行，硬退出后的锁需确认无控制器后移除。通过事件详情检查规划响应、使用量、工具参数和观察结果；模型正文只作为待校验数据。当前不会执行任意 shell 或模型生成代码，不修改 Agent 自身，不进行训练。它是长程行动循环的最小接口，尚非无人值守研究系统。
