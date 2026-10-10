# Vision RSI Agent 实施计划

## 独立成本与指标审计（2026-10-10）

- 新增training audit，Training账本以SQLite只读模式打开并读取一致快照；重核冻结计划、原始训练收据和任务要求，而非读取候选自报分数。
- 会话级成本包含所有运行与未结算预留；不把未关联实验、未知LLM tokens或旧版/中断动作时间当作零。新控制动作记录每次尝试的耗时与失败/完成状态。
- 现有H20合成记录实际审计正确指出fixture、同会话其他实验和旧记录耗时缺失，未给出RSI提升结论。独立配对保留评估及采用机制仍未实现。

## 有期限的持续控制（2026-10-10）

- 新增training watch，固定campaign、刷新最新会话/配置、推进动作并等待远端结果；前台运行、有期限、可Ctrl+C保留状态。
- 同ID只读观察错误有限重试；不重发不确定LLM/提交/恢复动作；观察期限不是作业终态，不取消或释放原GPU预留。停止原因持久化。
- 实际已有H20合成作业导入专用测试控制记录，watch完成远端核查、收据收集及差距分析，原run ID和运行总数均不变；这是历史终态联调，不是实时长程8卡证明。模拟测试覆盖运行等待、超时、丢失worker、API不确定、暂停与中断。

## 控制记录可定位恢复（2026-10-10）

- 新增training campaigns及--campaign-id，恢复冻结策略与研究轮数，避免遗漏参数误读其他记录。
- ID、会话及冻结绑定校验；需求/配置已改变时允许查看或暂停旧控制记录，拒绝拿当前新要求继续执行旧流程。
- 旧版控制记录按ID实际查询成功；列表明确区分保存状态与实时远端状态。106项测试通过，真实长程与方法效果验收仍未完成。

## 失败后的方法实验（2026-10-10）

- training advance支持research-rounds有限提案与下一轮执行；收据重新验收、API请求/响应持久化、非法提案拒绝、会话剩余预算和原目标保持由固定程序检查。
- 首阶段参数化方法实验复用父实验的远端冻结源码；不改变检测器、预训练权重、数据、种子、卡数、验收和总预算。源码/harness研究及外层效率采用机制仍未完成。
- 真实DeepSeek从H20合成实验提出128分辨率/4轮等调整，train-5aa3ffe7794b9f24e2bdf9dc9ed8541d完成并收集官方评测，AP=0，耗用约0.0038 GPU小时；fixture/未达标验收拒绝。改变父源码身份的部署请求也被实际拒绝。
- 修复Windows错误使用本机路径规则验证Linux执行路径的问题，Linux绝对路径可准备计划，Windows/相对/含上级路径的远程配置拒绝。

## 需求变更保护（2026-10-10）

- 多轮模型响应不能直接替换已建立的目标、接口、验收和预算；变更保留为独立草案，原合同及所有版本保留。
- CLI展示差异并支持精确版本接受/拒绝，交互模式提供/accept与/reject，不要求用户编辑schema。计划、harness及Training控制器阻止未处理变更进入新执行。
- mock模型刻意把60降为40并增加预算的测试被拦截；实际CLI演练拒绝草案后保留60。用户原会话AP>=60未改动。首次语义理解和后续自然语言意图正确性仍需独立评估。

## 研究候选版本推进（2026-10-10）

- 已接入真实LLM策略/harness代码提案、请求与响应持久化、独立Git候选提交和源码完整性检查。
- 主工作区不被候选覆盖；验收/预算/调度核心不能由该提案入口改写。
- 已完成DeepSeek Flash真实源码提案与独立Git提交，并在远端bubblewrap隔离环境执行两种子合成研究对照；属于运行联调，不是RSI效果证明。
- 隔离探针实测UID65534，拒绝主目录/系统配置目录读取、源码写入和网络连接，环境中无API Key。运行限时/限资源，不接GPU。
- 候选自报采用判据属于未经信任输出，不会改变Agent当前版本；独立保留任务与同预算配对验收仍待实现。通用策略提案不得固定COCO配方格点或合成评估函数。
- 实际通用策略候选e493463c的公开协议检查发现重复选择完成动作；将原代码及失败报告交给DeepSeek生成a3c0a7c候选，正确模块strategy_history_aware通过同组检查。保留一次调用错误模块的失败记录。此为反馈修正联调，非保留任务效果提升证明。
- 已加入不可由候选改写的动作合法性检查：已尝试ID、预算外/不存在动作、非有限数值和无成本预留均拒绝。仍待接入真实Training研究控制器及独立效果采用门槛。
- 已接入training advance可恢复控制流程，包含计划、稳定ID提交/查询、收据与差距分析；动作意图和源码哈希先保存，重启恢复不改写原计划。新增状态/暂停/恢复控制。
- 实际用户会话分别用确定性策略和远端生成的实验策略推进，均正确保存缺少数据/真实GPU预算的blocked状态；未提交真实COCO训练。完整控制状态转移与断线恢复使用mock工具测试，非真实全流程证明。

目标：构建可跨视觉任务的 RSI 研究 Agent；COCO 检测仅作为首个验证实验。


## 当前主线：长程自主视觉研究（取代早期配方搜索路线）

目标是持续研究视觉问题、积累证据并验证自身研究方法改进的 Agent。固定候选 Demo 仅保留为执行基础设施测试，不代表目标产品。下面早期阶段记录作为历史进展保留。

1. **持久状态与可观测性（已完成最小骨架）**：SQLite 事务事件库、不可覆盖目标、幂等事件、证据引用、行动结果、暂停/恢复意图与只读交互观测台。已导入既有真实 Demo；未实现实时自动采集。
2. **研究行动执行器（下一步）**：围绕研究目标生成行动，支持文献证据收集、仓库检查、实验设计、隔离代码实现、执行与复盘；行动类型扩展至模型结构、方法和工具，不限制于白名单配方。
3. **长程控制循环**：任务分解、持久队列、上下文重建、等待远程任务、失败恢复、GPU/token/时间预算。验证多次进程重启仍能继续同一研究。
4. **自我修改实验**：改进研究策略、记忆与工具；自身代码修改在隔离 Git 候选中进行。冻结旧版本，用独立任务和同预算配对检验；尚未实现自动采用。
5. **COCO 首个真实研究场景**：可复现基线作为校准，逐步验证更开放的方法研究。缺少数据和预算时不伪造训练结果；隐藏测试不参与搜索反馈。

