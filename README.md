# Vision RSI Agent

Windows 本地 CLI，通过 SSH 调度视觉研究任务。核心入口是 `training start`（自然语言定义与澄清）、`training watch`（持续研究控制）和 `test`（按已验收任务版本推理）。COCO 检测是首个真实任务适配器。

当前开发状态：已实现真实 LLM、SSH 作业、固定检测器训练/恢复、官方 COCO 指标计算、结果验收及版本化推理接口；H20 小规模开发验证已执行。官方预训练权重在完整 COCO val2017 的 CPU 基线已测得 box AP46.7097，隔离本地环境复算一致；完整 COCO 训练和 AP≥60 验收尚未完成，没有真实达标 COCO 能力，也尚无通用 RSI 效率提升的独立证据。当前应用只支持可信本地用户，不是公网多用户服务。

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

当前 Training 执行账本只强制结算 `budget.gpu_hours`。任务声明了 LLM、墙钟、CPU 或其它尚未支持的预算字段时，prepare、新训练、恢复和后续方法实验会明确阻断，保留原预算；不会忽略这些限制后执行。共享 LLM 用量观测尚不等于这些总预算已可执行。查询、取消及收集已有作业不因此被禁止。

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

audit区分已结算GPU小时和未释放预留，GPU范围覆盖整个会话，避免只选成功实验而漏掉其他成本；指标只采集该campaign关联的运行，并重核原始收据、计划及任务要求。新动作保存策略选择和每次工具尝试的墙钟耗时，缺失/中断/旧版耗时不能当作零；该时间不是CPU使用量，也不包括等待间隔。LLM计数范围是当前campaign的方法提案，分别显示尝试数、联网前拒绝数、已准入或结果未知数；已知未发送且没有响应的请求不计为未知 token，若状态与响应矛盾则继续标记不完整。使用API保存的usage，缺失或不确定用量单独标出；不含需求澄清和候选开发等前期成本。fixture不能进入真实指标统计。它只是独立的单流程证据审计，候选执行谱系已通过源码/请求/上下文/返回决策与控制流程重放核对，相同预算保留任务配对审核仍待接入，不会据此宣称RSI提升或采用策略。

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
API Key 仅从 DEEPSEEK_API_KEY 环境变量读取，doctor 只报告是否存在，绝不打印值。`vision-rsi.cmd` 启动器可将 Windows 用户环境变量加载到子进程；直接 `python -m` 检查当前进程环境。

`vision-rsi.cmd doctor --config config.local.json` 只做本地配置检查，不创建账本、不调用API或SSH、不开始训练。`configuration_ready` 只表示本地SSH可用及LLM/远端配置格式通过；报告中的 `real_api_tested`、`remote_connectivity_tested`、`task_budget_checked`、`task_effect_verified` 和 `release_verified` 均为本次未验证，历史实测证据仍需另查。真实训练已实现的范围为固定COCO单图适配器及有限配方实验，不代表通用harness调整完成。
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

可在本地配置的 `llm.usage_ledger` 设置共享账本的绝对路径。当前工作区已使用 `F:\vision-rsi-agent\runs\llm-usage.sqlite3`。启用后，同一配置下的需求澄清、方法提案、候选研究与修复会在联网前记录调用，成功后记录服务端 token 用量；超时、中断或用量缺失保留为未知。账本只保存请求哈希、模型、时间及用量，不保存密钥或对话正文。新增独立任务包沿用同一路径。

使用 `vision-rsi.cmd llm-usage --ledger F:\vision-rsi-agent\runs\llm-usage.sqlite3` 只读查看按模型和状态汇总的调用与 token。此为项目级新增调用观测，尚未与会话总预算合并，也未核对服务端账单；历史调用及未启用此配置的旧任务包不在其中，未知用量不能按零计算。该功能不自动授权预算或重发请求。

