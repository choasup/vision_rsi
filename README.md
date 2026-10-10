# Vision RSI Agent

Windows 本地 CLI，通过 SSH 调度视觉研究任务。核心入口是 `training start`（自然语言定义与澄清）、`training watch`（持续研究控制）和 `test`（按已验收任务版本推理）。COCO 检测是首个真实任务适配器。

当前开发状态：已实现真实 LLM、SSH 作业、固定检测器训练/恢复、官方 COCO 指标计算、结果验收及版本化推理接口；H20 小规模开发验证已执行。完整 COCO 训练和 AP≥60 验收尚未完成，没有真实达标 COCO 能力，也尚无通用 RSI 效率提升的独立证据。当前应用只支持可信本地用户，不是公网多用户服务。

首次使用（在项目根目录 PowerShell 中）：

```powershell
.\vision-rsi.cmd training start --task-id your-task --interactive
# 根据上一步显示的会话 ID 查看和补充需求
.\vision-rsi.cmd training show --session-id SESSION_ID
.\vision-rsi.cmd training reply --session-id SESSION_ID --message "补充执行预算及仍待明确的要求"
# 只检查计划和资源，不启动训练
.\vision-rsi.cmd training prepare --session-id SESSION_ID
# 配置和预算齐全后，开始有界研究（该命令可产生真实 API/GPU 用量）
.\vision-rsi.cmd training watch --session-id SESSION_ID --research-rounds 2 --watch-seconds 3600
```

交互会话内可用 `/budget N` 设置你选择的初始 GPU 小时上限（例如 `/budget 32`），无需再调用 LLM；已定义的上限不能用该命令改写或重置。也可使用 `vision-rsi.cmd training budget --session-id SESSION_ID --gpu-hours N`。这个操作不启动训练、不修改其它资源上限，只清除系统生成的对应预算问题，其它待澄清问题保留。

交互会话内可直接输入 `/prepare` 检查计划、`/run` 推进执行、`/watch` 持续观察，无需复制会话 ID。`/status` 查看本地控制记录，`/job` 实时核查远端作业，`/logs` 读取日志。`/pause` 暂停后续决策，`/resume` 恢复决策；已提交作业不会被取消。`/help` 列出命令。执行沿用启动参数（例如 `--research-rounds 2 --watch-seconds 3600`）及原会话预算；未知斜杠命令不发给 LLM。

需求用自然语言描述目标、输入、输出和效果要求即可；Agent 整理接口，不要求手写 schema。GPU 预算不自动推定，8 卡运行 1 小时计为 8 GPU 小时。`watch` 退出保留记录，远端已提交作业继续受原时限约束。完整推理验收通过后才能使用 `test --task-id ...`；首次任务尚未验收时不能靠代号取得达标输出。下方按阶段列出详细操作和限制。

Training的自然语言澄清会保留已定义的要求。模型提出目标、输入输出、验收指标/阈值/协议或预算变更时，只保存为草案，原定义继续保留；新计划、harness和advance会等待处理该草案。交互模式显示差异，使用`/accept`接受当前草案、`/reject`保留原要求，或继续自然语言修正。非交互模式明确指定草案版本，防止误接受旧版本：

```powershell
.\vision-rsi.cmd training show --session-id SESSION_ID
.\vision-rsi.cmd training accept --session-id SESSION_ID --version DRAFT_NUMBER
# 或拒绝；完整生效定义与草案可用show --json查看
.\vision-rsi.cmd training reject --session-id SESSION_ID --version DRAFT_NUMBER
```

这是已建立结构化要求的变化保护；不是对首次自然语言理解正确性的证明。第一次需求整理仍需查看摘要。接口描述或目标措辞变化也会显示供核对，实施假设/待回答问题的更新不强制变更确认。显式training define视为用户直接提供新定义，仍执行接口校验。

已有Training会话可直接推进控制流程：

```powershell
.\vision-rsi.cmd training advance --session-id SESSION_ID --steps 3
# 开启至多2轮基于实际失败证据的方法提案；后续advance/status/pause/resume保持同一参数
.\vision-rsi.cmd training advance --session-id SESSION_ID --steps 3 --research-rounds 2
.\vision-rsi.cmd training agent-status --session-id SESSION_ID
.\vision-rsi.cmd training agent-pause --session-id SESSION_ID
.\vision-rsi.cmd training agent-resume --session-id SESSION_ID
.\vision-rsi.cmd training campaigns --session-id SESSION_ID
# 按ID恢复已保存的策略和研究轮数，不必重新输入它们
.\vision-rsi.cmd training agent-status --session-id SESSION_ID --campaign-id CAMPAIGN_SHA256
.\vision-rsi.cmd training advance --session-id SESSION_ID --campaign-id CAMPAIGN_SHA256
# 前台持续观察并推进同一个控制流程；Ctrl+C保留记录，不取消远端作业
.\vision-rsi.cmd training watch --session-id SESSION_ID --campaign-id CAMPAIGN_SHA256 --watch-seconds 3600 --poll-seconds 15
# 从冻结计划/原始收据/只读账本重核成本与指标，不执行训练或调用模型
.\vision-rsi.cmd training audit --session-id SESSION_ID --campaign-id CAMPAIGN_SHA256
```

advance每次最多执行1..10个控制动作，持久化准备计划、提交、查询、收据收集和结果分析；远端仍在运行时返回等待，下次调用恢复同一个作业。动作选择使用控制步数，GPU预算独立由Training调度账本预留/结算，二者不混用。agent-pause只暂停继续决策，已经提交的远端作业仍按原超时/预算运行；需停止作业时使用training cancel。

watch是有期限的前台监督，不是后台服务。它固定同一campaign，刷新最新会话与配置并推进可执行动作；等待远端时按5..60秒间隔观察，同一作业的观察失败最多重试3次。不自动重发不确定的LLM请求或提交/恢复操作。需求变更、缺配置、预算耗尽、暂停、丢失worker或需要人工处理时停止。watch-seconds范围1..86400，期限到达后不发起下一轮，已经开始的有界调用可能稍晚返回；远端作业仍遵循自己的GPU预算和超时。Ctrl+C也不会取消它。结束原因、次数和耗时保存在campaign的watch-runs目录；--json的进度写stderr，最终结果写stdout。

audit区分已结算GPU小时和未释放预留，GPU范围覆盖整个会话，避免只选成功实验而漏掉其他成本；指标只采集该campaign关联的运行，并重核原始收据、计划及任务要求。新动作保存策略选择和每次工具尝试的墙钟耗时，缺失/中断/旧版耗时不能当作零；该时间不是CPU使用量，也不包括等待间隔。LLM计数范围是当前campaign的方法提案，使用API保存的usage，缺失或不确定用量单独标出；不含需求澄清和候选开发等前期成本。fixture不能进入真实指标统计。它只是独立的单流程证据审计，候选执行谱系已通过源码/请求/上下文/返回决策与控制流程重放核对，相同预算保留任务配对审核仍待接入，不会据此宣称RSI提升或采用策略。