观测台记录的是可审计摘要和证据，不是私有思维过程。自我修改目前只允许 proposed，验证与采用协议待实现。

## 0：独立仓库与模拟闭环（本次）

- [x] 初始化本地 Git，隔离秘密、数据、权重与输出。
- [x] 无依赖 CLI、配置检查、模拟实验、预算准入、原子检查点及版本校验。
- [x] 测试预算边界、恢复幂等性、配置变化与真实模式拒绝。

## 1：首个验证实验——COCO 可复现检测基线

- [ ] 确认 box AP 目标、检测器、预训练权重来源及许可；固定依赖和权重哈希。
- [ ] 确认 SSH 别名、远程路径、COCO 划分、首轮预算和 8 卡运行约束。
- [ ] SSH 任务适配器：固定命令协议、提交/查询/取消、远端持久任务 ID、断线重连、失败恢复。
- [ ] COCO 官方评测工具与真实日志解析；独立验证成功、失败及中断的恢复路径。
- [ ] 复跑基线并记录方差、耗时、显存和真实 GPU 小时；未完成前禁止结构搜索。

## 2：LLM 与内层实验闭环

- [x] 确认官方 deepseek-flash 和 Base URL；实现可替换 OpenAI-compatible 客户端，真实最小调用通过。
- [ ] API key 环境变量、超时、重试、token 成本和预算；先只读规划，再候选代码修改。
- [ ] 候选使用 Git 提交、结构化假设、父实验、配方、资源和评测产物校验和。
- [ ] 候选在隔离目录检查后训练；验证集错误分析；失败候选也记录成本。

## 3：外层递归改进

- [ ] 冻结研究任务、基线策略、随机种子和 GPU/token/时间三种预算。
- [ ] 改进选择策略、记忆检索与工具；新旧 Agent 多次配对对照，比较任务主指标（首个实验为 box AP）、提升/成本和成功率。
- [ ] 独立保留评估，防止外层策略过拟合研究验证反馈；隐藏测试仅用于最终评估。
- [ ] 有对照证据后逐步开放训练配方，再考虑结构搜索。

## 待用户配置

SSH 主机别名、远端工作目录、COCO 与权重路径、准确模型 ID、Base URL、初始 GPU 小时预算。
API Key 在本机设置 DEEPSEEK_API_KEY，无需分享。DeepSeek Flash 最小真实调用已通过；尚未连接远程训练。

## 4：跨视觉任务扩展

- [ ] 抽象任务适配器：数据版本、训练入口、评测协议、指标方向与错误分析。
- [ ] 将 COCO 专用配置和指标放入首个任务适配器。
- [ ] 接入第二个视觉任务，验证通用核心可复用，并检验策略改进的迁移效果。

## 当前执行顺序（2026-10-09）

1. 研究控制层：任务/指标方向、候选去重、基于历史的策略、模拟配对对照。已实现最小骨架；待将其整合进持久实验状态机，加入失败成本、进程互斥与恢复测试。
2. 远程执行层：只读检查 SSH、GPU、Python、磁盘和数据；确认工作目录后实现持久任务提交、状态、日志、取消与断线恢复。验收：控制器重启后不重复启动任务。
3. COCO 基线：选定并冻结检测器、依赖、权重哈希、数据划分及评测协议。验收：基线真实复跑并报告方差、显存、GPU 小时与官方 box AP。
4. LLM 内层：结构化实验假设、允许范围校验、隔离 Git 候选、预检查、训练、评测与记忆。验收：一个成功候选和一个失败候选均能完整追踪；GPU/token/时间预算均有准入与核算。初期只开放配方搜索。
5. 外层 RSI：冻结研究任务与配对种子，在相同预算下比较策略。验收：多种子真实对照与独立保留评估；有证据后才扩大搜索空间。模拟优势不作为 RSI 有效证据。

运行模拟策略对照：`python -m vision_rsi compare --run-dir runs/comparison`。
对照使用固定的 3 个种子，每种策略每种子 4 个模拟 GPU 小时；产物为 comparison.json。
当前对照器是独立 fixture，没有真实训练、LLM 规划或中途恢复；原 run 命令仍保留其恢复验证。

## 远端验证进展（2026-10-09）

- SSH 非交互认证和已信任主机密钥通过；8 张 H20 可访问。
- 按用户授权停止现有 GPU 推理服务及子进程，SIGTERM 正常退出；复查每卡仅约 3 MiB 占用。未删除模型或数据。
- 实测 PyTorch 2.6.0+cu124、torchvision 0.21.0+cu124、CUDA 12.4，8 卡逐卡 256×256 矩阵运算均通过。尚未验证 NCCL 多卡通信。
- pycocotools 未安装；COCO 路径与首轮训练预算待确认，未启动检测训练。
- 根文件系统剩余约 9 GB；数据挂载盘有空间，后续环境和输出应置于专用项目目录。
- remote-check 已实现并实测；持久任务提交、取消、预算核算仍待实现。

## 持久任务进展（2026-10-09）

- [x] 专用远端目录中的任务 ID、不可覆盖规格、重复提交去重、脱离 SSH 的 worker。
- [x] 查询、限量日志读取、取消、硬超时和进程身份检测。
- [x] 真实服务器验证 completed、failed（退出码 7）、timed_out 和 cancelled；不同本地控制器进程恢复查询成功。
- [x] 单元测试覆盖规格冲突、重复启动防护、不完整提交和 PID 复用。
- [ ] GPU 资源准入、真实 GPU 小时核算、总预算与队列互斥。
- [ ] 训练产物校验/拉取、服务器重启后的人工恢复协议、孤儿进程清理与日志总量限制。
- [ ] 将持久执行器整合进研究实验状态机；确认 COCO 路径和预算后接入真实基线。