可选的 `llm.usage_call_limit` 为同一账本设置项目调用次数上限（0..1000000 的整数），额度由你指定。首次使用会固定该上限；暂不支持提高、降低或重置。账本中已有调用、未完成和结果不明的请求都占用次数，所有指向同一账本的客户端共享剩余额度；数据库会在联网前拒绝超额准入，省略配置项也不会移除已绑定上限。`llm-usage` 显示项目上限及剩余次数。它不等于任务级 token、费用、GPU 或墙钟总预算已实现，未使用该账本的旧任务包也不受其约束。额度耗尽后不自动重试。需求澄清会明确区分联网前拒绝与未知 API 结果：前者保存原文，解决准入条件后可主动 reply，无需 abandon-request；新需求未整理前阻止训练和新 harness。也可显式 define 完整需求以替代未发送请求，不会重置额度。格式修正若未发送，会保存已收到的原始草案及错误。研究控制循环的方法提案若在联网前被拒绝，会保存 not_dispatched 并暂停；重复 advance/watch 不重发。解决准入条件后显式 agent-resume 才允许使用新请求 ID 再次尝试，不重置账本额度。已发送但结果未知的请求仍禁止自动重发。策略候选与适配器修复同样保留 not_dispatched，显式新请求 ID 才能重试；已知未发送的修复记录不占用 adapter_repair_calls，重建修复账本也保留该区分。结果未知的修复继续占用额度，不自动重发。当前真实项目未替用户设置此上限。

模型传输由独立 Python 子进程执行，连接、响应头和响应体合计受 60 秒时限约束；超时或中断会结束并回收子进程，子进程自身也有超时退出保护。启动和清理进程、编码及解析时间不计入该传输时限。请求和响应各限 8 MiB，输出 token 参数限 1..32768。不确定响应不自动重发，服务端是否已计费仍需核对；这些上限不替代任务总预算。

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

Windows x64 CPython 3.12 的本地媒体/COCO 依赖另提供 `requirements-control-windows-py312.lock`，固定 Pillow12.3.0、NumPy2.5.3、pycocotools2.0.11 及对应 wheel SHA-256。该清单不适用于其它平台/解释器版本，也不包含远端训练依赖、构建工具和 Agent 包本身。可在创建虚拟环境后使用：

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-control-windows-py312.lock
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe -m vision_rsi training --help
```

已用本地 wheelhouse 和 `--no-index --require-hashes` 在第二个新虚拟环境完成离线安装，`pip check` 及仓库外模块 CLI/8项媒体与COCO测试通过。本机应用控制曾拦截新生成的 console exe（WinError4551）；上述 `python -m vision_rsi` 入口已实测可用。



当前能力执行示例仍是 toy 强度矩阵检测，用于验证生命周期，不代表 COCO 效果。先执行上面的 toy training 命令注册能力，再运行：

```powershell
.\vision-rsi.cmd test --task-id bright-object --input-dir examples\batch-inputs --output-dir runs\batch-demo
.\vision-rsi.cmd test --task-id bright-object --input-dir examples\batch-inputs --output-dir runs\batch-demo --resume
```

`--input-dir` 读取目录中的 JSON 输入文件，每个文件是一条独立样本。目录需自行创建并放入符合该能力接口的输入，例如复制 `examples/toy-input.json`。也可使用 `--manifest` 指定 JSONL 文件，每行 `{"sample_id":"one","input":"toy-input.json"}`；input 路径相对于清单。此执行清单与 `training validate --manifest` 的多模态协议样本清单不同；联合多图和视频尚未接入真实推理适配器。

执行固定一个已验收能力版本，逐项保存结果及错误。恢复时校验输入和成功输出哈希，跳过成功项；输入变更或能力版本变化会拒绝混用。可用 `--version` 显式指定原版本。新版使用操作系统文件锁，强制终止后会自动释放，可直接 `--resume`；带版本标记的 `batch.lock` 会保留，请勿在活跃运行时删除。旧版无标记的锁无法判断是否仍活跃，会明确拒绝；需先确认旧进程已退出，再移除旧锁。实际进程终止/恢复验证使用合成输入，不代表模型效果验收。

项目可用 `python -m pip install .` 安装，入口为 `vision-rsi`。基础控制器不安装训练框架；图片解码使用 `[media]`（Pillow 12.3.0），本地 COCO 评测/资源校验使用 `[coco]`（另含 pycocotools 2.0.11）。远端 torch/torchvision 仍需单独配置。

Windows 可在项目根目录创建隔离环境，无需激活 PowerShell 脚本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[coco]"
.\.venv\Scripts\python.exe -m vision_rsi training --help
```

已在新建 Python 3.12.14 虚拟环境实际安装 `[coco]`，从仓库外启动安装后的 CLI，并通过7项 COCO评测和图片格式校验测试。安装解析到 NumPy2.5.3；这证明隔离安装和小样本评测可用，不证明真实任务达标。

当前 0.1.0.dev2 为开发版本。已验证 wheel 构建、新虚拟环境离线安装、从仓库外调用模块及176项安装包回归；早期toy CLI批处理恢复仅为合成示例。当前版本交付文件和验证证据见 RELEASE.md，完整上线门槛尚未完成。

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

