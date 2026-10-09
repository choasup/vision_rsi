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

状态 ready_for_harness 表示当前声明满足协议检查，不等于用户确认语义、真实可实现、已训练或已验收。模型不得自行放宽验收条件，但跨轮语义变更尚需用户检查版本，尚无自动语义差异审核。training run --session-id SESSION 在接口不完整时拒绝执行；完整时明确 blocked，因为通用 harness/训练适配器未接入。旧 training --task examples/toy-task.json 接口保留用于早期能力生命周期测试。

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