本次远端仅执行短时 CPU 测试，没有训练、COCO 评测或额外 LLM 请求。

## 端到端 Demo

- [x] DeepSeek 读取实验历史并输出结构化候选，确定性白名单校验。
- [x] 真实 SSH 持久任务执行合成实验，回收日志并校验结果。
- [x] 3 个实验的检查点、完成结果恢复、最多 2 次 LLM 请求和 HTML 研究报告。
- [x] 单元测试覆盖非法候选、完成后不重复请求及远端结果尚未回收时的恢复。
- [ ] 真实训练、候选代码变更、GPU/token/时间总预算、外层策略迭代与独立评估仍未完成。

## 只读行动执行器进展

- [x] 目标与持久历史驱动的模型规划、结构化工具/引用校验。
- [x] 仓库源码检查、真实 SSH 环境检查、带不确定性标记的解释行动。
- [x] 请求预留与响应记录、空响应拒绝、已保存规划恢复、暂停检查、成功工具去重。
- [x] 工具结果自动写入研究事件库并重建观测台，真实运行通过。
- [ ] 文献检索、隔离代码变更、实验实现、远端训练与长程自动调度。
- [ ] 基于任务状态的工具重访、上下文检索/压缩、总预算与即时暂停协调。

结构化规划的 DeepSeek thinking 参数依据官方文档：https://api-docs.deepseek.com/guides/thinking_mode/ 。此次真实规划发生过空响应和重复总结，历史记录保留；之后补充了拒绝记录和工具去重约束。

## 可执行任务工作台

- [x] 浏览器直接提交目标，持久任务队列与单后台工作线程。
- [x] 任务列表、实时轮询事件、详情与 token 用量、暂停/继续。
- [x] 重启时将不确定运行任务标记 interrupted，保留研究记录，不盲目重发请求。
- [x] 从真实 UI 提交任务并完成仓库、远端只读检查；23 项测试通过。
- [ ] 完整研究输出、任务内追问与目标修订、隔离代码执行、训练及真正的长期自主调度。

当前为可运行的 Agent 应用雏形；任务可执行范围在首页明确展示，不承诺完成任意视觉研究任务。

## Training/Test 能力生命周期（当前核心方向）

- [x] JSON 任务协议、Training/Test/capabilities CLI 和持久版本注册库。
- [x] 按已实现任务适配器组装可执行 harness，记录训练选择、独立验证、输入输出协议与产物哈希。
- [x] Test 仅加载已验收版本，验证产物完整性；COCO 未实现时明确 blocked。
- [x] 本地单亮色目标检测样例完整运行，不依赖 API/SSH，用于能力生命周期验收。
- [ ] 自然语言需求理解、自动生成/调整 harness、通用视觉训练适配器。
- [ ] 未达标原因诊断、模型/方法迭代和 Agent 自身 RSI 对照验证。

本阶段示例是基础算法参数拟合，不是已实现 RSI，不意味着 COCO 能力可用。

## Training 任务阶段接口定义

- [x] start/reply/show/define/validate/export/run CLI；自然语言 Goal 与多轮交互会话。
- [x] 保存原始用户消息、不可覆盖的契约历史版本、模型 token 用量与待澄清问题。
- [x] 单图、联合多图、视频、文本字段协议；输出 schema 子集、示例、验收和预算检查。
- [x] 样本/输出协议校验与带内容哈希的契约导出；未完整定义接口时不进入 run。
- [x] 真实 DeepSeek 解析多图视频需求，缺少阈值和预算时保持 clarifying（1177 tokens）；27 项测试通过。
- [ ] 语义差异/验收条件变更审核、自动 harness 生成、媒体解码、训练执行与 RSI。

当前训练任务阶段可以产出接口定义；training run 不会伪造训练，返回缺少适配器的 blocked 状态。

## CLI 试用可用性

- [x] vision-rsi.cmd 命令入口，绕过对系统 Python 和 .ps1 执行权限的依赖。
- [x] Training 会话列表与交互恢复、摘要视图、完整契约查看、退出保留记录。
- [x] JSONL 批量样本协议校验、重复 ID 检查、逐行错误报告。
- [x] 真实启动器验证交互恢复和批量校验；29 项测试通过。本次未额外调用 LLM 或远程训练。

## 用户试用回归修复

修复模型嵌套 contract 导致误报缺少 goal；保留原始会话并兼容恢复。任务已定义与执行条件分离，需求摘要只显示关键补充项，解析失败不丢失旧契约。使用实际用户会话验证 AP≥60 的目标和图像输入得到恢复；31 项测试通过。

## 契约绑定接口 Harness

新增 training build，按任务代号、契约版本与内容哈希生成独立输入/输出校验程序；现有用户 COCO 会话生成并 check 成功。重复构建复用，文件变更拒绝覆盖。未接模型时 infer 明确 blocked，未注册已验收能力。32 项测试通过。下一步仍是真实检测训练/推理适配器及训练执行预算接入。

## 真实检测器自主联调

- 新增 detector 适配器与 training diagnose：远端真实 GPU 前向/反向/一次更新/推理。
- 首次 CUDA peak memory reset 在初始化前失败，调整初始化顺序后实测通过。
- H20 smoke 实测约 1.29 秒 GPU 区间、峰值约 520 MB；使用随机图像与随机权重，不是 COCO 训练/评测。
- 现有用户会话新增契约 v4，修正 COCO 离散类别 ID，AP>=60 要求不变，保留旧版本。
- 34 项测试通过。COCO 数据路径、真实训练预算、预训练权重和完整评测/训练适配器仍待接入。

## 训练执行层进展（2026-10-09）