新任务包在 build 阶段冻结可支持的视频解码计划，`check` 显示 `video_decoders`。目前支持 `N fps`（也接受 `Nfps` / `每秒N帧`）、`ordered` 或 `preserve timestamps and order`（也接受 `保留原始时间戳和帧顺序` / `保留时间戳和顺序`）、`audio=ignore`：默认使用 `source_time_grid_v2`：以第一张源帧时间为原点，把时间轴分成 `[k/N,(k+1)/N)` 区间，每个有源帧的区间选择第一帧，保留原始 PTS/时间基准；缺帧区间跳过，不复制或合成帧，因此不保证稀疏源视频的固定输出帧数。旧 `source_first_min_interval_v1` 继续支持，它要求相邻选中帧至少相隔 `1/N` 秒，属于频率上限语义，可能产生更低采样率。未知策略保持 blocked，不在 Test 时猜测。

```powershell
.\run.cmd decode-input --input C:\samples\packet.json --field clip --output C:\samples\frames.json
```

使用配置的 SSH 服务器执行 CPU FFmpeg，要求 Linux bwrap、FFmpeg/ffprobe 及兼容共享库。解码进程没有网络/GPU/宿主凭据，只读一个输入文件，仅私有输出目录可写。默认计划上限为 640×480、64 帧、30 秒；超出拒绝，不能静默缩放或截断。Training 契约可用 `processing.decoder` 明确覆盖：`protocol=source_time_grid_v2`（或显式旧版 `source_first_min_interval_v1`）、`fps`、`max_frames`、`max_width`、`max_height`、`max_duration_seconds`、`audio=ignore`；所有字段必填，最大原始 RGB 总量 64 MiB。此处限制是已冻结的执行边界，不是任务效果要求。

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

## 分段资源解包

大压缩包可使用 `python -m vision_rsi.resource_unpack --archive ARCHIVE --destination NEW_DIRECTORY --sha256 FULL_SHA --seconds 240` 分段执行。每段重新核对压缩包完整哈希并核对已保存文件的哈希，使用独占锁与 SQLite 记录连续进度；重复调用同一参数继续处理。只有全部成员通过 CRC、尺寸与保存哈希检查后才发布目标目录，部分结果在独立 `.unpack` 控制目录中保留。已有目标目录不会被混入，代码或资源身份变化会拒绝恢复。每段有时限，外层调度仍需限制总步数/CPU费用；此工具不启动训练，也不证明数据集或模型质量已验收。

安装版的控制程序不依赖当前工作目录是 Git 仓库。源码版的版本读取固定到程序自己的仓库；wheel 中没有 Git 时，历史字段 `git_revision` 使用 `source-sha256:` 前缀记录控制包 Python/HTML 文件的确定性哈希，不把它冒充 Git 提交。候选代码研究仍需要独立的真实 Git 仓库。

研究流程及方法/策略候选/适配器修复请求会绑定配置中的共享 LLM 账本路径、调用上限和模型执行设置；对同一 campaign 或请求 ID 更换、删除这些配置会拒绝继续执行。指定 campaign 后仍可读取状态和暂停。未记录这些字段的历史流程不据此获得追溯性额度保证；显式新建项目或不同账本之间也没有全账户额度合并。API Key 不写入身份记录。