默认research-rounds=0，未达标后返回needs_research。显式启用0..10轮时，Agent重核原始收据，将测得的失败交给LLM提出下一实验，并在剩余会话GPU预算内继续执行。首阶段只支持学习率、权重衰减、训练轮数、batch、输入分辨率和保存频率；检测器、预训练权重、数据与哈希、种子、卡数、源码、验收目标及总预算均冻结。新实验从父实验远端不可变release复用源码，不混入本地后续开发。非法提案保存但不提交；API响应不确定时不自动重复调用。每个提案响应占用一轮，预算耗尽停止。这是首任务的训练方法研究入口，不等于通用harness代码调整或Agent自身效率已提升。不同research-rounds/策略设置属于独立控制记录；建议用campaigns找出ID，再用--campaign-id查询/暂停/恢复。列表是本地最后保存状态，不代表刚刚核查远端进程；实时查询使用training status --run-id。

实验研究策略可通过advance额外参数`--candidate-id CANDIDATE_SHA256 --candidate-module vision_rsi.strategy_NAME`接入动作选择。候选在隔离环境返回动作ID，固定程序重新检查合法性后执行固定Training工具；候选不能调用任意shell或改动验收。这是显式实验策略运行，不表示该策略已通过独立效率评估或被采用。

研究候选入口：`vision-rsi candidate`。它将策略/harness源码改动保存到独立Git仓库，保留原任务契约和证据指纹，不改动当前工作区。创建候选只做语法检查；显式check使用远端CPU隔离执行，均不自动采用，不能作为RSI效果提升证据。

```powershell
# evidence.json为本次研究观察；request-id保持不变可复用已保存的模型响应
.\vision-rsi.cmd candidate propose --session-id SESSION_ID --evidence evidence.json --request-id research-001
.\vision-rsi.cmd candidate list
.\vision-rsi.cmd candidate show --candidate-id CANDIDATE_SHA256
# cases.json为函数关键字参数对象数组；检查结果保存在候选checks目录
.\vision-rsi.cmd candidate check --candidate-id CANDIDATE_SHA256 --module vision_rsi.strategy_NAME --function propose --cases cases.json
.\vision-rsi.cmd candidate strategy-check --candidate-id CANDIDATE_SHA256 --module vision_rsi.strategy_NAME --cases cases.json
```

首次调用前需要提交主仓库已有源码修改。LLM调用先持久化请求，再保存响应；响应不确定时拒绝自动重复请求。候选限制在策略、harness、adapter模块，不能改写验收、调度和预算控制代码。

candidate check在远端bubblewrap隔离命名空间中运行纯Python策略：使用系统Python3.12、只读源码和标准库、不挂载用户目录/密钥/GPU、不联网、清空环境，限制12秒墙钟及每进程5秒CPU/512MiB地址空间，最多32进程。它不安装候选依赖，不支持torch训练；缺少隔离条件直接失败。Git隔离不代表执行隔离，执行检查也不代表效果验收；候选返回的adopt_rule_met等字段都是未经信任的观察，控制程序不会据此采用。真正的同预算保留任务配对效果验收仍待接入。

strategy-check额外执行固定协议检查。每个case包含history、actions和budget；动作包含id、estimated_cost、expected_gain和uncertainty。动作成本须有正数预留，不能选择预算外、不可用或history中已尝试的ID；重试需新的明确尝试ID。策略返回action_id和rationale；无可执行动作时action_id为null。协议通过也不等于策略更有效。

Windows 本地研究控制器，通过 SSH 调度独立 8 卡 H20 服务器；LLM 服务独立且可替换。
项目目标是通用视觉递归自我改进（RSI）研究 Agent，支持逐步扩展到不同视觉任务、数据集和评测协议。COCO 目标检测 box AP 只是第一个验证实验，不定义 Agent 的能力边界。真实路径与早期模拟演示并存；`run`、`compare` 是模拟演示，真实任务使用下文 Training CLI。完整真实 COCO 训练及达标验收仍未完成。

## 本地运行

本地控制器需要 Python 3.10+ 和 Git。Windows 可直接使用 `vision-rsi.cmd`；媒体校验需要 Pillow，COCO 评测需要固定 pycocotools 2.0.11，远端训练另需固定 torch/torchvision。早期模拟演示从仓库根目录执行：

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
不将密钥放入配置、Git 或聊天。OpenAI-compatible HTTP 客户端和独立 Training SSH 执行已接入。首个固定基线为 torchvision Faster R-CNN ResNet50 FPN v2 及其 COCO 预训练权重；原模拟 `run` 入口不执行真实训练。具体数据路径、完整哈希、远端运行时及任务预算须由 Training 准备阶段核查。

## 项目范围

通用核心负责实验规划、候选追踪、预算、调度、恢复、记忆和策略改进。具体视觉任务通过任务适配器提供数据、训练配方、评测指标和错误分析；首个训练适配器用于 COCO 检测。模拟演示中的指标只是占位数据，实际指标必须来自官方评测报告。后续任务无需以 COCO 或 box AP 为前提。

## 研究约束

- 首先锁定检测器、权重校验和、数据版本、训练配方和评测协议，建立可复现基线。
- 内层规划实验、修改候选代码、训练、验证、分析错误；候选代码使用独立 Git 提交记录。
- 外层比较相同 GPU、LLM token 和时间预算下旧策略与新策略的研究效率。
- 调度、成本、恢复和指标计算由确定性程序负责。远端执行须记录真实 GPU 数量乘运行时间。
- 研究反馈使用固定本地验证集；隐藏测试不参与反复搜索。
- 数据集、模型权重、训练输出、SSH 私钥和 API Key 不进入 Git；不配置远端、不推送。

详见 PLAN.md。研究候选保存在独立 Git 仓库，并有受限 CPU 执行检查；通用 harness 自动改进和独立效率验收仍未完成。

## LLM 连通性验证

设置环境变量后执行 `python -m vision_rsi llm-check --config config.local.json`。该命令会发起一次付费真实请求，输出回复和服务端 token 使用量，不输出 Key。该命令只验证模型连通性；自然语言需求整理、方法提案和受限候选代码提案使用各自持久化请求记录，不自动重发结果不确定的请求。`config.local.json` 已被 Git 忽略。

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

## Agent 应用入口（推荐）

在项目目录运行 `.\start-agent.cmd`，随后打开 http://127.0.0.1:8767/ 。也可运行：

```powershell
python -m vision_rsi serve --config config.local.json --run-dir runs/app --port 8767
```

直接在应用中提交任务，后台单工作线程处理持久队列；页面每 2 秒更新状态、事件和已报告 token 用量，详情可展开。支持任务列表、暂停和继续。关闭页面不会停止服务，退出服务会停止后续调度；重启时未结束任务标记 interrupted，不自动重发不确定请求。若有遗留 controller.lock 或 requesting 记录，需先核查，界面会报告失败，不绕过防重复保护。

状态 round_finished 表示当前只读能力范围或规划请求额度耗尽，不代表研究目标完成。当前最多 6 次真实规划，支持检查固定源码摘录、SSH 环境及未验证的模型综合解读。尚不支持训练、任意文件研究、文献检索、代码修改、自我修改验证或长期无人值守。暂停在行动边界生效，不能即时中止正在进行的 API 或 SSH 请求。