- 新增 pinned torchvision COCO adapter：真实图片/标注读取、1..8 rank DDP、步骤检查点、优化器与各rank RNG恢复、全量推理和官方评测。
- 在H20验证单卡及双卡合成fixture完整执行；单卡已完成检查点恢复不重复步骤。fixture非COCO效果证据，验收状态始终false。
- 真实任务新增 training prepare：保存契约/配方/源代码哈希、保留AP>=60并区分真实GPU预算与mock预算。
- 仍待：Training run自动部署/提交、跨候选总预算、真实数据/预训练权重、训练中断数值验证、8卡长程、能力注册、方法研究及自身RSI。


## Training 提交层进展（2026-10-09）

- 已接通 training run/状态/日志/取消/运行列表，SQLite保存任务、版本、远端和作业ID关联。
- 会话级预算事务预留与终态结算；SSH提交响应丢失后保持原ID与预算，重复命令不重复启动。
- 内容寻址远端源码/契约/配方封装，部署复用及启动前哈希验证已实测；缺配置预检查拒绝。
- 仍待结果同步与能力验收注册、Training resume、预算修订/跨机器统一账本、RSI研究循环和真实COCO效果验证。


## 结果收据与验收进展（2026-10-10）

- 新增 training collect：终态核对、预算结算、远端大文件流式哈希、受限JSON收据同步、不可覆盖保存及效果验收。
- 对比原任务阈值、配方/源码/图像指纹、标注、检查点、预测、覆盖及官方评测协议；拒绝缺失/变更/非法指标和fixture冒充用户能力。
- 实际H20合成实验收据已收集并正确判为not_met，没有注册真实COCO能力。
- 仍待真实推理适配器及能力注册、Training resume、研究方法/Agent自改进、完整真实数据和独立效果验证。


## Training 恢复验证（2026-10-10）

- 已接通 training resume：终态核对、检查点哈希、固定旧部署、预算余额、尝试谱系及共享输出互斥，收据保留原输出来源。
- 实际作业在持久化步骤后取消，再通过Training提交层恢复；与同环境连续训练8步比较，模型参数逐项完全一致（最大差异0），优化器状态一致。
- 初次对照发现仅固定种子仍有明显差异；启用确定性算法/ROIAlign路径并提前恢复RNG后重新对照通过，未将失败结果算作通过。
- 证据范围仅H20单卡小型合成数据；8卡长程、真实COCO、真实推理注册及方法研究/Agent RSI仍未完成。


## 实际图片推理与注册入口（2026-10-10）

- 新增固定检查点COCO CPU推理适配器、真实本地图片传输、命名契约绑定、输出与图像/模型身份校验和进程时限。
- 注册入口重核真实Training验收门槛并探测实际样本；Test可按任务代号执行已注册版本。现有fixture经CLI正确拒绝，真实注册数仍为0。
- 支持直接图片路径和图片目录批量；批量恢复指纹包含JSON引用的图片字节，保留样本ID，拒绝换图后复用旧结果。
- H20服务器CPU实测合成检查点图片推理通过，预测为空，不是质量证据；正向注册仅mock逻辑测试。CPU后端完整AP/性能待验证，登记serving_accuracy_verified=false，不能视为上线完成。
- 下一主线仍是通用研究/方法与Agent自身RSI，不把固定COCO adapter视为最终Agent能力边界；联合多图/视频适配器也未完成。


## Policy trace audit (2026-10-10)

- Added read-only replay of controller phases and baseline/candidate decisions. Candidate evidence binds Git source, module, protocol source, history, available actions, request digest and returned decision to executed actions.
- Missing or mismatched decision counts fail protocol validation. Legacy incomplete traces remain unverified.
- This establishes trace consistency only. Equal-budget held-out paired evaluation, policy adoption and real COCO acceptance remain pending.


## Natural-language interface validation (2026-10-10)

- Real DeepSeek Flash probes reproduced array-root detection schemas, boolean video audio policies, dictionary assumptions, and evaluation resources incorrectly added to inference inputs. Failures retained under ignored runs/semantic-live-check.
- Added bounded one-pass formatting correction, durable raw-response records and per-response usage, task/acceptance/budget/input preservation checks, explicit training-resource versus inference-input scope and adapter defaults. Added array length validation and checked all sparse COCO IDs before planning.
- Final three development regression probes passed input shape, original threshold and missing-budget preservation; COCO schema also passed adapter compatibility. These are visible development cases, not held-out semantic or RSI quality evidence. No real training was started.


## Clarification crash recovery (2026-10-10)

- Added per-request context and response association plus OS-held session locks across clarification and resolution. Received responses and request IDs are committed together.
- CLI recover applies received responses without API calls, checks the original context, preserves change review, and is idempotent. Explicit abandon-request preserves user turns and known contracts; unknown remote outcome/cost remains visible, never zeroed.
- Actual child process forced exit after response persistence followed by a new CLI process recovered the contract using a nonexistent API config, proving recovery does not depend on API access. Added live-lock, context tamper, no-response and duplicate-resolution tests.
- Legacy pending requests lack response association and remain unrecoverable automatically. No claims about remote API cancellation or billing reconciliation.


## Preregistered paired execution (2026-10-10)

- Added study create/show/advance/compare CLI, fresh independent sessions, equal task/GPU budget constraints, fixed per-pair seed, immutable candidate/control/config identity and preregistration time checks.
- Actual execution delegates only to existing bounded durable campaign tools. Comparison requires every arm to finish research, settle accounting and pass independent real-measurement audit; all measurements must share frozen data, weights, seed, code and runtime within each pair.
- Unit tests exercise execution binding and reject unequal budgets, reused sessions, prior execution, missing groups, manifest tampering and different data. Positive comparison logic uses explicitly fabricated metadata and is not real RSI evidence.
- Actual real-data paired experiment, independent held-out selection verification, statistical replication, joint multi-resource budgets and candidate adoption remain incomplete.


## Terminal policy decisions and study consistency (2026-10-10)