新建 GPU 训练实验将 Python/平台、torch/torchvision/pycocotools/Pillow/NumPy 版本、PyTorch 构建摘要、CUDA/cuDNN/NCCL、驱动版本、设备类型及确定性设置写入实验身份并纳入 checkpoint 校验。恢复时身份变化即拒绝继续；此指纹不代替依赖安装锁或数值复现验收，也不追溯改写旧实验。指纹采集只在已准入的训练作业内执行，驱动查询限时 10 秒；无法采集不按空环境继续。NCCL 可选版本后缀按 [PyTorch 2.6 源码](https://github.com/pytorch/pytorch/blob/v2.6.0/torch/cuda/nccl.py) 保留。

CPU Test 后端在注册探测时固定运行环境摘要（Python/平台、依赖安装版本及模块构建版本、PyTorch 构建摘要、线程数、确定性与矩阵精度设置）。每个分段评测和后续推理都重新计算并匹配该摘要；评测报告必须携带同一摘要才能晋级。旧的无摘要候选/后端需重新注册并完成完整 serving 验收，不自动继承通过状态。这不保证任意输入效果，也不代替模型 AP 验收。远端 CPU 指纹采集已实测通过，CUDA 未初始化；本机记录位于 `runs/resource-bootstrap/cpu-serving-runtime-live.json`。

维护验证：`tests/serving_fault_probe.py` 为 Linux-only 真实进程故障探针，通过标准输入读取 workspace、serving_source（当前 serving.py 的 base64）及 category_ids。它在独立 fixture 目录验证 SIGKILL 后保留预留、缓存复用和预算不可扩大，不加载模型或计算效果指标。当前远端执行记录见 `runs/resource-bootstrap/serving-crash-probe.json`，详见 RELEASE.md 的验证范围。

研究策略上下文 v3 为运行成本快照增加 run_id、预留是否仍占用、整次运行累计值的口径标记，以及会话授权/剩余 GPU 小时。重复查询、收集、分析中的同一运行耗时不能相加。分析时的余额由完整会话账本计算，包含其他流程和失败运行的已用/未释放成本；数值 budget 参数仍表示控制步数。新决策记录上下文版本，历史 v1/v2 的审计重放保留原语义。此为策略可用证据的改进，尚未证明 RSI 效率提升。

长程策略上下文 v4 在历史超出256行或192KiB时生成确定性有界视图，保留近期状态、实测极值和优先的研究记录；大诊断细节以摘要及省略标记引用原证据。memory_summary 明示总行数、保留/省略数、原上下文哈希及源行索引，计数不是费用。完整控制历史保持原样，所有已尝试行动ID仍由控制器在完整历史上检查；旧v1/v2/v3审计重放不采用新压缩语义。该机制限制策略传输上下文，不代表控制器磁盘历史大小、总运行时长或自主记忆检索已无限扩展。远端隔离策略已用2500条开发历史验证通过，未据此采用候选。


### 查看研究记忆与省略诊断

以下命令只读本地 campaign 状态，不创建会话、不轮询远端、不调用 LLM：

```powershell
.\vision-rsi.cmd training memory --session-id SESSION_ID --campaign-id CAMPAIGN_ID --json
.\vision-rsi.cmd training memory --session-id SESSION_ID --campaign-id CAMPAIGN_ID --source-index N --context-sha256 HASH --history-rows COUNT
```

第一条返回当前 v4 记忆视图、`context_sha256` 和 `history_rows`。第二条用这两个值固定快照，并按零起始的原历史行号取回未截短的策略观察；索引可从 `memory_summary.source_indices` 核对。历史追加后仍可查询原快照；原快照内容改变则拒绝返回。返回的是经过字段筛选的策略观察，不是原始状态文件或任意配置。该 CLI 入口用于人工核查；控制器的受控策略检索见下文。


### 策略主动读取研究记忆

新 Training 控制记录使用 `controller_action_version=2`。当 v4 视图省略或截短历史分析时，控制器在正常生命周期行动之外提供最多8个 `retrieve_memory` 候选，分别指向最多8份分析的下一未读页。实验策略可以选择这些候选；默认确定性控制顺序仍优先正常生命周期行动。

读取按源行索引及完整观察 SHA256 校验，每页最多1024个规范 JSON ASCII 字符，占用一次控制步数。页面可能从 JSON 转义中间断开，以 `offset` 顺序拼接才构成原观察；这是证据文本，不是工具指令。结果写入控制历史，在下一策略上下文的 `memory_page` 中可见；策略也可以继续实验或停止，不要求读完。控制器不提供任意文件路径读取，不能通过该行动调用 LLM 或训练。相同页不再次提供，审计重放会从原分析重算并核对返回内容；旧行动版本重放保持原候选集合。

目前仅支持已记录的分析观察分页；策略何时读取、是否改善研究效率尚未通过同预算真实研究验证。真实远端隔离开发探针已经验证选页、返回页面、下一上下文及下一页协议，不代表候选已采用或模型效果达标。


控制轨迹的版本字段必须是受支持的整数：上下文版本1..4，行动版本1或2；行动版本2要求上下文版本4。缺失字段明确按旧版1处理，未知版本、bool、浮点、字符串及不兼容组合被拒绝。执行/恢复前检查已完成历史、待执行意图和停止记录，发现非法版本时不执行工具、不改写控制状态；仍可show/pause以便调查。审计采用相同规则，不将未来版本猜作当前语义。请恢复正确记录或其对应程序版本，不通过删除版本字段绕过错误。


### 显式真实需求理解开发探针

`python -X utf8 tests/live_requirements_probe.py --live --config config.local.json` 会产生真实API费用，先固定三份独立开发需求及检查项，再使用独立账本最多准入6次调用（包含内部格式修正）；不调用训练。只有显式`--live`才执行，调用结果不确定时不会自动语义重试。原始结果、契约、账本及预登记均写入忽略的`runs/requirements-live/`。这些是需求理解开发案例，不是隐藏视觉测试集、模型效果或研究效率基准。

首轮实际调用5次，单图缺预算及联合多图通过；视频返回中文采样策略，初版严格英文字面检查失败，执行层也不支持该写法。原结果保留为2/3。已修复执行层的确定性中文同义解析，并使用同一原始契约通过解码计划编译与冻结接口包check，无额外API调用。后续探针评分器v2按实际编译语义检查帧率，预登记包含探针源哈希；不将其用于改写首轮结果。


视频计划编译发生在新任务包build时，既有冻结任务包继续使用自己的协议与源代码，不会被本地升级悄悄替换。时间网格由 [FFmpeg select 的源时间变量](https://www.ffmpeg.org/ffmpeg-filters.html#select_002c-aselect) 驱动；接收端独立用原始PTS和时间基准的有理数运算核对时序和网格区间，不把格式化秒数当成精确时间。


### 可选的累计控制工具尝试上限

在本地配置的顶层增加：

```json
{"controller": {"tool_attempt_limit": 1000}}
```

这是每个campaign跨`advance/watch`及进程重启的累计上限，取值为整数0..100000；0禁止开始任何控制工具尝试。配置缺省时不启用。它不应写进任务`budget`，也不授权GPU训练。上限绑定到campaign身份；对选定campaign删除或改变上限会拒绝执行，新campaign有独立计数，不能将它声称为全会话或全项目预算。

每次工具调用前先持久化`started`，再执行；完成、不确定、中断和已确定未发送的尝试都占用一次，恢复重试另占一次。完整历史及待执行意图用于累计，不依赖压缩后的策略视图。达到上限后返回`controller_budget_exhausted`，保留运行ID、原始意图及记录，不取消已经运行的远端作业；`agent-resume`不重置计数。可用`training agent-status --campaign-id ...`查看`controller_tool_budget`，远端作业仍可通过独立`training status/logs/cancel`人工处理。

冻结任务包保留该配置，损坏或缺失的计数证据不会自动补零。该上限只限制控制工具尝试数，不计算策略决策调用、Token、GPU小时、墙钟时长或实际费用；这些统一资源约束仍待完善。


### Windows 训练计划的深路径

训练计划及方法实验的本地计划、响应文件和请求SQLite账本在路径较长时使用 [Windows扩展路径命名](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)。返回的`plan_path`可能以`\\?\`开头，供Python原生文件I/O读回；不修改注册表或系统策略，短路径形式不变。已有冻结任务包不会自动获得此修改，需要重新构建新包。

已在本机通过288字符计划路径的真实CLI准备/读回/跨进程预算探针，以及更深实验目录的SQLite/响应/计划缓存复跑测试。这里没有承诺所有Shell、外部工具、网络共享或全部存储路径均支持长路径；UNC目前只验证命名转换，未访问真实网络共享。

本地故障复验（无需API/SSH/GPU）：`python tests/controller_budget_fault_probe.py`。探针使用独立fixture目录，在工具返回后真实退出进程，验证预算占用与待处理意图跨进程保留；结果保存在忽略提交的`runs/resource-bootstrap/budget-fault-*/evidence.json`。它不执行真实训练，也不代表断电或远端GPU恢复已通过。

最近一次安装复验覆盖当前控制包的累计预算、严格版本审计、研究记忆、中文视频时间网格及Windows深路径修复：新venv离线安装、`pip check`、仓库外3个模块CLI入口及120项相关回归通过。安装解释器位于 `runs/release-budget-video/venv/Scripts/python.exe`；可用 `python -m vision_rsi` 运行。它是本机开发安装包，真实任务质量与完整上线门槛仍见 RELEASE.md。

可重复使用安装验证器（必须用待验证环境的Python）：

```powershell
& .\runs\release-budget-video\venv\Scripts\python.exe -X utf8 .\tests\installed_release_probe.py --output .\runs\installed-recheck --wheel .\runs\release-budget-video\wheelhouse\vision_rsi_agent-0.1.0.dev1-py3-none-any.whl
```

验证器依赖仓库内测试与示例数据，但从仓库外目录导入安装包并核对文件集合/哈希；不能把它视为无需仓库的最终用户验收或新机器测试。

### 自动实验搜索的配方谱系

新的方法实验计划保存`experiment.method_ancestry`，把当前及祖先的冻结训练配方传给下一轮规划。确定性编译会拒绝A→B→A这类返回祖先配方的自动搜索；拒绝结果缓存到原请求，再次读取不重发API。谱系只包含计划配方，不把它当成每个方案都已实际训练或有效的证据。

该约束只覆盖同一计划的已保存谱系。升级前的旧计划缺少更早谱系时，只能从其当前配方开始累积，不声称能恢复未知历史；不同campaign之间尚未全局去重。正式重复实验/统计复现需要单独的显式工作流，当前自动搜索不会替你启动重复训练。

自动方法规划还会接收同一父run/plan/评测receipt的最近最多8条本地编译拒绝反馈（原因最多1000字符、原提案最多6000字符，并附原响应/结果哈希）。这些是编译反馈，不是训练效果测量。反馈快照保存到请求context；恢复同一请求不刷新快照、不因此重发API。不同父实验的拒绝反馈不会混入，规划模型仍须服从冻结任务约束，最终编译器继续独立检查。

真实LLM方法反馈探针可显式运行：`python tests/live_method_feedback_probe.py --live`。每次创建独立fixture/账本，最多一次实际API准入；首次非法提案明确为mock，随后验证真实回答编译与缓存重放。它不启动训练，合成预算不能授权真实GPU作业；不应把单次通过视为真实COCO效果或统计研究效率证明。

新配对研究预登记会保留配置中的共享API账本/调用上限与每campaign工具尝试上限，并把它们绑定到两组执行身份；不会因study配置复制而静默移除。共享API总上限仍不是各组相等的Token或费用预算，当前配对观察不据此自动采用候选策略。

### 配对研究的预登记统计检查

新study固定保存单侧精确符号检验规则：比较每对AP提升是否严格超过预登记的minimum_mean_ap_gain，精确平局排除，至少5个非平局配对，alpha=0.05。p值为Binomial(n,0.5)右尾，具体方法参考[NIST符号检验](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/signtest.htm)。该检验针对超过阈值的方向性概率，不是均值提升的置信区间；平均提升规则单独报告。

仅在所有预登记配对证据完整时计算。旧study未预登记该规则时不事后追加；输出evaluated=false。任务独立性仍未验证，重复候选研究的多重比较尚未控制，Token/费用公平性也未证明；统计标记通过不自动采用候选或宣称RSI效率已验证。

### 从其它目录使用源码启动器

`F:\vision-rsi-agent\vision-rsi.cmd training ...` 和 `test ...` 中显式指定的本地路径（例如`--input`、`--manifest`、`--config`、`--sessions`、`--output`）现在相对于调用目录解析，也支持`--flag=value`。省略这些参数时，源码启动器的默认配置/记录仍位于项目目录。安装版`python -m vision_rsi`保持其原有当前目录语义。其它源码CLI子命令的路径语义本轮未改；JSON文件内URI的解析规则也未改。

批量恢复会先核查整批当前输入指纹和所有已成功缓存的输出哈希，再派发失败/未完成样本。若后面的样本输入或缓存发生变化，本次恢复会在推理之前拒绝，避免先消耗前面样本的重试预算。派发时现有能力后端的expected_input_fingerprint校验仍保留；这不把校验后发生的并发文件修改声称为不可能。

任务包`check`和新训练计划现在输出`training_adapter`，区分接口有效与训练实现兼容。`implementation_supported=true`仅表示契约匹配现有COCO单图检测后端，不代表配置、预算、训练或质量已经通过。联合多图、视频或其它指标仍可定义接口和准备媒体，但当前训练后端返回不支持，不自动转换为COCO任务。旧冻结任务包保持原行为；需要重新build才能包含此字段。

当前最新本机开发安装位于 `runs/release-adapters/venv/Scripts/python.exe`，已离线安装并通过仓库外132项相关回归、3个模块CLI入口和toy训练/批量/恢复链路；对应源码全量338项通过。可使用该解释器的`-m vision_rsi`入口。证据见`runs/release-adapters/installed-evidence.json`及`cli-demo/evidence.json`。toy示例不代表真实视觉训练达标，完整上线门槛仍见RELEASE.md。

### 实际任务的只读本地就绪检查

```powershell
.\vision-rsi.cmd training readiness --session-id SESSION --config config.local.json
```

交互会话内可输入`/readiness`。该命令只读原需求及已有训练账本，不创建缺失账本、不修改预算、不调用LLM/SSH，不启动训练。报告任务接口、适配器兼容性、本地配置、GPU授权及本地剩余快照和未结算运行。`ready_for_prepare`仅表示可以继续准备计划，未检查运行环境、真实任务效果或上线质量；`--json`提供完整结构。

自动方法规划现在也接收controller的v4有界`research_history`，包括先前测量、方法、假设、预算快照和已检索记忆页；它复用外层策略的字段过滤/压缩规则（最多256行、192KiB），不转发任意原始工具结果。完整历史仍在campaign记录中。历史与请求context绑定，缓存恢复时变化会拒绝；这不会自动重发API或证明模型已利用历史提升效果。

COCO checkpoint恢复现在核对epoch/cursor/step与冻结数据集、DistributedSampler补齐规则及每rank批大小的一致性，并要求每个rank的CPU/CUDA RNG字段齐全。不一致进度在加载恢复模型/优化器状态和继续训练前拒绝。该结构检查不是随机状态张量或8卡数值一致性的证明，实际torch状态恢复仍会执行自身校验。

单机COCO多卡训练的全图片内容哈希现在由rank 0计算，再广播给其余rank；读取失败也广播为失败状态，不让其它rank接受空摘要。每个rank仍执行自身数据预检。该路径明确只支持单主机共享数据，不将此优化应用于多节点不同本地数据集。旧checkpoint仍受代码身份保护；新代码不会默默按旧代码身份恢复。

新控制程序的resume会在CPU资源预检中绑定选定checkpoint哈希，使用map_location=cpu/weights_only加载并检查恢复进度，读取前后都核对哈希；回执必须明确checkpoint_progress_checked=true且摘要一致，才能提交GPU作业。固定baseline的CPU检查文件大小上限为2GiB。缺少新进度校验器的旧冻结训练包会被新控制程序拒绝恢复，不自动改写旧代码；旧冻结程序自身的行为不变。CPU检查只证明这些进度条件，不是运行时身份或数值等价验证。

显式远端CPU checkpoint开发探针：`python tests/live_checkpoint_preflight_probe.py --live-remote`。它创建独立且明确标记的1图train/1图val fixture，部署冻结代码，对真实Torch序列化的合成checkpoint验证错误进度拒绝/正确进度通过；CUDA禁用，不启动训练。合成model/optimizer/CUDA RNG字段不代表有效检测器或数值恢复，原失败checkpoint文件保留用于核查。

checkpoint CPU预检进一步检查每rank CPU/CUDA RNG字段必须是非空的一维CPU uint8张量，并实际尝试恢复CPU RNG，随后在finally中还原检查进程原状态。CUDA RNG仅检查张量结构，不在预检里初始化GPU或声称它一定能被CUDA恢复。真实GPU恢复时仍执行CUDA自身状态校验。
# 视频事件评测（独立工具）

使用 `training build` 导出的新可执行任务包也提供冻结验收入口（纯 `--offline` 接口包不包含此模式）：

```powershell
python TASK_PACKAGE/harness.py evaluate-events --ground-truth gt.json --predictions predictions.json --output evaluation.json
```

`check` 的 `evaluation_modes` 会列出任务支持的评测入口。该命令强制读取包内合同，不接受外部合同或阈值覆盖，输出记录 task/version/bundle 身份；输出必须是冻结包目录外的新文件。支持评测仍不表示支持视频模型训练或推理。

自然语言 training 澄清已包含此评测器的协议说明。只在任务语义匹配且用户接受该计分方式时采用，保留明确指定的其它指标；F1效果目标必须来自用户，IoU选择需明确记录。采用精确协议ID后，任务定义阶段即校验 metric/direction、F1范围、IoU阈值及events输出字段。协议可定义不代表视频训练已实现：当前视频训练适配器仍不支持，执行会继续显示阻塞。

在项目目录运行：

```powershell
.\vision-rsi.cmd evaluate-events --ground-truth examples/events-ground-truth.json --predictions examples/events-predictions.json --iou-threshold 0.5 --threshold 0.9 --output runs/events-demo.json
```

示例是合成事件，预期 F1=1，不代表模型效果。输入 JSON 包含 `labels` 词表及 `samples`；每个样本有唯一 `sample_id` 和 `events`，每个事件有 `label`、`start_seconds`、`end_seconds`。两个文件的词表（含顺序）和样本集合必须一致；无预测时保留样本并使用空 events。

固定协议 `vision-rsi/event_micro_f1/v1`：同一样本、同类别、时间 IoU 达标的事件进行最大数量一对一匹配，汇总 TP/FP/FN 后计算 micro-F1（0..1）。不使用置信度或自动过滤；重复预测计入 FP。至少有一个真实标注事件，每份文件最多 10000 样本，每样本最多 1000 事件，超限拒绝而不截断。

输出记录原始文件 SHA256 和 `metric_threshold_met`。这是独立协议的评分工具，尚未接入视频训练适配器或能力注册；不验证标注来源、数据划分或真实模型质量。

可追加 `--contract <任务接口JSON路径>` 绑定验收定义。此时 `acceptance` 必须明确包含 `metric="event_micro_f1"`、`direction="maximize"`、`evaluation_protocol="vision-rsi/event_micro_f1/v1"`、`iou_threshold`（大于0且不超过1）和 `threshold`（0..1）。评测使用合同中的两个阈值，拒绝冲突的命令行覆盖；每个预测样本的 `{ "events": [...] }` 还必须符合合同 `output_schema`。结果保存原始合同 SHA256。这里校验的是评测所需的合同字段，不验证 training 会话是否已接受该版本、视频采样策略或任务预算，也不自动执行训练。
# 实验规划的可追溯记录

用只读命令查看某次决策（STORE 指 campaign 目录下的 experiments，ID 是规划请求代号）：

```powershell
.\vision-rsi.cmd experiment-request --store STORE --request-id ID
.\vision-rsi.cmd experiment-request --store STORE --request-id ID --messages
```

默认显示请求状态、父实验/计划、回执哈希、快照完整性、当时预算和回复哈希；`--messages` 展开原始规划消息与模型回复。`reserved` 表示请求结果仍不确定，命令不会重试或解除预留；`not_dispatched` 表示记录为未发送。旧请求若没有消息快照，会明确标记不可用。命令不创建不存在的账本，不调用模型或远端，也不将回复视为实验效果证明。

新的内层实验规划请求会在调用模型前，将完整 system/user 消息、max_tokens 和当时剩余 GPU 小时快照写入 requests.sqlite3，并记录内容哈希。收到回复后，相应请求目录同时导出 request.json，便于对照模型收到的测量、历史、假设和预算。重放读取原快照并校验哈希，不重新调用模型；旧请求没有快照时不伪造补全。

这是规划器消息记录，不包含 API Key，也不是底层 HTTP 请求、提供商计费证明或实验成功证明。预算快照用于解释决策，实际执行仍以调度器当前剩余额度为准；能同时改写整个本地账本与哈希的操作者不在此完整性检查的防护范围内。
# 新旧 Agent 的成本比较

`study compare` 每个已核验的实验对包含 `resource_comparison`：展示 baseline/candidate 的已结算 GPU 小时、已记录动作耗时及实验规划 Token，并计算 candidate 减 baseline 的差值。任何未结算、未知、非法或不完整值都显示为 null，不按零处理；LLM 成本范围不同也会标记不完整。

AP 比较完整性与成本完整性分别显示：`comparison_complete` 不代表成本可比，请同时查看 `observed_costs_complete` 及缺失证据。这些是观测成本，尚非固定 CPU/总耗时/总 Token/费用预算下的效率证明；需求澄清和候选生成成本不包含在实验规划 Token 中。`equal_resource_budgets_verified` 和 `rsi_efficiency_verified` 仍为 false，不自动采用候选。
# CLI 入口

运行 `vision-rsi.cmd` 或 `vision-rsi.cmd --help` 查看实际任务工作流；安装版使用 `python -m vision_rsi --help`。不带动作的 `training` 显示需求会话和执行命令帮助。顶层帮助明确区分真实 training/test 流程与旧 run/demo/compare 合成演示，具体能力以任务适配器和已注册版本为准。
# 接口包重建与版本

新导出的纯接口包使用 format_version=2 身份，包含 task/session/contract版本、合同哈希及校验运行时代码哈希。相同任务与代码可复用；校验器或入口代码改变后，同一输出根目录的 build 会生成新的包目录，保留旧包。会话不同也不复用同一包。运行时核对manifest与身份一致性；哈希仅提供本地完整性校验，不能防止操作者整体改写包与所有哈希。旧格式包维持原冻结行为。