任务保存在 runs/app/tasks.sqlite3，每任务的证据库位于对应 ID 子目录。界面只向本地 loopback 地址提供服务，API 使用随机本地令牌并校验 Host/Origin；不支持远程访问、多实例服务或生产级用户认证。启动器从当前进程或 Windows 用户环境变量读取 Key，不写入文件。运行应用需要有效的本地配置和 API Key；提交任务会产生真实 API 用量。

如果 PowerShell 报禁止运行脚本，直接执行 ` .\start-agent.cmd`。该入口不依赖 .ps1 执行权限，不更改执行策略；` .\start-agent.cmd --check` 只检查本地配置与环境变量，不请求 API。已运行时会显示现有应用地址。

## Training / Test CLI（新的核心入口）

```powershell
python -m vision_rsi training --task examples/toy-task.json
python -m vision_rsi capabilities
python -m vision_rsi test --task-id bright-object --input examples/toy-input.json --output runs/prediction.json
```

无需 API 或 SSH 即可验证协议。training 根据已实现的任务类型组装独立 harness，按训练分数选择参数，只对所选参数做一次独立验证；满足要求后注册 validated 能力。test 按任务代号选择最近的 validated 版本，也可指定 `--version`。版本保存在 `runs/capabilities`，包含任务协议、模型、可执行 harness、数据哈希和评测记录；推理前验证 manifest 及产物哈希，未达标/阻塞版本不能调用。模型与训练输出不会提交 Git。

示例使用可执行的单亮色目标检测算法，输入是 JSON 灰度矩阵，输出单个 xywh 框；不是合成评分公式，也不是 COCO 模型，极小验证集不构成泛化能力证据。score 固定为 1.0，不是校准置信度。此旧演示以 JSON 协议输入；自然语言需求使用下文 Training 会话入口。该示例按已实现适配器分派，不代表自动生成新视觉模型或 RSI 效果已验证。

`python -m vision_rsi training --task examples/coco-task.json` 会生成 blocked 记录，不会伪造训练或注册已验收检测能力。COCO 真实适配器已有独立 Training CLI；自动 harness 代码调整和真实 RSI 对照仍待完成。此注册库仅供本地可信产物使用；它不是任意代码沙箱。失败时可查询 capabilities 和 manifest 检查原因。

## Training 任务阶段：接口定义与需求澄清

```powershell
python -m vision_rsi training start --task-id inspection --interactive --config config.local.json
python -m vision_rsi training start --task-id inspection --goal "结合多视角图片和视频定位缺陷" --config config.local.json
python -m vision_rsi training reply --session-id SESSION --message "多图联合处理，视频忽略音频，结果以秒标记时间段" --config config.local.json
python -m vision_rsi training show --session-id SESSION
```

`--requirements requirements.md` 可替代 --goal。每轮调用模型并保存原始用户消息、任务契约版本和 token 用量，结果包含 issues 与 open_questions。交互中 /show 查看，/quit 保存退出；退出后用 reply 继续。当前 Key 从进程环境变量读取（可在同一 PowerShell 设置），不写入会话；请求结果不确定时保留 pending 并拒绝重复请求，需检查后处理或新建会话，尚无不确定请求恢复 UI。

接口在训练前定义：命名输入支持 image、image_list、video、text；声明必填性、多图数量与 joint 语义；视频声明 sampling/temporal/audio。输出使用明确的 JSON schema 子集（type/properties/required/items/description/enum/additionalProperties/minimum/maximum）。每个契约必须提供输入输出示例、验收指标/方向/阈值/协议、预算、假设和待澄清问题。模型草案不等于训练能力。

可不调用 API，直接定义和验证接口：

```powershell
python -m vision_rsi training start --task-id inspection --goal "联合多图和视频缺陷检测" --contract examples/interface-contract.json --offline
python -m vision_rsi training define --session-id SESSION --contract examples/interface-contract.json
python -m vision_rsi training validate --session-id SESSION --sample examples/multimodal-sample.json
python -m vision_rsi training export --session-id SESSION --output runs/task-contract.json
```

会话存于 runs/training-sessions/sessions.sqlite3；define 和每轮模型解析生成新版本，旧版本保留。导出含任务代号、会话、契约版本和内容哈希，供后续 harness 构建使用。validate --result result.json 可验证输出结构。样本校验只验证协议，不读取/解码媒体，不表示模型支持多图或视频。

状态 ready_for_harness 表示当前声明满足协议检查，不等于用户确认语义、真实可实现、已训练或已验收。模型不得自行放宽验收条件，但跨轮语义变更使用已实现的结构差异审核，仍需用户判断语义是否正确。training run --session-id SESSION 会准备任务计划；执行条件完整时部署固定 COCO adapter 并提交 SSH 作业，否则返回 blocked。已接入有限训练配方研究及受限候选策略；通用 harness 代码迭代与独立 RSI 效率验收仍未完成。旧 training --task examples/toy-task.json 接口保留用于早期能力生命周期测试。

## Windows CLI 试用入口

无需系统 Python 或 PowerShell 脚本权限，在项目根目录使用：

```powershell
.\vision-rsi.cmd training start --task-id my-vision-task --interactive
.\vision-rsi.cmd training list
.\vision-rsi.cmd training show --session-id SESSION --interactive
```

启动器优先使用 Codex 自带 Python，CLI 默认从当前进程或 Windows 用户 DEEPSEEK_API_KEY 环境变量读取 Key，不打印值。start 默认读取 config.local.json；其它 provider/环境变量需自行按其配置设置。离线 show/list/define/validate 不要求 API Key。界面应用入口 start-agent.cmd 保持原行为。

交互显示摘要，/show 查看当前状态，/contract 展开完整接口，/quit 保存退出；EOF/Ctrl+C 在输入阶段保留已保存会话。接口仍未定义完整时持续保持 clarifying。

```powershell
.\vision-rsi.cmd training validate --session-id SESSION --manifest examples/multimodal-batch.jsonl
```

JSONL 每行一个联合样本，逐行检查输入协议并拒绝重复 sample_id，单行错误不会中断后续行。这里是 Training 任务接口的批量校验，还不是批量媒体推理；不会读取或解码媒体文件。Test 另有已验收单图检测适配器入口；多图/视频媒体准备与接口检查不等于对应视觉模型已实现。

## 澄清交互修正

任务定义和执行准备分开显示：task_defined 表示目标、输入输出和验收定义已明确，仍可能缺少资源预算或待核查事项；不是已批准训练，也不能绕过 run 的完整性校验。终端不再要求用户填写 goal/schema 等内部字段，只展示已理解需求和关键缺口。模型负责选择技术细节并记录假设。

修复模型返回 {contract: {...}} 时丢失目标的问题：新响应自动解包；旧会话显示时兼容嵌套结构，保留原始数据库记录。解析失败时保留上一版需求，不清空任务。恢复已有终端会话需退出当前旧进程，再用 training show --session-id SESSION --interactive 进入。

## 从 Training 契约生成可执行任务包

```powershell
.\vision-rsi.cmd training build --session-id SESSION --config config.local.json
```