- Persist terminal no-action decisions with candidate evidence, selection timing and source identity. Repeated advance respects the recorded stop instead of restarting policy selection.
- Policy audit now verifies terminal decisions and checks final plan/run/analysis/research state against a full action replay; changing only final state cannot bypass remaining research.
- Paused campaigns cannot count as completed study arms. Comparison also checks that the independently audited state hash matches the phase-checked snapshot, rejecting concurrent state changes.

- Actual remote CPU isolation probe at control revision f54e0fe: explicit-stop candidate ced30cf8dd290d0cf6afa69d2b30dd594c869307dc502ea8c765c882826ccbbe produced a durable terminal decision. Second advance reused it, no tools ran, no Training run or GPU reservation was created. Independent audit verified one decision and correctly refused real measurement/RSI claims. Ignored evidence: runs/policy-stop-integration/{first,second,audit,summary}.json and cli-audit.txt. No LLM call or GPU training was performed.


## Evidence-aware strategy research direction (2026-10-10)

- Corrected a core limitation: candidate policies previously saw IDs/status only and could influence scheduling but not the next hypothesis. Context v2 now exposes bounded method settings, reported scores/gaps, known costs and prior hypotheses without paths/credentials. Replay reconstructs the exact versioned context; legacy v1 remains explicit.
- Strategies may attach a bounded research_brief only to propose_experiment. The method planner considers it as an untrusted hypothesis, rechecks original receipts and preserves frozen data/model/threshold/budget constraints. Request identity and resulting plan bind the brief; changing it cannot reuse an old response.
- Pending controller intents cannot silently execute after control-source changes. Resume requires the original source snapshot.
- This enables strategy influence over the existing first-task method planner; general harness/code modifications, actual equal-budget efficiency and automatic adoption remain pending.

- Actual integration at source 598a99f: independently re-reviewed historical H20 fixture receipt (AP=0, unchanged target60), assembled an explicitly diagnostic observation context, executed task-neutral candidate ecedb92baaf3a4069ea517d663b0000a1c31fac602fcb1a5fa8c6ee16e9a987a in remote CPU isolation, then made one real DeepSeek planning call with the returned research_brief. New plan bound its digest, preserved original contract/source and fixture=true. No GPU job submitted, no adoption. Ignored evidence: runs/evidence-strategy-integration/{context,runtime-check,plan-result,summary}.json. Diagnostic imported history is not a live campaign or paired research-efficiency proof.


## Executable task harness export (2026-10-10)

- Configured training build now exports a frozen Python runtime, contract and sanitized configuration with Windows run.cmd. Commands expose the existing Training controller and pinned validated-version Test including batches; offline build retains interface-only behavior.
- Export retains original session and shared absolute ledger/registry paths, preventing automatic budget/session reset on copying. Training checks current original requirements; explicit run IDs must belong to the bound session. Test checks validated version and exact frozen contract.
- Standalone subprocess tests outside Git cover check/blocked real preparation, original session/budget preservation, no credential export, changed requirements, unvalidated Test rejection, source tampering and unverified bytecode. No real model quality inferred from these checks.
- Generic harness code research/adoption and real COCO quality remain incomplete. Exported controls still require shared stores, configured remote resources and original Python-compatible dependencies.

- Actual Windows cmd.exe launcher tested from a temporary directory outside the repository using original task session df8e8f8991ee496d859e35fab2085d8f. Bundle d6b06dc5619f3642ba14d262e0e4f41584cf5610f49a4bf5786183e6679a6377 at source45bb32f passed controls check; prepare correctly blocked on original missing execution inputs. Original session was byte-equivalent in returned structure and AP60 unchanged; no GPU job/API call. Ignored evidence: runs/executable-harness-integration/{artifact,check,prepare,summary}.json. Legacy optional clarification questions remain in the old contract and were not silently rewritten.


## Measured COCO error observations (2026-10-10)

- New Training evaluation reports derive per-class AP and diagnostic TP/FP/FN from the same official COCOeval accumulator. Explicit IoU0.5 / confidence0.05 / max100-per-image-per-category diagnostic scope does not replace acceptance. Crowd and low-confidence matching cases tested.
- Independent receipt review validates category coverage, class AP versus overall AP and count conservation. Bounded summaries enter strategy observations and method-planner evidence; absent legacy diagnostics remain unknown. No causal error classification inferred from unmatched detections.
- Fetched only hash-verified bounded historical H20 fixture annotation/prediction/coverage artifacts, recomputed on local official pycocotools: AP remained0, TP0/FP0/FN2/GT2,80 category coverage, acceptance false. No GPU or API call. Evidence under ignored runs/error-analysis-integration/{evaluation,summary}.json. This is fixture integration, not real COCO quality.


## Log observation liveness (2026-10-10)

- Log observations now reconcile authoritative status for the same remote job and project it into campaign state. Completed jobs can proceed to collection even when the strategy selected logs. Terminal GPU accounting uses status evidence; failed reconciliation retains reservations.
- Regression coverage includes misleading log text and unavailable status. Real COCO data/weights and authorized GPU budget remain outstanding; bounded resource discovery found no matches before its 10,000-directory limit and does not establish absence.


## Long strategy context admission (2026-10-10)

- Control and remote candidate runtime now use the same finite-JSON cases encoder, 1..16-case bound and 1 MiB aggregate payload limit. This accommodates an individual 512 KiB strategy context while rejecting oversized aggregate cases before reserving evidence or contacting SSH. Other CPU, memory, wall time and output limits are unchanged.
- Actual H20 CPU namespace check with 2,500 history rows / 401,615 serialized bytes passed strategy protocol. Candidate remained unadopted; no GPU training or LLM call. Ignored evidence: runs/long-context-integration/summary.json and its referenced protocol receipt. This does not establish unbounded history support or RSI efficiency.


## Remote log reconciliation recovery evidence (2026-10-10)

