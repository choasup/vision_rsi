# Vision RSI Agent

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
.\vision-rsi.cmd training agent-status --session-id SESSION_ID
.\vision-rsi.cmd training agent-pause --session-id SESSION_ID
.\vision-rsi.cmd training agent-resume --session-id SESSION_ID
```

advance每次最多执行1..10个控制动作，持久化准备计划、提交、查询、收据收集和结果分析；远端仍在运行时返回等待，下次调用恢复同一个作业。动作选择使用控制步数，GPU预算独立由Training调度账本预留/结算，二者不混用。agent-pause只暂停继续决策，已经提交的远端作业仍按原超时/预算运行；需停止作业时使用training cancel。模型未达标时保留分析并返回needs_research，当前不会自动修改方法并无限重训。

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

示例使用可执行的单亮色目标检测算法，输入是 JSON 灰度矩阵，输出单个 xywh 框；不是合成评分公式，也不是 COCO 模型，极小验证集不构成泛化能力证据。score 固定为 1.0，不是校准置信度。任务需求目前以 JSON 协议输入，尚未自动理解自然语言、生成新 harness 或做 RSI；目前按已实现适配器分派。

`python -m vision_rsi training --task examples/coco-task.json` 会生成 blocked 记录，不会伪造训练或注册已验收检测能力。COCO 真实适配器、自动 harness 调整和 RSI 对照仍待实现。此注册库仅供本地可信产物使用；它不是任意代码沙箱。失败时可查询 capabilities 和 manifest 检查原因。

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

状态 ready_for_harness 表示当前声明满足协议检查，不等于用户确认语义、真实可实现、已训练或已验收。模型不得自行放宽验收条件，但跨轮语义变更尚需用户检查版本，尚无自动语义差异审核。training run --session-id SESSION 会准备任务计划；执行条件完整时部署固定 COCO adapter 并提交 SSH 作业，否则返回 blocked。通用方法研究和 RSI 尚未接入。旧 training --task examples/toy-task.json 接口保留用于早期能力生命周期测试。

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

JSONL 每行一个联合样本，逐行检查输入协议并拒绝重复 sample_id，单行错误不会中断后续行。这里是 Training 任务接口的批量校验，还不是批量媒体推理；不会读取或解码媒体文件。测试推理入口暂仍使用旧矩阵示例适配器。

## 澄清交互修正

任务定义和执行准备分开显示：task_defined 表示目标、输入输出和验收定义已明确，仍可能缺少资源预算或待核查事项；不是已批准训练，也不能绕过 run 的完整性校验。终端不再要求用户填写 goal/schema 等内部字段，只展示已理解需求和关键缺口。模型负责选择技术细节并记录假设。

修复模型返回 {contract: {...}} 时丢失目标的问题：新响应自动解包；旧会话显示时兼容嵌套结构，保留原始数据库记录。解析失败时保留上一版需求，不清空任务。恢复已有终端会话需退出当前旧进程，再用 training show --session-id SESSION --interactive 进入。

## 从 Training 契约生成接口 Harness

```powershell
.\vision-rsi.cmd training build --session-id SESSION
```

生成位置为 runs/harnesses/TASK-vVERSION-HASH，内含 contract.json、manifest.json、独立 interface_runtime.py 和 harness.py。不依赖项目包导入即可校验接口示例：

```powershell
python PATH_TO_HARNESS/harness.py check
python PATH_TO_HARNESS/harness.py validate-input --input sample.json
python PATH_TO_HARNESS/harness.py validate-output --input result.json
```

重复构建相同任务/契约版本会验证后复用，不覆盖产物。接口构建允许资源预算尚未确定，但清单保留执行缺口；不代表已允许或已完成训练。infer --input sample.json 在校验协议后返回 blocked（退出码 2），直到真实模型适配器接入。当前没有训练入口或预测能力注册。文件哈希用于本地完整性检查，不提供对恶意修改 manifest 的防篡改保护。

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

项目可用 `python -m pip install .` 安装，入口为 `vision-rsi`。当前 0.1.0.dev1 为开发版本。已验证 wheel 构建、隔离目录安装、从仓库外调用模块、40 项自动测试及 toy CLI 批处理恢复；完整上线门槛见 RELEASE.md。

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

远端 completed 仅表示进程正常退出，不能等同达到效果要求。training collect 已接入 result/evaluation 收据同步和验收检查；真实能力注册入口已接入，当前无真实达标模型；后续研究及预算修订流程仍待实现。Training resume 已接入，见后文。部署失败且尚未提交作业时结算为零。测试覆盖本地预算预留/结算、重复调用、丢失提交响应、错误目标主机及非法记账；远端验证内容寻址复用、启动前完整性检查和缺配置拒绝。真实 Training CLI 提交仍待数据与预算配置后验证。


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