返回 `runs/harnesses/executable-BUNDLE_SHA256`，包含冻结的 Python 运行源码、契约、配置、manifest 和 Windows `run.cmd`，可在仓库外调用。配置仅导出支持的字段，API Key 仍从本地环境读取。任务包绑定原会话和共享账本的绝对路径；复制包不会创建新会话或重置 GPU 预算，原存储和远端资源仍需可用。

```powershell
PATH_TO_HARNESS\run.cmd check
PATH_TO_HARNESS\run.cmd training --action prepare
PATH_TO_HARNESS\run.cmd training --action advance --steps 3
PATH_TO_HARNESS\run.cmd training --action watch --watch-seconds 600
PATH_TO_HARNESS\run.cmd test --version VALIDATED_VERSION --input image.jpg
PATH_TO_HARNESS\run.cmd test --version VALIDATED_VERSION --input-dir images --output-dir predictions --resume
```

跨平台可用 `python harness.py` 代替 run.cmd。Test 必须明确指定已通过实际 serving 验收的版本，并与冻结契约一致；没有达标版本就拒绝预测，不使用占位结果。训练前核查原会话版本及需求，预算或数据缺失返回 blocked。单图和批量使用既有真实 COCO 适配器，联合多图/视频尚无实际模型适配器。任务包不是任意代码执行环境，也不代表 Agent 已能自动修改通用训练源码。

`training build --offline` 保留纯接口包（TASK-vVERSION-HASH）：支持 check、validate-input、validate-output，infer 返回 blocked。构建哈希用于本地完整性检查，不防御能改写整个 manifest 的本机攻击者。可执行包拒绝源文件篡改、额外运行文件和未经验证的字节码缓存。修改原任务需求后需重新构建；共享账本和能力注册不能因重新打包而删除重置。

## 自主联调：真实检测 GPU 路径

```powershell
.\vision-rsi.cmd training diagnose --session-id SESSION --config config.local.json
```

只读检查 COCO 根目录配置，然后通过 SSH 在 GPU 0 运行 torchvision Faster R-CNN ResNet50 FPN v2 的真实前向/反向、一个 SGD step 和推理。模型和图像均随机初始化，使用 64×64 的两个合成输入，不下载权重，不使用 COCO 数据，不计算 AP，不注册已验收能力。单步训练只用于执行链路自测，不能算作任务训练完成。不会使用现有 mock GPU 预算作为真实训练授权。

诊断报告包含运行环境、loss、GPU 区间耗时、显存峰值、模型输出、契约版本、源码哈希与数据缺口，保存在 runs/training-sessions/diagnosis-SESSION.json（最新快照）。SSH 硬超时 120 秒，目前未接持久 GPU 任务管理；不要把此命令用于长期训练。

该适配器是接线基线候选，不是面向 AP60 的最终方法选择。API 参考：https://docs.pytorch.org/vision/0.13/models/generated/torchvision.models.detection.fasterrcnn_resnet50_fpn_v2.html 。COCO 的 80 类使用 1..90 内的离散 ID，输出从 xyxy 转换为 xywh 并过滤背景与无效类别，不能将“80 类”等同为 ID 连续 1..80。

完整 COCO 训练仍缺数据路径、预训练权重、真实执行预算和评测适配器；随机输入 smoke 通过不会解除这些阻塞。

## 批量推理与安装验证

当前能力执行示例仍是 toy 强度矩阵检测，用于验证生命周期，不代表 COCO 效果。先执行上面的 toy training 命令注册能力，再运行：

```powershell
.\vision-rsi.cmd test --task-id bright-object --input-dir examples\batch-inputs --output-dir runs\batch-demo
.\vision-rsi.cmd test --task-id bright-object --input-dir examples\batch-inputs --output-dir runs\batch-demo --resume
```

`--input-dir` 读取目录中的 JSON 输入文件，每个文件是一条独立样本。目录需自行创建并放入符合该能力接口的输入，例如复制 `examples/toy-input.json`。也可使用 `--manifest` 指定 JSONL 文件，每行 `{"sample_id":"one","input":"toy-input.json"}`；input 路径相对于清单。此执行清单与 `training validate --manifest` 的多模态协议样本清单不同；联合多图和视频尚未接入真实推理适配器。

执行固定一个已验收能力版本，逐项保存结果及错误。恢复时校验输入和成功输出哈希，跳过成功项；输入变更或能力版本变化会拒绝混用。可用 `--version` 显式指定原版本。强制终止后若留下 `batch.lock`，确认原进程已退出再移除该锁；正常异常会自动释放锁。尚未提供自动回收孤儿锁。

项目可用 `python -m pip install .` 安装，入口为 `vision-rsi`。基础控制器不安装训练框架；图片解码使用 `[media]`（Pillow 12.3.0），本地 COCO 评测/资源校验使用 `[coco]`（另含 pycocotools 2.0.11）。远端 torch/torchvision 仍需单独配置。