- Queried actual H20 logs/status for historical fixture job train-5aa3ffe7794b9f24e2bdf9dc9ed8541d: completed, 4,326 log bytes, unchanged settled cost 0.0037871319739820643 GPU hours; projected next action is collect. No new job or API call.
- Copied the historical SQLite ledger via backup and simulated an unobserved submitted state only in the copied ledger. Injected a lost status response after actual SSH log retrieval: reservation stayed unsettled; subsequent actual logs/status observation recovered the same run ID and original settled cost without submission. This is explicit fault injection against a completed fixture, not a real mid-training outage. Ignored evidence: runs/log-observation-integration/{summary,fault-summary}.json.
- Remaining release gates are unchanged: full real COCO resources/budget/quality, general harness code improvement, paired held-out RSI verification, joint media adapters and broader long-run deployment validation.


## Contract-bound joint media transport (2026-10-10)

- Executable harness prepare-input packages one validated sample with named images, ordered joint image lists, video bytes/declared processing policy, and text. Content SHA-256 and contract/sample fingerprint bind bytes and semantics; local-only reads, per-file/aggregate/asset-count bounds, no output overwrite or writes into frozen package.
- Standalone subprocess verification outside the source repository covers joint grouping, exported CLI packaging and overwrite rejection. Transport tests cover byte preservation, changed media/policy fingerprints, missing/network/empty/oversized media. Fixture bytes are explicitly not decoded or inferred; actual joint/video adapters and quality remain incomplete.


## Joint media receiver integrity (2026-10-10)

- Shared verifier checks embedded strict base64 bytes against exact declared size/SHA-256, per-field count/order/type, video processing against frozen contract, aggregate limits and contract-bound input fingerprint. No sender path reopened and no decoding/inference claims accepted. JSON object field order is immaterial; joint image list order remains material.
- New exported verify-input CLI enforces a 90 MiB serialized packet read bound. Packaging self-verifies before writing. Standalone CLI tests reject modified hashes; transport tests reject reordered/missing media, content/policy/text/fingerprint changes and false execution flags; original packet remains verifiable after source media deletion. No media model quality claim.


## Isolated video decoding execution (2026-10-10)

- Training harness build freezes supported numeric-fps/source-order/audio-ignore sampling and explicit decoder bounds; unknown semantics remain blocked. Exported decode-input consumes a verified packet and frozen named video plan, SSH CPU decode only. No silent frame truncation or resizing.
- FFmpeg/ffprobe execute under bwrap uid65534, no network/GPU/home/proc/host etc, read-only tool/shared-library mounts plus one input and private writable output. Ubuntu BLAS/LAPACK alternatives receive only two resolved library files. Tool CPU/address-space/file/process limits and probe/decode deadlines enforced.
- Actual H20 FFmpeg4.4.2 synthetic 64x48 / 4fps / 1.5s MP4 decoded under this isolation at2fps to source PTS seconds[0,0.5,1],27,687 RGB PPM bytes. Repeated frame hashes identical; max_frames=1 rejected instead of truncating. Ignored evidence runs/video-decode-integration/evidence.json. This verifies decoding, not event understanding or task quality.
- Receiver independently checks returned frame RGB headers/dimensions/bytes/SHA, exact rational timestamps, interval/count/aggregate limits and input/plan identity. Pure regression tests cover unsupported policy, altered fps, malformed plans/timestamps and response tampering. Joint/video model adaptation and acceptance still incomplete.

- Actual Windows run.cmd from an external temporary cwd passed frozen harness check → joint two-image/video prepare-input → verify-input → SSH decode-input → independent RGB/timestamp verification. Two decoded runs had identical frame hashes; one-frame cap rejected. Fixture session 2a4f92a664da4720a100c0fd62828b3a, bundle 955a25253913b090f9347837ed05a9e52f7f5e7d64a672d6b40b8722cf3650c1 at source3671894; no original user task changes, GPU training or LLM calls. Evidence: runs/video-cli-integration/latest.json and referenced summary/frames.
- Initial direct-driver test receipt was invalidated because its in-process test later mutated the shared request plan; validate_plan/compile now return copied scalar plans, with regression coverage. Initial receipt retained as initial-aliasing-receipt-invalidated.json; current video-decode-integration/evidence.json references the fresh CLI receipt, which passed independent response verification.


## Independent video response bounds (2026-10-10)

- Receiver now requires a positive finite container duration within the frozen plan, fixed frame dimensions, integer sequence/byte accounting, and source PTS span consistent with container duration. Span uses exact rational PTS rather than subtraction of rounded float seconds, including large timestamp-offset regressions.
- Targeted decoder tests reject missing/boolean/nonfinite/oversized duration, a self-consistent hash-valid frame with changed dimensions, timestamp span beyond container duration and float cancellation at large offsets. Previously actual H20 CLI receipt independently rechecked: duration1.5s,3 frames,source span1s; no new remote call/training/API. Evidence runs/video-decode-integration/receiver-duration-review.json.


## Adapter candidate development contract gate (2026-10-10)

- candidate adapter-check executes isolated adapter/harness functions on 1..16 validated development samples and independently checks each result against the frozen task output schema. Invalid interfaces/inputs fail before runtime. Contract/result-count/per-sample errors, candidate Git, request/source identities, contract SHA and verifier source hashes retained.
- Runtime self-claims cannot set quality/adoption; this gate always leaves acceptance_evaluated/quality_verified/adopted false. This is only development contract conformance; no hidden/held-out task feedback, model training or serving promotion. Tests cover a failing second output, missing results, malformed task schema, missing inputs and untrusted runtime adoption claims.

- Actual CLI/H20 CPU isolation verification at source9831d98 used manual fixture candidate9c9c5eb39d045478e2bda101ea05cb84bad5bc990bf6c80c99e72fb77ad6d43f (candidate Git4cc6d28ad82730993b2ff449f2ab6ff578363183). One conforming development sample passed; the same candidate with a second intentionally negative start_seconds result failed at sample_index1. Both reports retained quality/adoption false. No model inference/training/API call. Evidence runs/adapter-contract-integration/summary.json and referenced adapter receipts. This is a schema fixture, not a learned visual adapter or task-quality demonstration.


## Bounded adapter code repair from development failures (2026-10-10)

- adapter-repair reconstructs original candidate source/request hashes and independently replays input/output contract failures before any API call. One bounded LLM response proposes exactly one deterministic new module; isolated child Git candidate retests original development samples/contract. Parent/response/report/control identities retained; no quality/adoption or requirement changes.
- Per-request OS lease and SQLite response journal prevent duplicate API calls. Stable runtime check IDs/leases reuse known results and retain unknown execution without automatic reexecution. Recorded responses remain reusable after documentation-only Git movement when frozen controls/feedback/model match.
- Regression coverage includes parent-child lineage, response/runtime cache replay, API uncertainty, modified feedback and SSH uncertainty. Actual visual-model training, held-out quality and general Agent research-efficiency adoption remain independent incomplete gates.

- Actual DeepSeek Flash repair at source4e96e1f consumed reported1,126 prompt /733 completion /1,859 total tokens. Child1f1370d70900926188509e7775311fae162cab41f75703052f3443e5da40364d passed original H20 CPU isolated development cases; same request replay reused candidate/runtime receipt unchanged. Evidence runs/adapter-repair-integration/{summary,result}.json. Manual source inspection shows fixture timestamp normalization, not a visual model; broader unseen behavior remains unverified.
- Added known-valid-output preservation gate: schema-conforming repairs that alter prior valid development outputs now return repair_regression_failed. Actual saved parent/child responses re-reviewed with this gate:1 known-valid output unchanged, no regressions; no new API or remote call. Evidence behavior-review.json. Quality/adoption remain false; no GPU training.


## Repair lineage call budget admission (2026-10-10)

- Added explicit adapter_repair_calls stage quota, shared across verified parent/child lineage. Request journal insertion and quota occupancy reserve in one SQLite immediate transaction; unknown outcomes retain occupancy, changed contract/quota cannot reset/increase it. Known API records backfilled without API calls; missing historical evidence blocks reconciliation.
- Legacy global llm_calls is audit-only and is never reinterpreted as a fresh per-lineage allowance. Any declared global LLM cap blocks new repair calls until cross-stage accounting is implemented. This is deliberately not a claim of unified Agent budgeting. Example development contract now uses the explicit stage field.
- Tests cover last-slot concurrent admission, unknown API outcomes blocking new request IDs, frozen quota increase rejection, child lineage/restart retention and reconstruction after absent local stage tables. Actual previous Flash response reconciled to1 occupied/1 responded/0 unsettled; legacy audit reports new_calls_authorized=false and global_llm_budget_verified=false. No API/SSH call during audit. Evidence runs/adapter-repair-integration/budget-audit.json.

- Local LLM configuration is now preflighted before call reservation: missing environment key, invalid HTTPS endpoint/port or empty model ID cannot consume a repair slot. New missing-key regression confirms no API request or reservation; API transport/config tests pass. Full171-test suite passed before this preflight addition; final targeted21 candidate and3 LLM tests passed afterward.


## Official baseline resource bootstrap (2026-10-10)

- Verified actual H20 torchvision0.21.0+cu124 enum COCO_V1 URL and official reference boxAP46.7; reference is not our measurement or target60. HTTPS HEAD succeeded for fixed PyTorch weight175,221,657 bytes, COCO annotation archive252,907,541 bytes and val2017 archive815,585,330 bytes. Free notebook storage1,876,397,391,872 bytes at probe. Evidence runs/resource-bootstrap/probe.json.
- Added standalone bounded Linux download step, maximum240s, intended for existing durable CPU scheduler (zero GPUs). Pinned URL/ETag/size, conditional HTTP Range, sidecar checkpoints/full SHA, official weight hash prefix, restart integrity/no overwrite and exclusive workspace lock. This stage only downloads; archive extraction/CRC/image coverage and real evaluation remain pending.
- Four deterministic transport regressions pass: deadline/resume, ignored-range rejection preserving bytes, completed/source tamper rejection, verified-digest rename-crash recovery. No dataset/model artifact tracked by Git.

## Resource extraction gate (2026-10-10)

- Added full SHA-256 verification and bounded ZIP extraction into a new staging directory, CRC verification, unsafe/normalized/duplicate path rejection and no destination merge. Publication occurs only after successful extraction; receipt explicitly leaves dataset coverage unverified. Six download/extraction tests pass.
- Actual CPU download attempt a0 completed with zero GPU-hours: official fixed weight SHA-256 dd69338a24b8d7381807e247652bdc356325bcbaf1cd3e092e00e0a1a58706bf verified, annotations partial. Attempt a1 resumes the same pinned sources under a separate bounded CPU job after a0 terminal confirmation. Validation images, actual archive extraction/coverage and real model evaluation remain pending.

## Dataset readiness separation (2026-10-10)

- Detector dataset-check now distinguishes evaluation_ready (full 5,000-image validation split) from training_ready (full 118,287-image training split plus validation, disjoint image IDs). Validates all referenced image files exist/nonempty, unique image/file/annotation IDs, sparse category IDs, dimensions and finite positive bbox extents; records annotation SHA-256. This does not claim pixels were decoded or AP measured.
- Extraction has a standalone CLI with explicit SHA/byte/file bounds; malformed CRC cleans staging, special files and reserved receipt paths are rejected, including platform-normalized entry names. Actual Linux CPU fixture extraction passed without GPU; evidence runs/resource-bootstrap/extraction-linux-fixture.json. Targeted11 detector/download/extraction tests passed.

- Full182-test suite passed in65.928s after readiness/extraction changes. Attempt a1 terminal completed with archive still partial6,455,415 bytes; bounded CPU attempt a2 resumes it. Actual COCO extraction/evaluation remains pending; no real training or quality/adoption claim.

## Durable resource CLI (2026-10-10)