Windows 可在项目根目录创建隔离环境，无需激活 PowerShell 脚本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[coco]"
.\.venv\Scripts\vision-rsi.exe training --help
```

已在新建 Python 3.12.14 虚拟环境实际安装 `[coco]`，从仓库外启动安装后的 CLI，并通过7项 COCO评测和图片格式校验测试。安装解析到 NumPy2.5.3（传递依赖尚未全量锁定）；这证明隔离安装和小样本评测可用，不证明真实任务达标。

当前 0.1.0.dev1 为开发版本。已验证 wheel 构建、隔离目录安装、从仓库外调用模块、40 项自动测试及 toy CLI 批处理恢复；完整上线门槛见 RELEASE.md。

## COCO 官方评测入口

安装可选依赖 `python -m pip install ".[coco]"`，再执行：

```powershell
.\vision-rsi.cmd evaluate-coco --annotations PATH\instances_val2017.json --predictions runs\predictions.json --coverage runs\processed-image-ids.json --annotation-sha256 FROZEN_DATASET_HASH --threshold 60 --output runs\coco-evaluation.json
```

预测遵循 COCO `image_id/category_id/bbox(xywh)/score` 格式；coverage 是推理实际处理完的全部图像 ID 列表，包括零检测的图像。漏跑图像直接拒绝评测。评测固定官方 COCOeval bbox 默认参数，AP 输出按 0..100。冻结标注哈希、5000 张图和 COCO 80 类属于验收必要条件，标注哈希来源仍需独立确认。小型测试数据可验证评测器，但不能通过 COCO 能力验收。当前评测结果尚未连入自动训练与能力注册。

## 预算约束的远端作业

`job-submit --config config.local.json --job-id TASK --job-spec SPEC.json` 现在支持 GPU 规格：

```json
{"argv":["python3","/absolute/path/to/train.py"],"timeout_seconds":3600,"gpu_devices":[0,1,2,3,4,5,6,7],"gpu_hours_budget":8.1}
```

这只是规格示例，不表示已授权或启动训练。GPU 预算必须覆盖卡数×超时，加上 5 秒退出余量；设备索引限定 0..7。CPU 默认不暴露 CUDA，仍限制 300 秒。worker 使用单调时钟控制执行时间，结束时按卡数×实际 worker 时长记账；OS 调度延迟可能产生少量边界误差，并非硬实时计费上限。

Linux flock 租约阻止同一专用工作区内 Agent 作业重复占卡，子进程继承租约文件描述符；这不检查其他工作区或外部程序的 GPU 使用，正式运行前必须重新核查。取消/超时会终止进程组并清理残留子进程。已在真实服务器验证 CPU 正常执行、重复提交、超时、取消和租约冲突/释放，未验证长时间 GPU 任务，Training 提交层已加入同一会话下的预算预留和结算；其他底层 job-submit 调用仍是独立预算，不能绕过 Training 入口用于研究任务。

## 检测训练适配器（开发中）

`training prepare --session-id SESSION --config config.local.json` 将保存的任务契约绑定到首个 COCO baseline 配方，生成不可覆盖的结构化计划；保留原验收阈值，默认选择检测器与优化参数，不要求用户填写架构。该命令只准备计划，不启动训练。`training run` 已接入此计划的 SSH 自动封装与提交；执行条件不完整时明确阻塞。

实际 GPU 训练入口已实现为 `python -m vision_rsi.coco_train --recipe recipe.json --output /absolute/run-dir`，多卡使用 `python -m torch.distributed.run --standalone --nproc-per-node=8 -m vision_rsi.coco_train ...`。恢复需要显式 `--resume`，并保持相同配方、代码、图像内容和世界大小。配方要求绝对数据/权重路径、权重及 train/val 标注 SHA256；支持 epochs、batch_size_per_gpu、seed、checkpoint_steps、world_size、min_size、max_size、learning_rate、weight_decay 和 acceptance_threshold。模型默认 torchvision Faster R-CNN ResNet50 FPN v2，固定 torch 2.6.0+cu124、torchvision 0.21.0+cu124、pycocotools 2.0.11，无隐式下载。

正式运行读取完整 train2017/val2017，保留 80 类稀疏 ID，拒绝缺失图像、路径逃逸、非有限损失/梯度及配方变化。检查点保存模型、优化器、当前 epoch/样本游标、各 rank RNG；训练完成后生成全量预测和覆盖清单，再执行官方评测。SIGTERM 在步边界尝试保存，硬退出只能恢复到最近已保存步骤；已消耗时间由作业层计账。Training 提交层按会话预留跨作业 GPU 总预算，查询终态后结算实际消耗；RSI 调度器仍待接入。

已在 H20 验证单卡与双卡 NCCL/DDP 的小型合成数据训练→检查点→推理→评测，另验证已完成检查点恢复时不重复训练。已补充单卡合成数据中断恢复的8步数值对照；仍未验证8卡完整训练或真实COCO AP。合成 fixture 使用随机初始权重，始终拒绝 COCO 达标验收；正式 Training 计划强制 fixture=false。已接入显式训练验收注册入口；现有fixture未注册为能力。


## Training 作业使用

```powershell
.\vision-rsi.cmd training run --session-id SESSION
.\vision-rsi.cmd training status --session-id SESSION
.\vision-rsi.cmd training logs --session-id SESSION
.\vision-rsi.cmd training cancel --session-id SESSION
.\vision-rsi.cmd training runs --session-id SESSION
```

status/logs/cancel 也可使用 `--run-id` 指定历史作业。prepare/run/status 默认显示摘要，`--json` 输出完整记录。`runs/training-runs` 保存会话预算及作业关联，不能删除后继续同一研究，否则会丢失账本。多个本地账本或不同机器仍不能共享这个预算；上线前需统一权威账本。

运行时检查源文件是否仍匹配计划，将源码、契约和配方封装到远端按内容寻址的 releases 目录，复用前及启动前校验哈希。远端必须已有固定 torch/torchvision 和 pycocotools 2.0.11（可安装在专用工作区 runtime-coco-2.0.11）。提交响应不确定时保留预算，重复 run 返回原运行记录，不自动重启；用 status 核对同一 ID。远端 lost 或提交目录不完整需人工诊断，不会自动释放预算后重跑。

远端 completed 仅表示进程正常退出，不能等同达到效果要求。training collect 已接入 result/evaluation 收据同步和验收检查；真实能力注册入口已接入，当前无真实达标模型；有限配方研究已接入，预算修订与跨阶段统一预算仍待完成。Training resume 已接入，见后文。部署失败且尚未提交作业时结算为零。测试覆盖本地预算预留/结算、重复调用、丢失提交响应、错误目标主机及非法记账；远端验证内容寻址复用、启动前完整性检查和缺配置拒绝。真实 Training CLI 提交仍待数据与预算配置后验证。


## 训练结果收集和验收

```powershell
.\vision-rsi.cmd training collect --session-id SESSION
# 或指定历史运行
.\vision-rsi.cmd training collect --run-id RUN_ID --json
```

collect 先核对原远端作业已正常退出并结算预算，再在服务器上流式计算检查点、预测及覆盖文件哈希，仅将有大小限制的 JSON 报告收据同步到本地，不下载模型权重。收据按内容哈希保存，原计划变化、报告不完整或被修改会拒绝验收。

检查包括：原任务阈值和指标方向、配方及全部源码哈希、图像内容指纹、实际训练步骤、完整覆盖、COCOeval默认协议/版本/分数尺度、标注与模型产物哈希以及指标有限性。仅进程 completed 不代表达标；fixture、子集和低于阈值的结果返回 not_met。通过证据检查只会返回 ready_for_registration，不会直接注册能力：必须先实现并验证该版本的推理适配器。数据来源是否为官方COCO仍需独立确认冻结哈希，哈希本身不建立来源真实性。

已实际收集H20合成训练的JSON报告和远端检查点哈希，确认判定为not_met且不注册能力。测试使用的伪造达标收据仅用于验收逻辑测试，不是任何真实COCO达标证据。


## 中断训练恢复

```powershell
.\vision-rsi.cmd training resume --run-id STOPPED_RUN_ID
# 默认选择会话最近一次运行
.\vision-rsi.cmd training resume --session-id SESSION
```

只允许恢复已确认终止的原作业；lost、活动作业、缺检查点、未知进度和已完成评测都会拒绝。恢复使用原不可变部署及配方，从剩余会话预算内预留新的执行时限，关联原作业和检查点哈希；新运行写入原输出目录，收集结果保留此来源关系。重复恢复请求复用同一尝试，账本事务防止其他活动或提交状态不确定的尝试同时写该目录。所有恢复尝试消耗合并记入原会话。

模型加载前核查检查点哈希，恢复优化器、数据游标和各rank随机状态。开发早期不支持哈希恢复协议的冻结bundle会明确拒绝，不会偷偷替换其代码。硬中断仍只能恢复最近持久化步骤；丢失步骤的算力消耗保留在账本中。

基线启用确定性算法、固定cuBLAS工作区并关闭TF32/非确定性cuDNN选择，torchvision的确定性ROIAlign使用未编译的Python路径以控制编译开销。实现依赖已固定的torch/torchvision版本，可能降低吞吐。仅随机种子不保证复现，参见[PyTorch复现性说明](https://docs.pytorch.org/docs/stable/notes/randomness.html)。在H20单卡合成数据上，真实作业取消后通过Training恢复继续到第8步，与不中断参考的模型参数完全一致（最大差异0），优化器状态也通过比较；这不证明跨硬件、多卡长程或真实COCO效果。


## 注册检测能力与实际图片推理

```powershell
# 仅已完成并达到原任务验收目标的真实训练可注册；sample用于探测实际推理接口
.\vision-rsi.cmd training register --run-id RUN_ID --sample examples\your-input.json
# register返回pending版本；以下命令分段评测实际CPU后端，重复执行可恢复
.\vision-rsi.cmd training serving-evaluate --task-id TASK_ID --version PENDING_VERSION --wall-seconds-budget 3600 --chunk-size 10
# 完整5000张验证且达到原目标后生成validated新版本，再按任务代号调用
.\vision-rsi.cmd test --task-id TASK_ID --input C:\images\photo.jpg --output runs\prediction.json
.\vision-rsi.cmd test --task-id TASK_ID --input-dir C:\images --output-dir runs\image-batch
.\vision-rsi.cmd test --task-id TASK_ID --input-dir C:\images --output-dir runs\image-batch --resume
```

register会重核原计划、收据和验收结果，并以实际本地图像探测远端推理。能力版本固定训练检查点、源码依赖、契约、收据和独立推理适配器；注册过程不保存API Key。未达标/fixture及错误图像或模型身份响应均不能注册。当前没有任何真实COCO达标能力，不能直接执行上述TASK_ID示例；正向注册生命周期测试使用mock收据/传输，仅用于逻辑验证。

COCO适配器目前在SSH服务器使用CPU推理（4线程），最多20MiB图片、40百万像素，进程硬时限60秒。读取本地图片字节后传输，支持相对路径及本地file URI；不能用此入口读取网站或文件共享。联合多图、视频、动画需要对应任务适配器，会明确拒绝。单图任务可直接传图片路径，Agent根据命名输入构造样本；批量目录读取JSON及常见图片文件，样本ID在结果中保留。恢复校验JSON及引用图片内容，换图不能复用旧成功结果。

register只创建pending_serving_validation候选，Test拒绝使用。serving-evaluate复用该候选固定的实际CPU推理适配器，按图保存结果、支持重复调用恢复、使用显式CPU墙钟预算。完整5000张COCO验证、原始验收阈值、数据/模型/适配器身份全部通过后，才生成新的validated版本；fixture或低分不会放行。预算在首次评测冻结，重复调用需保持相同值。性能SLA与真实COCO效果仍待验证。实际H20测试只使用合成检查点，图片字节、源码/检查点身份及输出契约校验通过，预测为空；这不是检测质量证据。


Training 需求理解会在内部对已收到的接口格式错误最多修正一次，保留目标、验收阈值、预算和输入语义；不会因为格式问题要求用户填写 schema。每次实际 API 响应及用量保存到会话 SQLite，版本中记录 response_ids、response_usage 和 format_correction_attempted。网络结果不确定仍停止，不自动重复调用。输出 schema 支持 minItems/maxItems，可验证四坐标边界框。训练数据、保留集和权重不会被默认要求为逐样本推理输入。


需求 API 中断恢复：`training show --session-id SESSION_ID` 会显示待处理请求 ID 和已保存响应数量。原进程退出后，使用 `training recover --session-id SESSION_ID --request-id REQUEST_ID` 从已落盘响应完成接口保存，不调用 API；同一恢复命令可重复执行，不会追加重复版本。若没有收到响应，需显式执行 `training abandon-request --session-id SESSION_ID --request-id REQUEST_ID` 才能解除本地 pending，再自行决定是否发送后续消息。解除不会取消服务端 API，请求结果和费用仍未知，用户原消息及旧契约保留。活跃进程持有会话锁时两种操作均拒绝；恢复要求原请求上下文未变，需求变更仍走接受/拒绝门槛。旧版 pending 请求没有关联标识时不支持自动恢复，不会猜测其响应。自定义存储需同时传入原 `--sessions` 路径。


同预算配对实验入口（首个真实适配器为 COCO）：先为每组 baseline/candidate 建立两个独立、需求完全一致且有授权 GPU 预算的新会话，完成真实数据/权重哈希配置，再按 `examples/paired-study.json` 填入会话和候选 ID。提交当前源码后运行：

```powershell
.\vision-rsi.cmd study create --spec examples/paired-study.json --config config.local.json
.\vision-rsi.cmd study show --study-id STUDY_SHA256
.\vision-rsi.cmd study advance --study-id STUDY_SHA256 --pair 0 --arm baseline --steps 3
.\vision-rsi.cmd study advance --study-id STUDY_SHA256 --pair 0 --arm candidate --steps 3
.\vision-rsi.cmd study compare --study-id STUDY_SHA256
```

`advance` 每次只推进指定组，等待远端运行时重复同一组命令，不自动启动所有组。pair 从0编号；所有预登记组都需执行完成。登记会冻结同组随机种子、相同 GPU 预算、契约版本、候选 Git、控制源码及配置；已跑过实验的会话拒绝登记。执行要求保持登记时的控制源码版本，修改控制代码后旧实验不能混跑。比较会重新审计全部组的原始证据及整个会话成本，拒绝 fixture、缺组、未结算、未完成研究、事后登记、条件不一致和源码变化。其输出仅表示预登记 GPU 预算下的观测 AP 差异；保留任务独立性目前仍是声明，统计复现和多资源预算审核尚待实现，`rsi_efficiency_verified` 和 `agent_adopted` 始终为 false。该入口不会自动采用或覆盖现有 Agent。


候选策略主动停止时，控制器会保存 `policy_stop`（决策、隔离执行报告、耗时、源码和 Git），后续 `advance` 保持停止，不重新选择动作。暂停不算完成；配对比较重放并核对最终计划、运行、分析及研究计数，并拒绝审计期间状态变化。停止不取消已提交作业，也不释放未结算 GPU 预留；仍需按原运行 ID 观察或取消。未记录停止证据的旧版 policy_stopped 状态不能作为完整比较证据。


候选策略上下文 v2 包含历史实验的方法设置、已记录分数/目标差距、已知成本和此前假设；不传密钥、数据/权重路径或原始日志。策略可在 `propose_experiment` 决策中返回 `research_brief`（最多6000字符），影响下一轮假设选择。该建议不能授权修改数据、目标、阈值、检测器、预训练权重或预算；方法规划器重新核对原始收据，实验请求及计划保存建议的身份。`budget` 参数仍表示本次控制步数，不能当作 GPU 小时。中断 intent 的控制源码改变时拒绝继续，需恢复原源码。通用 harness 代码改进及 RSI 效率验收仍未完成。


新的 COCO Training 评测报告自动附带 `error_analysis`：每类官方 AP，以及 IoU=0.5、score≥0.05、每图每类最多100个预测下的 TP/FP/FN。crowd/ignored GT 不计漏检，低于诊断置信度的匹配计入漏检；正式验收仍使用原始 COCO IoU0.50:0.95 box AP。收据审核核对类别覆盖、各类 AP 与总 AP 一致性及计数守恒，再把最多10个低 AP/高 FP 类别和汇总计数传给策略与方法规划器。未匹配预测不能直接断言为背景误检、类别混淆或定位问题。旧报告未包含诊断时保持缺失，不伪造分析。手动评测可用 `evaluate-coco --errors`；合成/子集限制保持原样，诊断不使模型自动达标。


### 联合媒体输入打包

新生成的可执行任务包支持：

```powershell
.\run.cmd prepare-input --input C:\samples\sample.json --output C:\samples\packet.json
```

`sample.json` 必须符合该任务的命名输入契约；相对媒体路径以 JSON 所在目录为基准。单个 sample 可包含联合多图、视频及文本；多图不会被拆成 batch，视频保留原始字节和声明的处理策略。输出包含有序媒体内容、SHA-256、契约与输入指纹。限制：JSON 1 MiB、文本字段 256 KiB、图片 20 MiB、视频 64 MiB、媒体最多 128 个、单样本内容合计 64 MiB。仅支持本地文件；输出不得覆盖已有文件或任务包。

此命令完成传输打包，不解码视频、不执行推理，也不注册能力；联合多图/视频模型适配器仍待实现和验证。现有 COCO Test 仍只接受其单图契约。旧任务包需重新 build 才包含该命令。

接收端可执行 ` .\run.cmd verify-input --input C:\samples\packet.json `，核对包内字节、每个输入的媒体数量与顺序、视频策略、总大小和契约绑定指纹。接收端无需访问发送端文件路径。完整 JSON 包读取上限为 90 MiB。校验成功仅表示传输内容符合该契约；哈希不是身份认证，也不证明模型效果。


### 视频解码执行

新任务包在 build 阶段冻结可支持的视频解码计划，`check` 显示 `video_decoders`。目前支持 `N fps`、`ordered` 或 `preserve timestamps and order`、`audio=ignore`：选择第一张源帧，之后选择与上一张至少相隔 `1/N` 秒的第一张源帧，保留原始 PTS/时间基准；不合成重复帧。未知策略保持 blocked，不在 Test 时猜测。

```powershell
.\run.cmd decode-input --input C:\samples\packet.json --field clip --output C:\samples\frames.json
```

使用配置的 SSH 服务器执行 CPU FFmpeg，要求 Linux bwrap、FFmpeg/ffprobe 及兼容共享库。解码进程没有网络/GPU/宿主凭据，只读一个输入文件，仅私有输出目录可写。默认计划上限为 640×480、64 帧、30 秒；超出拒绝，不能静默缩放或截断。Training 契约可用 `processing.decoder` 明确覆盖：`protocol=source_first_min_interval_v1`、`fps`、`max_frames`、`max_width`、`max_height`、`max_duration_seconds`、`audio=ignore`；所有字段必填，最大原始 RGB 总量 64 MiB。此处限制是已冻结的执行边界，不是任务效果要求。

输出带帧内容哈希、原始时间戳、计划与视频内容绑定；本地再次验证远端返回字节和采样间隔。当前只完成解码，不执行事件理解、联合多图模型或质量验收。

采样与时间戳实现使用 FFmpeg 官方文档中的 [select 与 showinfo](https://www.ffmpeg.org/ffmpeg-filters.html)；实际验证的服务器版本为 4.4.2。解码器依赖版本仍需纳入正式发布环境固定。


### 通用适配器候选的接口检查

```powershell
.\vision-rsi.cmd candidate adapter-check --candidate-id CANDIDATE_SHA256 --module vision_rsi.adapter_candidate --function predict --contract contract.json --cases development-samples.json
```

`development-samples.json` 为 1..16 个符合任务契约的 sample 对象组成的 JSON 数组；隔离候选函数签名为 `predict(sample)`，每个返回值必须符合该契约的 `output_schema`。允许 `adapter_*.py` 或 `harness_*.py` 候选模块，仍执行于已有 CPU/无网络/无 GPU 沙箱。发送前验证输入，返回后由控制端独立校验每个输出；报告绑定候选 Git、契约、验证器源码及原始运行报告。

这是开发样本的接口门槛，不能替代真实模型评测、保留集验收或 RSI 效率证明。通过不注册能力、不采用候选、不改变 Test；候选自行返回的达标声明不被采用。当前沙箱依赖仍为 Python 标准库，未接通训练型通用模型适配器。


### 从接口失败反馈修复候选

```powershell
.\vision-rsi.cmd candidate adapter-repair --report FAILED_CHECK.adapter.json --module vision_rsi.adapter_candidate --function predict --request-id repair-001
```

命令核对原始运行请求、源文件/Git、契约、开发样本及实际失败后，最多调用一次配置的 LLM（输出上限 3000 tokens），生成一个新的完整适配器模块和独立 Git 候选，再用原开发样本与原契约复测。父候选和失败报告保留；报告记录父子关系、LLM 响应哈希及复测路径。这里传入报告必须位于当前候选仓库原始 checks 目录。

同一 request-id 会复用已记录的 API 响应及固定 ID 的复测结果；不确定的 API/远程执行不自动重试。控制源码或反馈变化会拒绝复用旧请求。修复只针对开发接口错误，不自动修正任务要求、不注册 Test 能力、不采用 Agent，也不能替代保留集效果及研究效率验证。

修复复测还会比较原来已符合契约的开发样本输出；若被改掉，返回 `repair_regression_failed`，即使新输出仍能通过 schema 也不算修复通过。报告记录有效旧输出检查数；这不保证未见样本的行为保持不变。


### 修复谱系调用配额

新修复调用需任务契约中明确的 `budget.adapter_repair_calls`（0..10000 的整数）。父子候选共享首次冻结的同一谱系配额；修改预算不会隐式重置。调用前以 SQLite 原子预留，结果不明也占一次，重复请求不重复计数。开发示例中的阶段配额不是正式训练或全项目费用授权。

```powershell
.\vision-rsi.cmd candidate adapter-budget --report FAILED_CHECK.adapter.json --module vision_rsi.adapter_candidate --function predict
```

此命令不调用 API/SSH，可将旧请求记录补记到账本，显示已响应、未结算、账面剩余及预算门槛。历史 `budget.llm_calls` 仅供审计，不能当作新的修复额度；若契约声明了全局 `llm_calls`，在跨阶段消耗未对齐前会拒绝新修复调用。当前阶段账本不覆盖需求澄清、策略研究与 GPU 训练，不能据此声称全 Agent 统一预算已经完成。缺失历史证据会阻止准入，不会当成零消耗。


### 首个基线的公共资源准备

服务器端 `python3 -m vision_rsi.resource_bootstrap --root ABSOLUTE_ASSET_DIR --seconds 240` 可执行一轮有界下载；由 Windows 控制端通过现有持久化 CPU 作业协议调度。固定资源为 torchvision COCO_V1 检测权重、COCO2017 标注及验证图片压缩包；下载后记录完整 SHA-256，断点续传必须匹配 ETag/尺寸/Range。模块不启动训练、不用 GPU、不解压，也不把下载成功作为数据覆盖或模型效果已验收。下载收据和原始数据保存在独立资源目录。

来源：[COCO下载页](https://cocodataset.org/#download)、[PyTorch固定模型权重说明](https://docs.pytorch.org/vision/master/models/generated/torchvision.models.detection.fasterrcnn_resnet50_fpn_v2.html)。官方参考 AP46.7 不等于本项目已复测，更不等于目标 AP60 已达标。训练图片尚未包含在此准备步骤中。

### Resource extraction and readiness

After download receipts report a completed archive, use `python -m vision_rsi.resource_extract --archive ARCHIVE --destination NEW_DIRECTORY --sha256 FULL_SHA256 --max-bytes LIMIT --max-files LIMIT`. Destination must be new; CRC and SHA are checked before publication. Extraction does not certify dataset coverage. The detector dataset check reports `evaluation_ready` separately from `training_ready`; a validation-only dataset cannot authorize training. Pixel decoding and measured COCO AP remain separate verification steps.

### Durable resource preparation CLI

Run `vision-rsi resources --config config.local.json --root /absolute/remote/assets/coco2017 --records runs/resources`. On Windows use `./vision-rsi.cmd` instead of `vision-rsi`. Each invocation submits at most one CPU-only download step (240s download window,270s worker limit). Repeating while queued/running observes the same job. A confirmed completed partial step permits the next attempt; lost/failed/uncertain submission never silently creates another job. Retain the records directory. Download completion does not imply extraction, dataset readiness or model quality.

The current development download is already tracked under `runs/resource-bootstrap/cli-records`; use that directory to observe/continue it rather than creating another record set for the same resources.

For a complete extracted validation dataset, `python -m vision_rsi.resource_verify --root COCO_ROOT` checks all5,000 referenced JPEGs with Pillow, decodes pixels, verifies dimensions and records deterministic image-content and annotation SHA-256 fingerprints. It does not execute a model or compute AP.

### Fixed public baseline evaluation

`vision-rsi baseline-evaluate --root COCO_ROOT --weights PUBLIC_WEIGHT --weights-sha256 SHA --annotation-sha256 SHA --image-manifest-sha256 SHA --output NEW_RECORDS --seconds 240` runs CPU inference of the fixed torchvision Faster R-CNN ResNet50 FPN v2 public weight with800/1333 resizing. Requires pinned torch2.6.0+cu124/torchvision0.21.0+cu124 and the full verified5,000-image validation dataset. Each input/output cache is bound to model/source/data identity and integrity checked on resume. Full COCO AP is computed only after complete coverage; this diagnostic never registers a validated Training capability. External scheduler timeout must bound execution because an individual model call can exceed the soft deadline.

### Official training image preparation

`vision-rsi resources-train --root runs/coco-train-downloads --seconds 240` downloads/resumes the official19.34GB train2017 ZIP locally using pinned HTTPS URL/ETag/size. It reserves disk for the remaining archive plus extraction, uses an OS lease and inherits the download integrity checks. Repeat only after the current invocation finishes. Archive download alone never reports dataset_ready or starts training; extraction, CRC,118,287-image coverage and server transfer remain separate.

For read-only inspection on the execution host, `vision-rsi baseline-audit --root COCO_ROOT --records BASELINE_OUTPUT --identity FROZEN_ID --annotation-sha256 SHA` validates saved cache checksums, exact model/source/input identity and detection categories/scores/box bounds. A partial audit reports its actual coverage and never claims model AP or a validated capability.

### Observe the remote CPU baseline from Windows

`./vision-rsi.cmd baseline-status --job runs/resource-bootstrap/baseline-eval-job-a2.json --audit` queries the frozen job specification and live remote status, verifies the deployed source bundle and audits cached results over SSH. Requires the job record's frozen observation_context; follow the current manifest in `runs/resource-bootstrap/baseline-active.json` when later bounded steps start. This command is read-only and cannot submit/restart jobs. `last_completed_step` may lag the current running job; with `--audit`, saved_prediction_files equals the audited snapshot coverage. Neither count is model AP.

### Bounded CPU baseline continuation

`./vision-rsi.cmd baseline-watch --active runs/resource-bootstrap/baseline-active.json --max-steps 64 --seconds 14400 --poll 30` runs a foreground controller for the frozen baseline. It imports all contiguous previous job records into the64-step cap, verifies terminal receipts and zero-GPU accounting, journals the next handle before submission and observes that same handle after an uncertain submit. Each worker has a300s hard limit. The4-hour foreground deadline is separate from the total step cap; the controller does not start a worker when fewer than305s remain. Deadline/interrupt does not cancel an already running worker. Lost/failed/unknown jobs, changed controls/quota and regressed coverage stop automatic continuation. Full evaluation ends the watcher without registering a capability. Retain its records; this is a CPU baseline stage limit, not unified Agent/GPU/LLM budgeting.

The model client requires a direct HTTPS endpoint without URL userinfo, query or fragment. Automatic HTTP redirects are disabled, so the Authorization header is never copied to another redirect target. A redirect is reported as a suppressed HTTP error; it does not trigger a retry or another model call. Configure the final service Base URL explicitly.

Training submission and checkpoint resume now run a read-only CPU resource preflight before submitting DDP/GPU work. The gate disables visible CUDA devices, verifies the frozen deployed source/recipe/contract and pinned runtime, weights/annotation hashes plus full split coverage. It has a90-second remote alarm and100-second SSH timeout. Failure before GPU submission records zero GPU use and releases the unused reservation; actual GPU submission uncertainty still retains its reservation and stable job ID. Pixel validation during training remains in place; preflight does not prove AP or replace acceptance.

### Full image integrity verification progress

`python -m vision_rsi.resource_verify --root DATASET_ROOT --split train --progress runs/train-image-progress.json` checks all118287 training images; `--split val` checks5000 validation images. The progress path must be new and outside the dataset. It reports coverage checking and every1000 decoded images; only a completed run emits the final pixel/content fingerprint receipt. Partial progress is not resumable validation, dataset readiness, model evaluation or acceptance. Original annotations remain unchanged; zero-area training annotation IDs are recorded.

### Check transferred image bytes against decoded reference

`vision-rsi.cmd resources-equivalence --root DATASET_ROOT --reference FULL_DECODE_RECEIPT.json --reference-sha256 RECEIPT_SHA256` rehashes every image and the annotations, checks full split coverage and compares the exact ordered content fingerprint to a pinned complete CPU pixel-decoding receipt. It rejects changed images/annotations, partial receipts and changed reference bytes. This is read-only and does not load a model or use GPUs. A successful result reports byte_equivalence_verified=true, reference_pixel_decode_verified=true, pixel_decode_verified=false and dataset_ready=false: target bytes match the decoded reference; the target was not decoded again. Use only the original trusted verification receipt, not a candidate claim; the receipt hash pins identity, not authority.

Image integrity verification identifies static JPEG/PNG from decoded content rather than filename suffix: official train2017 includes a PNG named000000320612.jpg. It preserves original bytes and annotations, rejects animation and unsupported formats, and reports actual format counts. A format/dimension failure identifies the image; partial decoding does not yield a complete reference receipt.