- Added resources command that journals the exact CPU job/source/remote identity before submitting, observes the same handle after uncertain transport and starts another bounded step only after authoritative completed/partial confirmation. Lost/failed jobs hold their handle; remote spec/source changes reject. Verified download summaries retain dataset_ready=false. Five recovery/source/summary tests plus four transport regressions pass.
- Migrated the existing a2 handle from its saved exact job manifest into runs/resource-bootstrap/cli-records; actual Windows vision-rsi.cmd invocation reported the same running a2 job, new_attempt_started=false. Endpoint throughput probe timed out; it is not evidence of stopped downloader or usable alternate mirror. Real evaluation/training remains pending.

## Official validation dataset verified locally (2026-10-10)

- Same official HTTPS URL/ETag/size probe from Windows transferred1MiB in1.906s, substantially faster than H20 direct route. Completed official annotations252,907,541 bytes (SHA113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268) and validation archive815,585,330 bytes (SHA4f7e2ccb2866ec5041993c9cf2a952bbed69647b115d0f74da7ce8f4bef82f05). Both local ZIP CRC extractions passed.
- Added resource_verify full JPEG decoding/dimension checks/content fingerprint with strict referenced-image coverage. Actual full5,000 validation images/36,781 annotations/80categories passed locally; image bytes814,705,164, annotation SHAe8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f and image manifest SHA4510dc47dfd3f451bbe482a75a98c4c358b2d16eb576a90a390d8fde212bc6c2. Evidence runs/resource-bootstrap/windows-full-validation.json. These are dataset checks, not model AP or training acceptance.
- Annotation archive transferred to independent remote assets/coco2017-prepared, actual zero-GPU extraction job extract-annotations-8047f2a9367a completed with full SHA/CRC verified. Validation SCP is still live under exec session40655; do not overwrite/restart while live. Evidence/handles under runs/resource-bootstrap. Original direct-download job completed partial; original bytes retained, no additional direct attempt started.
- Nine targeted verification/detector/resource CLI tests pass, including actual JPEG bytes, dimension/corruption rejection and content fingerprint changes. Full182-test prior run predates this new verifier; no new full-suite claim.

## Fixed public baseline CPU evaluation entry (2026-10-10)

- Added baseline-evaluate CLI: fixed official weight SHA prefix/full hash, full validation JPEG/fingerprint verification, pinned torchvision runtime/default800/1333 recipe, per-image atomic caches bound to full Python source/model/input bytes. Only full5,000 coverage permits official COCO evaluation and error analysis; partial runs report no AP and never register/adopt a capability. Soft<=240s step requires existing external CPU worker hard timeout.
- Cache regression verifies same-input reuse without inference, changed model/image ID/input refusal and modified saved detections rejection. JPEG verifier regression also passed. CLI help works via actual Windows wrapper. Actual baseline inference/full AP has not yet run: validation transfer still live in exec40655.

## Remote full validation verification and first real CPU predictions (2026-10-10)

- Validation SCP exec40655 completed successfully. Actual CPU job verify-val2017-819658b0a962-a0 completed full archive SHA/CRC extraction and all5,000 JPEG decodes; remote annotation/image fingerprints exactly match Windows. Dataset at /home/tione/notebook/choasliu/vision-rsi-agent/assets/coco2017-prepared/dataset reports evaluation_ready=true, training_ready=false (train images absent). Evidence runs/resource-bootstrap/validation-verify-observation.json.
- Deployed source16f1ec6 content-addressed bundle819658b0a96287364faeeaca16e8056a4288a739b6dae8a1922c75cf06e88b08. CPU baseline job baseline-cpu-819658b0a962-a0 is authoritatively running with zero GPUs,300s external timeout;11 real per-image predictions saved at last observation. Full AP is still unavailable; never infer AP or acceptance from partial outputs. Evidence runs/resource-bootstrap/{baseline-deployment,baseline-eval-job,baseline-eval-observation}.json.
- Local ignored configuration now points at verified remote validation root and fixed weights/annotation hashes; original configuration backed up in ignored runs directory. Original user contract/budget unchanged, no training submitted. GPU budget question remains pending.
- Full189-test suite passed in70.716s. This verifies tested implementation paths, not AP60, strategy efficiency, unseen adapters or launch readiness.

## Official training image download admission (2026-10-10)

- Actual official train2017 HTTPS HEAD returned200,19,336,861,798 bytes and ETag62ff7d7fbcc7e0c0604cbb0f9047ce77-2306; resolved URL unchanged. F drive free653,340,934,144 bytes at probe. Evidence runs/resource-bootstrap/train-source-probe.json.
- Added resources-train local CLI,<=240s per invocation, OS lease, disk reserve for archive/extraction and inherited pinned-source/Range/SHA sidecars. Download completion leaves dataset_ready=false; no extraction/model/training/GPU claim. Six targeted training-resource/download tests pass, including insufficient-disk rejection before network. Existing189-test full run predates this command.

## Independent real baseline cache audit (2026-10-10)

- Added read-only baseline-audit CLI. Checks frozen annotation coverage, record checksums/model identity/image bytes, exact image IDs and sparse COCO category IDs, finite scores/coordinates and image bounds. Explicitly reports partial coverage and quality_verified=false. Negative fixture tests reject semantically invalid detections even with internally consistent cache checksums; model/input mutations rejected without changing records.
- Actual independent H20 audit of164 real image caches/5,533 detections passed at audit sourceeda2c306c3e34b089251ac33b064cf0841c34f723796009ea3383fb2366785af. Expected baseline identityaaea619ccdc33fe8c6c4601d92a9d3ad15383801ca1b18d65f2e679b295a1e66. All first95 cached file mtimes predate resume job start, consistent with fixed cache code reusing outputs without inference. Evidence runs/resource-bootstrap/{baseline-independent-audit,baseline-resume-reuse-evidence}.json. This is not COCO AP, RSI efficiency or quality acceptance.
- Training archive first bounded local invocation finished partial2,363,307,198 bytes; next240s invocation live under exec54420, same pinned source/root. Original exec1601 completed normally; do not restart54420 while live. No GPU use or training.
