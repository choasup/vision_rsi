# 上线验收门槛

目标：Windows 本地 CLI 可交付的视觉 RSI Agent；通过 SSH 执行训练。此文件是尚待完成的验收清单，不是上线声明。公开互联网服务不在已确认部署范围内。

| 要求 | 验收证据 | 当前状态 |
|---|---|---|
| 自然语言 Training/Goal、多轮澄清与契约版本 | 用户会话恢复、需求不丢失、变更记录与契约校验 | 已建立要求的结构变更审核、精确版本接受/拒绝及执行门槛已接并验证；真实DeepSeek单图/联合多图/视频开发回归及有界格式修正已验证；已收响应的进程退出/CLI恢复、精确请求解除与活跃锁拒绝通过；更广独立语义评估和服务端API费用核对待补 |
| 任务内定义单图/联合多图/视频/文本及输出 | 有效与无效样本、输出、时序策略的自动测试 | 协议与联合媒体传输/接收完整性校验已接；Windows任务包→SSH CPU隔离视频解码/原始PTS/帧哈希复跑已用真实编码合成视频验证；多图/视频模型能力及效果待补 |
| 自动组装并调整 harness | 从契约生成真正训练/评测/推理入口并跑通 | 冻结源码的可执行Training/Test任务包（共享原账本、仓库外控制入口已测）、接口harness与固定COCO适配器、有限失败反馈方法提案/冻结源码再部署已接；真实LLM→H20合成训练→收据验收通过执行联调。通用harness代码调整与同一官方COCOeval产生类别AP/诊断匹配计数并接入策略/方法证据；历史H20合成产物复算通过。真实任务效果待验证 |
| 真实训练与 COCO 评测 | 冻结依赖/权重/数据、GPU预算、日志、复跑AP | 单/双卡合成数据训练-推理-官方评测通过；完整5000张预训练CPU基线评测完成，独立本地复算一致；真实COCO训练未完成 |
| AP>=60 首个任务目标 | COCO val 标准评测、独立复跑及完整产物 | 实测预训练CPU基线box AP46.7097，低于60；尚无达标训练模型，不能发布为达标能力 |
| 研究方法及 Agent 自身 RSI | 隔离候选Git版本、同预算配对、保留评估、采用门槛 | 真实LLM源码提案、独立Git候选、CPU隔离执行、单流程审计及实验观察→策略研究建议→真实LLM方法计划联调已接；真实通用harness改进、配对预登记/执行/全组审计入口已接；实际配对保留评估、统计复现、多资源预算及采用门槛未完成 |
| 能力注册与Test版本固定 | 已验收版本与契约/权重/代码哈希，拒绝未达标版本 | 真实收据门槛、pending候选、实际CPU后端分段评测与达标晋级门槛已接；无真实达标模型，完整效果与性能仍待验证 |
| 单输入和批量推理 | 真实媒体结果、多图联合/视频不拆样本、逐项错误和恢复 | 单图/图片目录CPU检测执行及恢复已接；联合多图/视频适配器及完整效果验证未完成 |
| 长程执行、暂停/取消、预算及恢复 | 控制器重启、远端断线、孤儿进程、三种预算故障注入 | 可恢复控制、按ID恢复、有期限前台watch及观察重试已接；实际会话缺配置停止、历史H20作业收据分析联调通过，远端CPU隔离候选主动停止→再次推进→CLI轨迹审计实测通过；暂停/并发变更/状态篡改拒绝通过测试。等待/异常故障用mock验证。远端GPU账本与单卡合成恢复数值对照通过；8卡长程、统一账本及全面故障验证待补 |
| 可安装可启动、配置与密钥隔离 | Windows打包安装测试、仓库外原任务包启动、文档与干净环境试运行 | wheel构建/隔离目录安装与仓库外入口通过；原任务包通过Windows run.cmd仓库外check/prepare实测；新建隔离Python3.12.14 venv安装[coco]、仓库外CLI及7项COCO评测/图片校验通过；Windows3.12本地媒体/COCO依赖带wheel哈希离线安装、pip check及模块入口通过；新生成console exe被本机应用控制拦截（4551），使用已验证的python -m入口。其它平台/训练依赖、构建工具、新Windows机器及完整发布验收仍待验证 |

不得把fixture分数、随机GPU运算、协议校验或绿测试当作任务效果或RSI成功。发布审计需逐项提供直接证据；缺少数据或预算不等于可以降低目标。

## 外部依赖

- SSH 已实际连通，8卡H20曾逐卡验证；每次正式训练仍需重查占用。
- 官方 COCO2017 验证集和固定预训练权重已配置并校验；训练集本地118287张完整像素解码通过；远端分段导入完成，全部图片及原始标注与固定本地校验收据逐字节哈希核对通过。冻结训练程序的完整CPU资源预检也已通过。此为数据准备证据，尚非真实训练或效果验收。
- 真实训练总GPU小时预算未给出；mock预算不是授权。
- DeepSeek Flash真实调用通过，密钥在本机环境变量。

## 当前安装版回归（2026-10-10）

- 源码提交 `c8bd6b9` 的 wheel 在新建 Windows CPython 3.12 虚拟环境中安装；媒体/COCO 依赖按现有哈希锁离线安装，`pip check` 通过。
- 从仓库外临时目录运行已安装模块，逐一核对全部 Python 文件与构建源码一致；94 项安装版测试通过，覆盖源码身份、LLM传输/账本、需求恢复、研究控制、方法提案、审计、候选修复与导出任务包。
- 发现并修复安装版从当前目录调用 Git 导致 Training 控制失败的问题：源码版锚定自身仓库，安装版使用明确的 `source-sha256:` 控制包身份。仓库外 `python -m vision_rsi --help` 实测通过。
- wheel SHA256：`4209af6df2cf8cdfacbf9a2b083d94fcbc72665f5fd0b4fd8175915678ca46d8`。本机证据保存在 `runs/release-current-c8bd6b9/`，未纳入 Git。
- 此为当前代码在本机新虚拟环境的安装/fixture回归，未验证新Windows机器、真实训练、AP>=60或RSI效率，不构成上线通过。

## Serving 真实进程中断验证（2026-10-10）

- 在远端独立 fixture 目录执行当前 `serving.py`，使用无模型的合成 CPU 适配器和三个假样本，未使用 GPU、未计算 COCO AP、未注册能力。
- 两次实际 SIGKILL 及同一评测恢复：首次未产出样本时保留完整 60 秒预留；恢复后完成一个样本，累计约 60.016 秒；再次中断后累计保留 120 秒上限，再调用返回 budget_exhausted。
- 请求扩大到 121 秒被拒绝，状态未改写。调用记录为 val-1 两次（首次中断未保存，恢复重算），val-2 一次（第二次中断）；已保存 val-1 后没有再次计算，缓存文件字节保持一致。
- 可复用 Linux 探针：`tests/serving_fault_probe.py`；真实记录：`runs/resource-bootstrap/serving-crash-probe.json`。控制器有 50 秒总期限并终止、回收自身创建的子进程，保留 fixture 目录供审计。
- 此项仅证明当前分段 serving 的进程中断预算与缓存行为；不证明真实模型效果、GPU 断点数值一致性、网络断线恢复或全部故障已覆盖。

## Serving 并发与损坏状态验证（2026-10-10）

- 扩展同一远端 Linux 故障探针：两次实际并发请求在首进程仍阻塞于合成适配器时被 OS 锁拒绝，持久状态字节和预算预留均未改变；终止首进程后仍可恢复。
- 新增恢复状态校验：拒绝负数、bool、字符串、null、NaN/Infinity 累计耗时，拒绝非法状态、覆盖数量和缓存索引/摘要；不会修正为零或自动重置。已观测的超额耗时仍保留，可正常判断预算耗尽。
- 远端实际验证六类非法耗时和损坏缓存摘要均在新预留前拒绝，原错误记录未被覆盖；预算不可扩大、120秒上限和已保存样本复用仍通过。记录：`runs/resource-bootstrap/serving-concurrency-state-probe.json`。
- Windows 本地纯状态校验及远程能力/serving验收的12项相关测试通过；OS锁和进程中断证据来自真实Linux子进程，不以Windows模拟替代。仍未使用GPU或真实模型，不扩大为整体上线通过声明。

## 有界研究记忆视图验证（2026-10-10）

- 新控制决策使用上下文v4；完整审计历史保留，策略视图最多256行/192KiB，省略记录及截短细节明确标注并保留哈希、原行索引。全历史行动ID检查不依赖压缩视图。
- 本地2500行测试证明原上下文超过旧协议边界，新视图满足边界并保留旧分析/假设、近期状态、测量值与省略详情引用；原历史无改写，改变被省略记录也会改变摘要。旧版重放语义保持。
- 真实远端CPU隔离策略a3c0a7c接收2500行生成的256行/58445字节视图，通过行动协议。记录：`runs/resource-bootstrap/research-memory-remote-probe.json`；没有LLM调用、GPU使用或候选采用。
- 相关34项本地测试通过。此为长上下文开发协议证据，不是研究效率、保留评估或通用长期记忆检索已完成的证明。


## 研究记忆只读查询（2026-10-10）

- 新增 `training memory`：重建 v4 策略视图，使用上下文哈希、快照行数和源行索引取回完整的字段筛选观察。查询不创建会话、不调用远端或 LLM、不改写控制历史。
- 测试覆盖20KB诊断取回、追加后的旧快照、被改动记录拒绝、非法引用，以及实际模块 CLI 路由；现有任务记录实际查询退出0，状态字节未变。证据：`runs/resource-bootstrap/research-memory-cli-live.json`。
- 这是人工审计入口；尚不构成自主检索工具、研究效率提升或上线通过。


## 最新安装版回归（2026-10-10，226498d）

- 将源码226498d构建为新wheel，在新Windows CPython3.12虚拟环境中离线安装带哈希锁的媒体/COCO依赖；`pip check`通过。
- 在仓库外临时目录执行安装版`training memory --help`及58项控制/研究记忆/审计/运行时/Serving相关测试，全部通过。逐项比较安装包Python/HTML文件与当前源码哈希，全部一致；运行时控制身份使用`source-sha256:`。
- 首次回归暴露一项测试按当前目录读取示例文件，已改为按测试源码位置读取后复验；未改动产品行为来绕过失败。
- wheel SHA256：`ae70102f2216156c413bbc8f0e9d53d89502f37e585082488e8c5bfebc074f47`。本地安装证据：`runs/release-current-226498d/installed-evidence.json`及`installed-tests.log`。
- 仍是本机隔离安装证据，未证明新Windows机器、全部平台、真实训练或AP>=60达标，也未证明RSI效率提升。

- 同轮源码全量回归292项通过（112.505秒），产品源码未改；记录：`runs/release-current-226498d/source-regression.json`。


## 受控策略记忆读取（2026-10-10）

- 新控制行动版本2允许策略从控制器列出的 `retrieve_memory` 候选读取被省略/截短的历史分析，每页1024个规范JSON ASCII字符，占用一个控制步数。最多8个来源候选，下一未读页推进；只返回字段筛选观察，不读取任意文件，不调用LLM或训练。
- 源行及完整观察SHA256绑定，结果持久化后进入下一上下文。测试验证全部页可重构20KB诊断、同页不再提供、源内容改变/非法引用拒绝、真实advance持久化和未调用训练。审计重放重算页面，伪造诊断被拒绝；旧控制行动版本的候选集合保留。
- 真实远端CPU隔离候选a3c0a7c完成两轮开发协议：从230354字符的合成分析选择第0页，控制器返回1024字符，下一上下文可见，并选择offset1024的下一页。证据：`runs/resource-bootstrap/research-memory-retrieval-remote.json`。无GPU、无LLM调用、无采用。
- 此为研究控制机制及协议验证，未证明策略会在真实研究中恰当地选择检索、研究效率提升、通用记忆检索或模型达标。

- 本轮42项相关回归及源码全量297项测试通过（111.310秒）。未重新构建安装包，先前安装版226498d不包含这项新工具。


## 记忆读取实际进程退出与损坏引用（2026-10-10）

- 增加完整页引用元数据校验：源行动ID、总字符数、分页大小均须与源观察一致。非法索引/页偏移/哈希和被改变元数据被拒绝。
- 损坏记忆状态的顶层结构、binding/history及观察结构返回明确CLI错误，退出1，不输出内部Traceback、不改写原记录。
- 可复用本地探针`tests/research_memory_fault_probe.py`：合成1000行历史，在实际子进程读完页但结果尚未持久化时`os._exit(73)`，第二个独立进程成功恢复，OS锁释放；原历史保留，结果与退出前读值一致，只新增一页，下一页offset1024。保留未完成started及恢复completed两次尝试记录，不掩盖中断。
- 实测证据：`runs/resource-bootstrap/memory-fault-7d2d0f57380146498fea8bcba5743382/evidence.json`。49项相关本地回归通过（5.955秒）。无远端、LLM或GPU调用；本轮未重跑全量测试或重建安装包。
- 此项证明实际进程退出后的幂等读取恢复；不等同断电持久性、所有故障覆盖或真实研究效率验证。


## 本地启动诊断纠正（2026-10-10）

- `doctor` 不再固定报告真实训练未实现；明确当前固定COCO适配器和有限配方实验范围，并分别报告本地配置检查、任务预算未核查、API/远端未实测和效果/发布未验证。
- 使用实际LLM配置校验器检查HTTPS、模型、当前进程Key及账本路径/调用上限；校验不创建账本、不进行API/SSH调用。缺失/畸形配置不会误报就绪，Key只返回存在布尔值。
- 实际模块与Windows启动器分别验证：模块进程当前无Key，启动器从已设置的Windows用户环境加载后配置检查就绪；原配置文件不变。证据：`runs/resource-bootstrap/doctor-live-local.json`。不将配置就绪当作训练授权或上线通过。


## 最新工具安装交付复验（2026-10-10，2a822a7）

- 将包含策略记忆检索、实际进程退出恢复校验和新doctor的当前源码构建为wheel，在新的Windows CPython3.12虚拟环境按哈希锁离线安装；`pip check`通过。
- 仓库外临时目录使用真正site-packages包完成68项相关回归，全部通过；所有包内Python/HTML文件与源码逐项SHA256一致。wheel SHA256：`ffa3c51a720b8310003991f6e9759490c3987b6d389fb293309e2d14e6fef374`。证据：`runs/release-current-doctor/installed-evidence.json`及`installed-tests.log`。
- Windows启动器实际重新prepare原任务my-vision-task；计划ea7cdefa9b22e9e0e38aa3d33340f55cbc3d931ef10a81f87921c6726bbffa59仍因真实GPU预算未设置而blocked，未开始训练，GPU预算及超时保持null。记录：`runs/resource-bootstrap/current-task-prepare.json`。
- 此项只补齐当前源码的本机安装与入口验证；不是新Windows机器、其它平台、真实模型达标、完整多资源预算或RSI研究效率通过。


## 控制版本语义边界（2026-10-10）

- 修复审计将所有>=2行动版本当作版本2，以及bool/浮点可通过整数版本比较的问题。统一校验支持上下文整数1..4、行动整数1/2；行动2必须对应上下文4。缺失字段明确回放旧版1，不猜测未知版本。
- advance/resume在工具执行和状态改写前校验完整历史、意图及停止记录；非法版本拒绝执行且原状态字节不变。show/pause保留调查入口。审计在读取候选证据前拒绝未知版本，并保持各旧上下文版本及新行动版本的合法回放。
- 56项相关回归通过（6.806秒），覆盖非法类型/未知版本/不兼容组合、未知意图和历史恢复拒绝。真实进程退出恢复探针复验通过：`runs/resource-bootstrap/memory-fault-8e2f7e7c9f334035a0b2319a8ec10542/evidence.json`。
- 未重建安装包；最近2a822a7安装包不包含本轮版本校验。此项不构成模型效果、RSI效率或整体上线通过。


## 真实自然语言→接口开发评估及中文视频策略（2026-10-10）

- 新显式探针`tests/live_requirements_probe.py`先固定3份新开发需求（COCO单图缺预算、2..5图工件联合缺陷检测、3fps视频事件）与检查项；独立调用账本最多准入6次，实际DeepSeek Flash响应5次（含格式修正），报告12885 tokens，无未知token调用。费用未与服务端账单核对，无训练/远端/GPU调用。
- 首轮严格判定2/3：单图保留AP60且只问缺失GPU预算；联合多图保留joint、2..5数量、类别/严重度及F1目标；视频保留事件输出和F1/IoU要求，但生成中文“每秒3帧/保留原始时间戳和帧顺序”，未满足初版英文字面采样检查且现有编译器也不接受。失败原记录保留，未重跑API或覆盖判定。
- 修复视频计划编译：确定性接受等义中文及Nfps空格/大小写形式，契约原文不变；歧义、非法类型、0或超限帧率、乱序/音频等不支持策略继续blocked。5项视频测试及共41项接口/契约/媒体相关回归通过（5.758秒）。
- 不重发API，使用同一三份实际生成契约构建可执行接口包，仓库外check均退出0；视频包冻结3fps计划，需求版本未改，model_quality_verified/training_performed均false。证据：`runs/requirements-live/f531f06c2b5343a6bdb8ef6547870ed2/{summary.json,video-compiler-postfix.json,harness-checks.json}`。
- 后续探针评分器v2按实际编译语义检查视频帧率，并在新运行预登记中加入探针源哈希；本轮原2/3结果不据此重评为通过。该证据不是独立统计评估、真实模型推理、多图/视频任务效果或上线通过；当前安装包尚不含本轮中文解析。


## 中文视频契约→实际CPU解码及时间网格修正（2026-10-10）

- 直接复用此前真实DeepSeek生成的中文视频契约，冻结实际SSH配置，从Windows run.cmd执行打包/验证和两次远端隔离CPU解码；未改需求版本，无新增API/GPU/训练/模型推理。
- 实测暴露旧最小帧间隔算法在本段源视频上3fps和2fps同选0/.5/1秒的问题。保留原v1证据：`runs/video-chinese-live/61ade19944ea4a009fd4d9eca336d386/summary.json`，不把它声称为目标固定采样率通过。
- 新任务包默认`source_time_grid_v2`，以首源时间为原点，每个有帧的[k/fps,(k+1)/fps)区间选首帧；空区间跳过，不复制帧。保留显式旧v1协议及其最小间隔校验。接收端按原始PTS/时间基准有理数独立验证网格区间不重复、时间严格递增、字节与尺寸等既有边界。
- 同一实际源视频/中文契约的新冻结包两次解码得到0/.5/.75/1秒，帧哈希及PTS完全一致；再次执行旧冻结包仍返回v1和0/.5/1秒，确认升级不改旧包行为。证据：`runs/video-chinese-live/fd56de1bca3a44feb1b0852fdf1ee239/summary.json`及`legacy-frozen-recheck.json`。
- 6项视频测试通过；此为真实媒体/CPU协议证据，不是视频模型能力、事件F1或上线达标。源帧不足时不承诺精确固定输出率；新安装包尚未重建。

- 本轮源码全量309项测试通过（112.614秒），未以CPU媒体验证替代真实训练或任务质量验收。


## 跨进程累计控制工具尝试上限（2026-10-10）

- 新可选顶层配置`controller.tool_attempt_limit`（整数0..100000），绑定campaign身份；每次工具开始前持久化尝试，完整历史及待执行意图累计，已完成/started/不确定/未发送均计数，重试另计。缺省不启用；实际用户GPU授权未改。
- 达限后advance/watch返回`controller_budget_exhausted`，不取消远端作业、不删除意图、不因暂停/恢复或重启刷新；selected campaign不能删除/改变上限。独立新campaign仍有独立计数，不宣称全会话、多资源或费用总预算已实现。
- 导出任务包保留配置，doctor本地检查非法配置，CLI展示累计/剩余数，审计核对完整尝试证据和预算终止状态；非法/缺失账目拒绝执行，show/pause保留调查入口。测试覆盖未知尝试保留、重试额外计数、1000行压缩视图不减少计数、零上限、非法类型及导出一致性。
- 可复用本地探针`tests/controller_budget_cli_probe.py`：4个实际独立CLI进程，计数始终1，后续advance/watch停止，状态不因重复调用改写，未创建训练运行。证据：`runs/cb-36dc3aee/evidence.json`。无API、SSH或GPU调用。
- 首个深层fixture在准备计划时触发Windows路径错误；原错误和已占用的1次尝试保留，未据此声明长路径支持通过。失败证据：`runs/controller-budget-live/7c6d4a2a2ed84431a02266e2847d00c1/path-failure-evidence.json`。成功探针采用短工作路径；Windows长路径支持仍为待处理缺口。
- 本上限不计策略决策调用、Token、GPU小时、墙钟或费用；统一多资源与真实研究效果仍未验证，未重建安装包。

- 本轮产品源码全量317项回归通过（114.206秒）；另补充2项测试后，19项相关复验通过（1.784秒）。未将此声明为统一预算或上线通过。


## Windows计划/方法实验深路径修复（2026-10-10）

- 针对上一轮实际WinError3，新增本地文件I/O路径转换；Windows长绝对路径使用扩展命名，短路径和非Windows保持原形式，已扩展路径转换幂等，UNC转换仅做词法处理。不改系统长路径策略或注册表。
- 训练计划目录/原子保存/返回plan_path，以及方法实验请求SQLite、响应文件、派生计划使用该转换；旧冻结包不会被改写。
- `tests/controller_budget_cli_probe.py --deep`在与原失败相同目录结构上实际执行4个独立CLI进程，288字符计划路径创建和JSON读回通过，累计预算仍1，后续停止且无运行创建。证据：`runs/controller-budget-live/fd29b1ced71d44ed8903cd676c0035d1/evidence.json`；原失败证据保留。
- 43项相关测试通过（2.354秒），包括真实深目录原子写入、原生WindowsUNC词法转换，以及深实验请求SQLite/响应/计划写入和缓存重放；方法LLM为mock，无真实API/GPU/训练调用。测试按所有权逐项清理自身文件/目录，避免普通短路径清理递归失败。
- 仅证明本机这些原生文件I/O链路，不扩大为所有路径、Shell、Git/外部工具、真实网络共享或新Windows机器均通过；安装包尚未重建，真实训练/AP60与统一预算门槛仍未完成。

## 累计控制预算的实际进程退出验证（2026-10-10）

- 新增可复用 `tests/controller_budget_fault_probe.py`：本地fixture上限1，在prepare返回blocked之后、结果写回campaign之前执行真实 `os._exit(73)`；另三个独立进程验证再次推进、显式恢复、再次推进。
- 原始started意图逐字段保持，累计占用1、剩余0、无完成历史追加、无免费重试；新进程能取得已释放的进程锁。证据：`runs/resource-bootstrap/budget-fault-e5693915d94346f3a90b87abd28e60b5/evidence.json`。
- 初始探针fixture缺少contract version而失败；修正探针输入后复验通过，没有将初次失败作为成功证据。31项预算/watch/campaign相关测试通过（5.192秒）。
- 本次没有API、SSH、GPU或真实训练调用；这不证明断电持久性、远端训练中断恢复或统一费用记账，实际任务GPU预算与AP60验收仍未完成。

## 当前源码离线安装复验（2026-10-10）

- 将产品源码25cf2b8构建为新wheel，SHA-256 `68840b8e19f7581a7728be2267d7ceb231d840ac524a70724627d878251be94a`，位于`runs/release-budget-video/wheelhouse/vision_rsi_agent-0.1.0.dev1-py3-none-any.whl`。不替换先前安装包或冻结任务包。
- 创建新venv，使用既有本地wheelhouse及Windows3.12依赖哈希清单离线安装；Agent无依赖安装，pip check通过。构建工具仍使用本机环境，未声称可复现构建锁已完成。
- 新增可复用`tests/installed_release_probe.py`，在仓库外临时目录导入site-packages、逐一核对Python/HTML文件集合及SHA，验证3个模块CLI帮助入口和120项相关回归（11.416秒）。包含近期控制预算、版本审计、记忆、视频、深路径/SQLite、可执行任务包及未发送API恢复逻辑。
- 初次120项运行中12项因测试按cwd读取示例契约而失败，原日志/evidence保留于`runs/release-budget-video/`；修正两份测试的fixture路径后120项全部通过，成功证据另存`runs/release-budget-video/verified/{installed-evidence.json,installed-tests.log}`。产品源码和wheel未因此改动。
- 已安装控制包identity为`source-sha256:127946a1957f0417fcea70d6d082194c1d28b863f220aadd99c35abc425662e4`。测试运行没有API/SSH/GPU调用，不替代真实COCO AP60、8GPU恢复、跨任务模型能力、统一成本预算或新机器验收；目标仍未完成。

## CLI控制状态可观测性修正（2026-10-10）

- 修正campaign人类可读摘要遗漏嵌套plan.blockers的问题；计划路径、Campaign/会话/运行标识、控制记录路径、暂停状态和待处理动作/尝试预留数量现在直接显示。去掉上层重复输出。
- 控制工具尝试预算耗尽时明确显示剩余数、恢复不刷新上限、保留原记录；有原run_id时提示实时查询/日志/取消入口，暂停不等于取消远端作业。
- 22项training shell/控制预算/watch相关测试通过（1.864秒）；去重后7项shell测试再次通过。实际对既有本地fixture运行agent-status，显示1/1、剩余0、原嵌套阻塞原因和路径，无API/SSH/GPU调用。
- 本轮只改变源码CLI展示，不修改任务预算或campaign状态，也未重新构建上一轮安装包；完整上线门槛保持未完成。

## 自动方法搜索谱系与重复拦截（2026-10-10）

- 新方法实验冻结`experiment.method_ancestry`，把当前/祖先配方中可变方法参数提供给规划模型；确定性编译拒绝返回祖先配方（例如A→B→A），保留parent run/plan和原有预算、数据、模型/权重约束。
- 重复响应作为proposal_rejected保存到原请求；缓存复读不再次调用LLM。损坏谱系在请求账本/联网之前拒绝。谱系记录的是计划配方，不自动认定所有方案均已训练或验证。
- 新测试覆盖两代累计与返回祖先拒绝、提示词历史传递、拒绝缓存以及损坏谱系阻断。初次按模块名调用受测试内部同级导入影响失败，调整测试搜索路径后34项相关测试通过；随后加损坏谱系测试，全量328项通过（114.154秒），日志`runs/lineage-regression.log`。
- 没有真实API、SSH或GPU训练调用。仅覆盖已保存的同一计划谱系；旧计划的未知祖先不补造，跨campaign全局去重、显式统计复现实验、真实研究效率与上线质量仍未完成。未重新构建安装包。

## 方法提案拒绝反馈闭环（2026-10-10）

- 修复下一轮方法规划缺少前次编译拒绝原因的问题。新请求从同一本地请求账本选取同父run_id/plan_id/receipt SHA的最近最多8条已响应且proposal_rejected的记录，附限制长度的原因/原提案及完整响应、结果哈希。
- 提示词明确反馈是不可信证据，不是训练测量或修改约束的授权。反馈快照随请求context持久化；复读旧请求使用原快照，后来增加反馈不触发context漂移或免费API重试。旧无反馈context仍兼容，模型/账本等既有绑定继续核验。
- 50项实验/campaign/审计/控制预算/未发送API恢复相关测试通过（5.879秒）。覆盖非法提案→反馈进入新请求→有效提案、原拒绝/新结果缓存重放仅2次mock调用、8条/字符上限和其它父receipt排除。
- 无真实API/SSH/GPU调用，不声称模型必然纠错或真实研究效率提升；安装包尚未重建，真实训练质量与完整上线门槛仍未完成。

## 真实DeepSeek方法反馈开发探针（2026-10-10）

- 新增显式`--live`的`tests/live_method_feedback_probe.py`，使用明确合成的AP42/预算1 fixture，预登记源码哈希、种子非法提案、通过标准。预算仅为测试输入，不授予实际用户GPU训练。
- 首条非法提案由mock种入本地编译流程（world_size修改被拒绝），明确不是提供商输出；后续仅一次真实deepseek-flash API调用，独立账本上限1，读取Windows本地环境密钥、不打印密钥。
- 实际请求context包含synthetic-rejection反馈；返回支持的min/max_size、learning_rate等方法字段，状态ready_to_submit；祖先配方保留1条。缓存重放在禁止创建API客户端的条件下与原结果一致，没有新增调用。
- 证据`runs/method-feedback-live/931e24134bc54c01aa177c00098d206e/{preregistered.json,seed-result.json,evidence.json}`及research请求账本/原响应。账本1次responded，报告prompt1228/completion425/total1653 Token，无未知Token调用；账本剩余0，不声称覆盖账户其它账本或实际费用结算。
- 这是一个合成开发样例的真实API/编译证据，不是模型改善、统计成功率、实际GPU训练或RSI研究效率。没有语义重试、SSH或GPU调用，完整上线门槛仍未完成。

## 配对研究保留控制/API约束（2026-10-10）

- 修复paired study配置复制遗漏`llm.usage_ledger`、`usage_call_limit`和`controller.tool_attempt_limit`的问题：新预登记的两组配置及campaign binding均保留原约束，不因进入study路径而静默去掉上限。
- 预登记本地验证controller配置、绝对账本路径及调用上限类型；声明调用上限但缺少共享账本时拒绝。验证不创建API账本、不联网；凭据值继续排除，api_key_env名称可保留。
- 39项paired study/campaign/控制预算/API账本相关测试通过（6.151秒），包括两组绑定一致、密钥未序列化、非法约束拒绝及未创建账本/研究目录。
- 已有研究冻结记录不回写。本次没有真实API/SSH/GPU调用；共享API调用总上限不等于每组独立相等Token/费用预算，实际公平性、独立保留集和统计RSI效率仍未证明，候选不自动采用。安装包尚未重建，完整上线目标未完成。

## 配对统计证据门槛（2026-10-10）

- 新study identity冻结固定单侧精确符号检验规则、alpha=.05、最少5个非平局配对；每对gain与预登记minimum_mean_ap_gain比较，平局精确排除，以Binomial(n,.5)右尾计算p值。方法核对NIST符号检验文档；这是条件方向性概率检验，不是均值增益置信区间。
- compare仅在全体预登记配对证据完整后输出统计信息，与已有平均增益规则分开。缺失证据不评估；旧study无统计规则时明确未预登记，不事后改记录。
- 19项paired study/campaign audit/policy audit测试通过（.943秒）。覆盖5胜p=1/32、4胜1负p=6/32、2胜p=.25仍不足、平局/非法数值、规则变更拒绝、缺失及旧记录不评估。
- 单位测试为合成计算/审计fixture，没有实际训练、API或SSH。任务独立性、跨候选多重比较与完整资源公平性未证明，rsi_efficiency_verified/agent_adopted仍false；不把统计单项当成上线或候选采用通过。安装包尚未重建。

## 源码CLI调用目录修正（2026-10-10）

- 修复vision-rsi.cmd/launch_agent.py先切换项目目录，导致training/test显式相对输入、输出、配置或存储参数被解释到错误位置的问题。cmd用绝对路径调用Python启动器；启动器先捕获调用目录，对支持的显式本地任务路径做绝对化，再沿用项目目录中的默认状态。
- 同时支持分离参数和--flag=value，保留自然语言goal/task ID、缺省参数及缺值错误处理；不改其它子命令、安装模块CLI或JSON内部URI的规则。
- 9项launcher/training shell测试通过（.388秒），含真实子进程从外部临时目录读取其相对sessions；另从既有fixture目录实际执行Windows vision-rsi.cmd，返回正确原session 6fe2a8baf0764d798a07537b1df69ad2，未意外切到默认库。
- 无API/SSH/GPU调用；本轮只涉及源码启动器及相关文档，不声明真实训练质量或完整上线已完成。

## 批量恢复的整批预检查（2026-10-10）

- 修复按行校验/重试交织的顺序问题：前行失败样本可能已经重试，后行才发现输入或成功缓存被修改。现在在任何新infer之前先计算/核对全批指纹及成功输出哈希，再处理失败/未完成项；成功样本仍跳过。
- 新测试构造首项失败、后项成功，分别修改后项输入和缓存；恢复均拒绝，infer调用0、batch-state字节不变。原真实子进程中断/OS锁释放及续跑跳过成功项测试仍通过。
- 20项batch/capability/remote capability/media相关测试通过（1.372秒）；初次模块名调用遇同级fixture导入失败，修正测试搜索路径后通过。无真实API/SSH/GPU调用。
- 派发时既有expected_input_fingerprint验证保留；不声称阻止校验后并发修改或证明所有损坏状态均被识别。安装包尚未重建，真实任务效果与完整上线验收未完成。

## 任务适配器兼容性职责抽取（2026-10-10）

- 将training_plan中的COCO输入/指标/输出兼容性检查抽为确定性task_adapters.training_adapter，保留原阻塞条件；新计划保存adapter_id/implementation_supported及独立的未训练/未验收标记。
- 新可执行任务包check同时报告训练适配器兼容性，避免仅控制接口检查通过被解读为任意视觉任务已有训练实现。现有COCO单图后端仍是唯一已实现训练路径；这次抽取没有新增多图/视频模型。
- 27项适配器/可执行harness/COCO训练配置/需求/交互shell相关测试通过（5.788秒），包括兼容契约不变更、joint/video/text/F1/不兼容输出拒绝，以及冻结包check明确不支持其联合任务。
- 无真实API/SSH/GPU调用。旧冻结任务包不自动升级，安装包尚未重建；真实COCO AP60及跨任务训练/模型效果、RSI效率与完整上线门槛仍未完成。

## 近期改动的全量与新安装包复验（2026-10-10）

- 产品源码b794156全量338项测试通过（113.619秒），日志`runs/release-adapters-full-tests.log`。覆盖近期谱系/拒绝反馈、配对预算/符号检验、启动路径、批量预检查和适配器职责变化。
- 新wheel SHA-256 `3a50e8e5716c5d2534d4ce9e3dbb9dc3f8163a461fb2662803f3bb44d51bfaa7`，位于`runs/release-adapters/wheelhouse/vision_rsi_agent-0.1.0.dev1-py3-none-any.whl`。新venv使用既有哈希依赖清单离线安装，pip check通过；本机构建工具未锁定，不声称可复现构建或新机器验收已完成。
- 安装验证器增加task_adapters模块，在仓库外临时目录核对Python/HTML完整文件集合及哈希、3个模块CLI入口和132项相关测试通过（12.387秒）。证据`runs/release-adapters/{installed-evidence.json,installed-tests.log}`，控制包identity `source-sha256:fd2a2b519559e762c059b5f34e8decdb5dd6459615df688b427228a6aefc04cb`。
- 另用安装解释器在仓库外工作目录的3个独立CLI进程实跑toy阈值训练→固定版本双样本batch→resume，2成功/0失败，恢复状态字节不变。证据`runs/release-adapters/cli-demo/evidence.json`及`cli_demo_probe.py`；明确不是实际视觉模型或COCO质量验收。
- 本轮无真实API/SSH/GPU调用。安装模块不包含仓库根的cmd启动器（该入口已单独验证）；旧安装包和冻结任务包保留。实际GPU预算、COCO AP60、8GPU长训恢复、跨任务模型能力、统一资源公平性和RSI效率门槛仍未完成。

## 只读实际任务就绪检查（2026-10-10）

- 新增training readiness及交互/readiness，在构造可写Sessions之前分派。Sessions新增显式read_only模式，SQLite mode=ro、不创建根目录/表；缺失账本拒绝，写入由SQLite拒绝。
- 汇总契约/待确认变更、COCO适配器兼容性、本地doctor配置、真实GPU预算、已有训练账本剩余快照/未结算运行；检查非法GPU账目，状态仅blocked或ready_for_prepare。后者不是运行环境或质量验收。
- 28项就绪/契约/需求/shell相关测试通过（.974秒）；交互入口补充后10项相关复验通过（.204秒）。覆盖缺失库不创建、原库字节不变、只读连接写拒绝、缺预算阻止及授权兼容fixture只允许继续prepare。
- 用源码Windows启动器实际检查用户session df8e8f8991ee496d859e35fab2085d8f：状态blocked，真实GPU预算None，当前阻塞为GPU小时预算尚未提供。未替用户填写预算，未调用API/SSH或启动训练。
- task_quality_status=not_checked、release_verified=false；不覆盖已有历史质量证据，也不据本地检查推断上线。安装包尚不含本轮命令，完整目标未完成。

## 内层方法规划接入历史测量（2026-10-10）

- 修复外层策略已有历史指标，但propose_experiment内层LLM只看当前失败和配方谱系的缺口。controller现在把同一v4有界字段投影视图传给方法规划，包含旧测量/方法/假设/成本快照及已取回记忆页；不直接转发raw result或未选字段。
- research_history以最多256行/192KiB限制并与请求context持久绑定；非法/超限输入在请求账本和API之前拒绝。同一请求历史改变拒绝，缓存相同历史不重发。提示词明确不完整视图、未知测量、不可信文本及成本快照不能累计为增量。
- 50项实验/campaign/研究记忆/上下文相关测试通过（6.094秒），覆盖旧AP40进入提示词、未选api_key字段排除、历史改变拒绝、缓存仅1次mock调用和超限前置拒绝。
- 无真实API/SSH/GPU调用；不能据此声称模型已比较历史或研究效率提高，安装包尚未重建，完整目标未完成。

## 当前远端环境只读复验（2026-10-10）

- 实际SSH连接独立服务器成功，查询时8张NVIDIA H20均可见（各97871MiB，利用率0，显存使用3MiB）；仅观察瞬时状态，不代表资源已预留或长期空闲保证。
- 基础Python未安装pycocotools；核对实际训练预检使用的workspace/runtime-coco-2.0.11目录后，固定版本2.0.11及_mask.abi3.so编译模块导入成功。没有为基础环境重新安装或修改依赖。
- 复查训练/验证目录文件计数118287/5000，以及train标注469785474字节、val标注19987840字节、预训练权重175221657字节；三个文件SHA与当前本地配置完全一致。没有据计数推断所有图片内容未变，本轮未重哈希图片集。
- 原始只读结果`runs/resource-bootstrap/remote-readonly-20261010-current.json`，本地比对证据`remote-readonly-20261010-verified.json`；原始结果SHA-256为49f4917e62c30dcb9cd061993468cd8ec8dd1051f573cc9e268faf3783406733。
- 本次网络调用仅执行依赖元数据/编译模块导入、文件计数/hash及nvidia-smi查询，没有训练、GPU计算、API调用或作业启动。GPU小时授权仍未提供，不能用空闲GPU状态替代授权；真实训练质量、数值恢复及完整上线门槛仍未完成。

## checkpoint恢复进度一致性（2026-10-10）

- 新增确定性validate_checkpoint_progress，在checkpoint身份核对后、加载恢复模型/优化器状态前检查epoch/cursor/step整数类型、范围、总步数关系及每rank CPU/CUDA RNG字段存在性。全epoch完成游标0，以及epoch末cursor等于批数均支持。
- 批数按DistributedSampler默认补齐、DataLoader不丢末批计算。25项COCO训练配置/运行时/训练账本测试通过（1.131秒），覆盖17图/8rank/批2的非整除样例、epoch边界、布尔/负数/超界/不一致step和缺rank状态。初次命令包含不存在test_resume模块，去除后相关测试通过，未据失败命令声称全过。
- 真实SSH CPU PyTorch 2.6复验：17图8rank各2批、118287图8rank各7393批、17图1rank9批，与新校验器一致。证据`runs/resource-bootstrap/checkpoint-progress-cpu-torch.json`，校验函数源SHA2950ec985246623bb93b52110697a46e0e3dadc1232b967747cd8a481f53276f。
- 远端只执行CPU采样器/loader长度及结构校验，没有模型训练或GPU计算。RNG值使用opaque结构fixture，不能证明张量有效、模型数值一致或8卡实际断点恢复；GPU训练预算仍缺，完整上线门槛未完成。安装包尚未重建。

## 多卡共享图片身份避免重复全量读取（2026-10-10）

- 原训练run在每个rank独立哈希全部train/val图片内容，造成重复读取。单主机共享数据路径现在仅rank 0计算同样编码的全图片摘要，再通过进程组广播；文件读取异常先广播错误状态，所有rank拒绝，摘要格式也验证。
- 显式拒绝多主机/LOCAL_WORLD_SIZE不同的启动配置；各rank的数据预检保留，没有用缓存计数代替内容哈希。原代码/recipe/runtime身份约束不移除。
- 26项COCO训练配置/运行时/账本相关测试通过（1.203秒），覆盖单rank/模拟多rank摘要一致、其它rank零重复hash调用和错误传播。
- 实际远端CPU torchrun两进程Gloo复验：两张合成文件rank0读取2次、rank1读取0次，摘要相同；模拟读取失败时两个rank均收到OSError失败状态并干净退出。证据`runs/resource-bootstrap/shared-image-hash-cpu-broadcast.json`，helper源SHA182241fc22b63ff29550e41e38eb7fcb5a07f42653b483fda7a8323e88c295a3。
- CUDA_VISIBLE_DEVICES对探针子进程设空，无GPU计算或训练；仅两进程CPU通信证据，不证明8卡NCCL、真实吞吐提升或数值恢复。真实训练GPU预算及上线门槛仍未完成，安装包尚未重建。

## 恢复提交前CPU checkpoint进度门槛（2026-10-10）

- 将新checkpoint进度校验接入resume的CPU资源预检，传递原output directory及选定SHA。远端限定Training存储内路径、固定baseline最大2GiB文件，CUDA_VISIBLE_DEVICES空，torch.load使用CPU/weights_only；哈希在读取前后均核对。
- 本地必须收到checkpoint_progress_checked=true及相同SHA回执；否则沿用resume_preflight_failed/实际GPU小时0路径，不提交GPU作业。该流程可有短暂本地预留，预检失败会结算为0，不将其描述为从不创建预留。
- 27项预检/训练账本/COCO配置相关测试通过（1.017秒），覆盖checkpoint请求绑定、缺失/错误回执拒绝、resume传参及既有预检失败不调用submit。补充2GiB检查后远端探针源码语法编译通过。
- 旧冻结包缺少validate_checkpoint_progress时新控制程序预检拒绝，不自动升级旧代码；旧冻结程序保持自己的原行为。本轮无真实API/SSH/GPU调用，仅mock资源回执及本地语法证据，尚未在真实checkpoint上跑完整CPU预检。
- CPU进度门槛不证明全部权重/优化器/RNG张量、GPU运行时身份或8卡数值恢复；真实预算与完整上线门槛仍未完成，安装包尚未重建。

## 冻结包CPU checkpoint预检真实链路（2026-10-10）

- 新增显式--live-remote的tests/live_checkpoint_preflight_probe.py，固定预登记两种进度结果，创建独立远端fixture目录，不改实际COCO数据、权重或用户训练预算。
- 实际部署当前冻结源代码，微型COCO结构train/val各1张图、80类定义，文件哈希核验通过；Torch真实序列化合成checkpoint，先epoch0/cursor0/step1拒绝，再step0通过，CPU回执绑定各自选定SHA。错误checkpoint另存invalid-checkpoint.pt，原拒绝证据保留。
- 实际冻结bundle afd26853b8d0c93c8d686c9bd0bed1aebaa523f4e2c4f7fd23a05a9dfceaaa5d；证据runs/resource-bootstrap/cpu-progress-probe-2e59e72fb3144a5ba55152a2055de886/{preregistered.json,resources.json,deployment.json,invalid-result.json,valid-result.json,evidence.json}。
- CUDA_VISIBLE_DEVICES为空，仅SSH CPU文件/序列化/冻结包预检，不调用LLM、不运行GPU或训练。checkpoint的model/optimizer及CUDA RNG是明确结构fixture，不能据此证明实际检测器状态有效、GPU运行时身份或8卡数值恢复；完整上线门槛仍未完成。

## CPU checkpoint随机状态校验（2026-10-10）

- 新增validate_checkpoint_rng并接入CPU预检及GPU训练恢复：各rank RNG需非空一维CPU uint8张量；CPU状态实际尝试torch.set_rng_state后，在finally中还原检查进程原状态。预检不调用CUDA随机状态接口。
- 28项COCO/CPU预检/训练账本相关测试通过（.974秒），含模拟CPU状态不兼容时仍恢复调用方状态及非张量前置拒绝。
- 冻结新代码真实远端CPU探针通过：错误进度拒绝、float类型CPU RNG拒绝、有效CPU状态/正确进度通过。原失败checkpoint和invalid-rng-checkpoint另存，证据runs/resource-bootstrap/cpu-progress-probe-a4920bcc543c4e20bc748aa1474e92ed/；冻结bundle1ef7f7329c20755eacec447c1ba0b7082f754b859276006f79d9cb8ce41a3d41。
- CUDA禁用，无模型训练或GPU计算。CUDA字段仅结构检查，合成model/optimizer仍不是有效检测器状态；未证明CUDA RNG兼容、完整8卡数值恢复或COCO质量。安装包尚未重建，GPU授权及完整上线门槛仍未完成。
## 视频事件独立评测工具（2026-10-10）

- 新增 evaluate-events，固定 event_micro_f1/v1 协议，类别与时间 IoU 最大数量一对一匹配；精确样本覆盖、输入校验、原始文件哈希及独立阈值结果。
- 5项测试通过，覆盖贪心匹配陷阱、重复预测、无预测、非法输入、覆盖不完整、边界值及真实子进程 CLI。Windows vision-rsi.cmd 示例实际执行成功，合成事件 F1=1；证据 runs/events-demo.json。
- 仅独立评分工具，没有视频训练/推理模型接入、能力注册或数据来源证明；不把合成指标作为模型质量。安装包未重建，完整上线门槛仍未完成。
## 事件评测绑定任务验收定义（2026-10-10）

- evaluate-events 新增 --contract，严格绑定 event_micro_f1/maximize、精确协议ID、显式IoU/F1阈值及逐样本输出schema，拒绝冲突覆盖，记录原始合同SHA256。未绑定模式沿用原默认值。
- 7项测试通过，含合同阈值改变实际匹配结果、拒绝错误协议/非有限阈值/错误输出，以及既有CLI/匹配测试。实际Windows命令链绑定合成合同成功，证据 runs/events-task-bound.json 和 runs/events-task-contract.json。
- 合同文件评测字段绑定不证明会话接受状态、训练预算、视频采样或模型质量；尚未集成视频训练、能力注册和安装包重建。完整上线目标仍未完成。
## 当前代码整体回归与隔离安装（2026-10-10）

- 产品源码版本5665bd11d29545673545d821d941f622d6cf295b，源码全量354项测试通过（118.454秒），日志 runs/release-current-full-tests.log。
- 当前wheel SHA256为4fc7fb4d094b239112c81b27d982121d8dfd47338be35f2b3e0b4a915ccaa2fb，文件 runs/release-current/wheelhouse/vision_rsi_agent-0.1.0.dev1-py3-none-any.whl。新venv离线按哈希安装依赖、安装本包、pip check通过。
- 仓库外实际导入site-packages，所有Python/HTML文件集合及SHA与当前源码一致，控制器identity为source-sha256:3ddeed2090fcb5a035041bf146bbc02f5c064343c6344898295c7712dc1a03ca。161项安装回归及5个模块CLI帮助入口通过，含新增readiness、事件评测、checkpoint恢复和批处理。
- 首轮安装回归发现两个批处理测试的相对样例路径错误，已改为基于__file__定位并重跑161项通过；原失败证据保留为installed-tests-first-failure.log及installed-evidence-first-failure.json。修正仅测试路径，不改变wheel内容。成功证据 runs/release-current/installed-evidence.json 和 installed-tests.log。
- 本轮无真实API/SSH/GPU调用。仅证明本机当前Windows/Python安装与回归；不证明新机器兼容性、真实训练/恢复、COCO AP60、视频训练/推理或研究策略提升，完整上线门槛仍未完成。
## 内层实验规划请求快照（2026-10-10）

- propose_next 在API调用前的reserved账本记录中保存完整规划消息、max_tokens、剩余GPU小时快照及哈希，响应后导出request.json。缓存重放保留原快照并检查哈希，不自动补全旧记录。
- 41项实验规划/campaign/未发送请求测试通过（4.875秒）。新增测试在mock complete内部读取SQLite，确认调用前已持久化；重放字节一致且仅一次调用，篡改快照拒绝且不再次调用。
- 本轮无真实API/SSH/GPU调用。快照不含凭证，不是HTTP wire payload、计费证明或研究效率提升证明；同机操作者同时改写账本与哈希不受防护。执行额度仍实时检查。上一轮已验证wheel不包含本次产品变更，尚未重建；完整上线目标仍未完成。
## 规划请求只读CLI（2026-10-10）

- 新增experiment-request --store --request-id，默认摘要、--messages展开原始消息与回复，以SQLite mode=ro读取。记录状态/父实验/快照哈希/预算快照及回复哈希；不确定请求可观测但不自动重发，旧记录缺失快照不伪造。
- 25项观测/实验规划测试通过（.757秒），覆盖查询前后数据库字节不变、未知store不创建目录、未知ID/篡改拒绝、reserved和旧记录、真实子进程CLI。首次测试fixture未关闭SQLite导致Windows清理失败，已显式closing并重跑通过，产品读取端原本即使用closing。
- 无真实API/SSH/GPU调用，安装包探针已加入此入口与测试但尚未重建运行。命令不证明计费、外部真实性或模型效果；完整上线目标仍未完成。
## 实际DeepSeek规划快照与观测链路（2026-10-10）

- 扩展显式--live的live_method_feedback_probe.py，预登记快照验证和只读CLI一致性门槛，独立usage账本硬上限1次；合成AP42/预算fixture不改变用户实际训练授权。
- 真实deepseek-flash单次请求成功，读取mock编译拒绝反馈后输出方案通过冻结约束编译；缓存重放未创建API客户端。provider报告prompt1281/completion309/total1590 tokens，1次responded、无未知Token，额度剩0；不证明实际计费。
- request_snapshot_sha256=e1c0a1e4de55dd2daa665e45f30c27dd46a19f9d0eaabfd197ee69c577687b33，快照消息确实含synthetic-rejection反馈；独立CLI子进程输出与库查询完全一致，查询前后SQLite字节相同。Windows vision-rsi.cmd摘要入口另实际通过。
- 证据 runs/method-feedback-live/668aab947b354a02a814081c71570f5b/ 下preregistered.json、evidence.json、observation.json及research请求快照/回复/方案。
- 仅一次合成开发案例，无SSH/GPU/训练，不证明真实任务效果、跨案例稳定性或同预算RSI效率提升；安装包未包含最新快照/观测实现。完整上线目标仍未完成。
## 成对RSI实验观测成本（2026-10-10）

- study compare 每个核验实验对加入resource_comparison，展示GPU小时、动作耗时、实验规划Token的两臂值与candidate-minus-baseline差值。完整性标记不真/非有限/负值/bool/非整数Token保持null；Token范围缺失或不一致标记不完整。
- 17项成本/paired-study/campaign-audit测试通过（.830秒）；补充集成断言确认缺成本的AP比较不会误标成本完整。观测比较与AP完整性分别显示，不自动推断公平预算、效率提升或采用候选。
- 本轮仅mock及本地逻辑，无真实API/SSH/GPU/训练。成本范围不含全部CPU/项目总费用/需求与候选生成；安装包尚未重建，真实同预算研究提升及完整上线仍未证明。
## 自然语言需求与事件验收协议衔接（2026-10-10）

- clarification prompt加入独立video_events评测说明，明确事件micro-F1/0..1、时间IoU最大数量匹配、events输出与额外iou_threshold字段；要求只在语义匹配/接受该协议时选用，保留用户已有指标，不发明F1目标，不声称视频训练可用。
- issues对精确event_micro_f1/v1协议提前校验metric/direction、有限0..1目标、显式0<IoU<=1及events输出属性，错误properties类型返回问题而非崩溃。其它协议不自动转换。
- 29项contracts/event_eval/training_shell/task_adapters测试通过（.576秒），含mock澄清消息、非法验收字段和无效schema。无真实API/SSH/GPU调用，视频训练适配器和质量证据仍缺失，安装包尚未重建，完整上线目标未完成。
## 实际任务就绪复核与可执行下一步（2026-10-10）

- 实际session df8e8f8991ee496d859e35fab2085d8f v5当前COCO适配器/本地配置检查通过，训练账本0记录，真实gpu_hours仍null；未启动训练，等待用户指定上限。
- readiness新增suggested_actions结构化argv、原因、用户值要求及executed=false。缺预算且任务可实现/无待审或不确定请求时提供budget占位命令；已有预算且全部条件满足才提供prepare；未结算预留提供runs查询，阻塞任务提供show。保留自定义sessions/run-store/config路径，不执行建议。
- 10项readiness/shell测试通过（.215秒），实际Windows命令显示正确会话的budget/show下一步。首次回归暴露新增函数内import遮蔽全局subprocess造成异常路径错误，已移除局部import并重跑通过。
- 只读本地检查，无API/SSH/GPU；配置可用不证明远端实时状态、任务效果或上线。真实预算缺失与完整上线门槛仍未解决。
## CLI顶层任务入口（2026-10-10）

- 修正顶层无参数/-h/--help仍由早期mock runner提供说明的问题，展示实际training start/list/readiness/watch、单样本/批量test、预算和注册前提，列出实际工具入口并说明通用训练范围尚不完整。training无动作显示新任务CLI帮助；旧training --task入口保持兼容。
- 11项CLI帮助/任务shell/启动路径测试通过（.957秒），Windows vision-rsi.cmd --help实际成功。无配置读取、API/SSH/GPU或任务状态修改。安装包探针加入新CLI测试但未重建；完整上线目标仍未完成。
## 独立接口包事件需求校验修复（2026-10-10）

- 隔离Python -I进程复现：抽取contracts函数的interface_runtime.issues因新增event_eval相对导入失败；原check只校验示例未覆盖此调用。移除抽取校验的包内运行时依赖，协议常量/有限单位区间检查随校验函数冻结，测试确认常量与评测器一致。
- 28项contracts/harness/executable_harness/event_eval测试通过（5.316秒）。新增隔离进程直接调用导出包issues，验证普通合同及事件合同通过、缺IoU拒绝，且未导入vision_rsi；安装包探针加入harness测试并修正其样例路径。
- 原已生成接口包保持冻结内容，不自动篡改更新；需在新输出目录重新build以获得修复。无真实API/SSH/GPU/模型训练，安装包未重建，完整上线目标未完成。
## 接口包按运行时代码版本重建（2026-10-10）

- 修复纯接口harness仅按合同命名导致代码更新后复用旧运行时的问题：format_version=2身份绑定task/session/contract版本、合同hash及三个实际文件hash，目录由bundle ID派生，字节写入避免平台换行改变身份。
- 重用时核对完整身份/metadata/artifact，独立包入口也核对manifest与identity一致。代码变化生成新包，旧包不覆盖；同合同不同session分包。已存在旧格式包不自动更改。
- 22项harness/executable_harness/contracts测试通过（5.254秒），含模拟运行时代码变化后新包/复用、旧包字节不变、不同session隔离、篡改session元数据构建与独立入口拒绝。首次模拟把注释放在抽取片段外未改变运行时代码，测试修正为片段内变更后通过。
- 无API/SSH/GPU/模型训练，身份哈希不防同机整体重写，安装包尚未重建，完整上线目标仍未完成。
## 实际任务v5独立接口包验证（2026-10-10）

- 新增tests/task_bundle_probe.py，显式session-id，用公开training build --offline --json命令导出实际任务，在独立临时cwd及Python -I进程运行check、输入/输出示例校验、非法输出拒绝和infer无模型阻塞五项预登记检查；重复build验证同bundle复用，会话数据库字节不变。
- 实际任务df8e8f8991ee496d859e35fab2085d8f v5全部通过。bundle ae789add6007c328e25300a9b9918c2d187af59a52b225cb0992f52a17537429；证据runs/task-bundle-probes/6a52bbc68cd34278a785d9e1ad844710/{preregistered.json,results.json,evidence.json}，包位于其bundles/my-vision-task-v5-ae789add6007。
- 示例仅合同数据，无模型输出或质量证明。本轮无API/SSH/GPU/训练，保持实际预算未设置，未注册能力，完整上线门槛仍未完成。
## 0.1.0.dev2 当前交付包验证（2026-10-10）

- 当前产品源码91bf8cb3179d52a09bccfd395e4d36402de144a6，版本0.1.0.dev2。包含事件合同、规划快照/观测、成本比较、就绪建议、CLI入口和接口包代码身份修复；与旧dev1包明确区分。
- 源码全量370项测试通过（125.635秒），日志runs/release-dev2-full-tests.log。
- wheel为runs/release-dev2/wheelhouse/vision_rsi_agent-0.1.0.dev2-py3-none-any.whl，SHA256=9adbca68974a90f6fdcfe1d82bd64650e925790f7e651b33233b197821e57743。新venv使用离线wheelhouse和依赖哈希锁安装、pip check通过。
- 仓库外site-packages导入验证全部Python/HTML文件集合及SHA一致、发行版本精确匹配dev2。176项安装回归及6个模块CLI入口通过（18.197秒），证据runs/release-dev2/{installed-evidence.json,installed-tests.log}。安装身份source-sha256:160debbc2c5d9135ee09aafbf17d6c97845a7a867aafc1cc6fd77328d0ee4f3e。
- 探针新增可选--expected-version并记录实际发行版本，修正README当前版本说明。测试和文档变更不改变上述wheel产品代码。
- 本轮无真实API/SSH/GPU调用，仅本机Windows/Python环境交付验证。真实GPU预算仍未给出，真实训练、AP60、视频训练/推理及可验证RSI效率提升未完成；dev2不是正式上线认证。
## CPU单进程数值断点恢复探针（2026-10-10）

- 提取生产epoch_batches迭代器，保持原DistributedSampler seed/epoch、DataLoader私有generator、num_workers=0和cursor跳过语义；生产训练与探针共用函数。没有新增数据随机增强。
- 显式--live-remote的tests/live_cpu_resume_probe.py实际SSH执行Torch2.6.0+cu124 CPU fixture，CUDA_VISIBLE_DEVICES为空。17样本/批2/3epoch共27step，Linear/Dropout/SGD(momentum.9)模型在step1/8/9/10/26/27真实序列化checkpoint后重建恢复，全部loss/batch trace、模型张量、动量buffer、最终CPU RNG逐值完全一致。
- 生产迭代器source SHA256=42c6cf1afe40af5af752f7dc7c20a9dd537e4c2dec13c098527c30b6b6701ef2；证据runs/resource-bootstrap/cpu-numerical-resume-1dd0eb2075d04423960b46af51972f8c/{preregistered.json,stdout.txt,stderr.txt,evidence.json}。数据/checkpoint仅内存fixture，不修改用户远端数据或训练预算。
- 此证据仅单进程CPU合成数值恢复，不覆盖实际检测器、CUDA RNG、8卡DDP/NCCL、信号终止或真实COCO效果。本轮无LLM/GPU调用，安装dev2 wheel早于此次迭代器提取，完整上线目标仍未完成。
## 两进程CPU/Gloo数值恢复（2026-10-10）

- live_cpu_resume_probe.py新增显式--distributed，复用同一生产epoch_batches源码，远端CUDA禁用、两进程Gloo DDP，Linear/Dropout/SGD合成数据17样本、每rank批2、3epoch15step。各rank RNG收集、rank0 checkpoint序列化广播、重建DDP后按rank恢复CPU RNG。
- 实际step1/4/5/6/14/15共6种断点、2rank全部loss/batch trace、模型张量、动量buffer、最终CPU RNG与连续运行完全一致。Torch2.6.0+cu124，生产迭代器SHA42c6cf1afe40af5af752f7dc7c20a9dd537e4c2dec13c098527c30b6b6701ef2。
- 证据runs/resource-bootstrap/cpu-numerical-resume-92a12c52d40d4bd484233cac0c8459d5/{preregistered.json,stdout.txt,stderr.txt,evidence.json}；远端临时rendezvous正常清理，fixture数据及checkpoint仅进程内存。
- 仅两进程CPU对象重建恢复，未杀进程，不证明实际检测器/8卡CUDA/NCCL恢复或真实训练质量。无LLM/GPU调用、未修改真实任务预算，完整上线目标仍未完成。
## 固定检测器CPU数值恢复（2026-10-10）

- 新增显式--live-remote的tests/live_detector_cpu_resume_probe.py，远端50秒alarm、外层60秒timeout、CUDA禁用、CPU单线程。Faster R-CNN ResNet50 FPN v2实际加载固定预训练权重，SHA核验dd69338a24b8d7381807e247652bdc356325bcbaf1cd3e092e00e0a1a58706bf。
- 两张64x64合成图/类别1/batch2，SGD lr.0001/momentum.9/weight_decay.0001；连续2step与1step后真实序列化、重建模型/优化器、恢复CPU RNG再1step完全一致。核对4项loss、全模型parameters/buffers、momentum和CPU RNG，合计4次fixture训练step。
- 实际Torch2.6.0+cu124 CPU探针成功并正常结束。checkpoint SHA e89aab067722229248d4614fde9acce4455da96c30a579cddbc1034d6f1f3051；证据runs/resource-bootstrap/detector-cpu-resume-3fca0fdb2dd14f959d0f1e67fb366e0c/{preregistered.json,stdout.txt,stderr.txt,evidence.json}。
- 无LLM/GPU调用、未读取用户COCO数据、未改变任务预算或权重文件。此处是极小CPU检测器fixture训练，不是生产coco_train完整入口、进程死亡、CUDA/DDP/NCCL恢复或AP质量证明；完整上线目标仍未完成。
## 冻结可执行任务包事件评分入口（2026-10-10）

- executable_harness新增evaluate-events模式及ground-truth/predictions/output参数，强制包内contract绑定、任务版本及bundle身份输出，无外部阈值覆盖。输出必须新建且在冻结包外，check显示evaluation_modes。纯离线接口包不新增模型或评分实现。
- 18项executable_harness/event_eval/harness测试通过（6.764秒）；覆盖冻结IoU实际影响匹配、合同绑定、包身份、重复输出/包内输出拒绝、包字节不变、不兼容任务拒绝。补充check入口断言确认评测可用且视频训练仍不支持。
- 全部本地合成数据/独立子进程，无API/SSH/GPU/模型训练或能力注册。dev2安装包早于本次产品变更，旧冻结包需重新build，真实视频模型及完整上线门槛未完成。
## 事件评分输入与工作量边界（2026-10-10）

- 新增有界JSON读取：标注/预测各16MiB、合同4MiB，拒绝重复字段/非有限常量、超过64层嵌套。最多1000标签、每文档100000事件、每次1000000个逐样本标注×预测比较对，超限在匹配前拒绝；保留既有每样本1000事件/10000样本边界，不截断数据。
- 输出新增comparison_pairs工作量计数。协议与合格输入计分语义不变，冻结可执行包自动包含新评分模块，但旧包不自动更新。
- 30项event_eval/executable_harness/contracts测试通过（7.157秒），覆盖JSON重复/常量/深度/大小，超工作量不调用匹配函数，既有合同和冻结入口回归。无API/SSH/GPU或训练，安装dev2尚未包含此次更新，完整上线目标仍未完成。
## 新评测/观测命令的源码启动路径（2026-10-10）

- launch_agent.task_cli_paths扩展按命令限定的本地路径：evaluate-events ground-truth/predictions/contract/output，以及experiment-request store，按调用者cwd转绝对路径，保留training/test既有行为和其它命令行为，不改默认存储路径或文本参数。
- 21项launcher_paths/cli_help/experiment_observe/event_eval测试通过（2.206秒），包含实际独立子进程从外部cwd读取合成事件并写回调用者目录，以及读取带空格账本目录、前后数据库字节相同。
- 本轮只源码启动器/测试/文档变更，无API/SSH/GPU，安装模块cwd语义不变；不证明任务质量，完整上线目标仍未完成。
## 通用只读研究控制器崩溃锁恢复（2026-10-10）

- 上线缺口复核确认实际任务gpu_hours仍null、训练记录0，现有全量val基线AP46.70974265420546低于60；通用开放模型/harness适配、真实研究效率验证尚缺，不把软件探针视为上线通过。
- 发现通用research_step仍使用O_EXCL锁文件，异常进程退出后永久阻塞。改用与campaign相同的OS lease，锁文件保留但仅OS持有状态决定活跃；不自动删除其它进程的锁，不改变不确定API停止重试规则。
- 25项controller/campaign/ledger测试通过（4.844秒）。真实子进程在execute内os._exit(73)后，保留pending事件和锁文件，新控制器成功完成原动作且不调用API；活跃lease阻止第二控制器进入，事件不增加。
- 此测试只读mock工具，不证明写工具的崩溃幂等性。旧版仅文件锁的控制器须停止后再升级，不能与新版跨版本并发；无真实API/SSH/GPU，安装包未更新，完整上线目标仍未完成。
## 通用仓库研究证据绑定（2026-10-10）

- inspect_repository此前用Git HEAD标注当前工作区片段、未提供内容哈希。现明确Working-tree bytes，每文件SHA、读取前后tracked clean状态、HEAD是否变化；atomic_snapshot_verified始终false，不把两次Git检查当原子快照。
- 固定源码白名单保持，路径resolve不得越界/不得最终symlink，单文件读取≤1MiB、最多128个片段/总UTF8≤128KiB、每片段≤2500字符，跳过源和列表截断明确记录。Git查询timeout10秒，ls-files -z避免换行文件名误拆。
- 7项controller测试通过（2.246秒），含真实临时Git仓库：tracked .env内容不读取，未提交源码变化保持同HEAD但内容SHA变化且clean=false，超1MiB源码跳过；既有崩溃恢复仍通过。
- 提交2b8b1abb808bc1236ac02f01c714e5d3391e152c后实际检查本仓库成功：170 tracked files，HEAD未变、前后clean=true，17源码因边界未收入片段。证据runs/repository-observation-current.json；不是全仓库内容完整性或运行正确性证明。
- 无API/SSH/GPU/训练，安装包未重建，真实训练和完整上线门槛仍未完成。
## 通用研究规划未发送请求恢复（2026-10-10）

- research_step捕获客户端明确LLMNotDispatched，持久记录planning_not_dispatched及原request_key后重新抛出；本次不自动重试。下一次显式推进忽略该已知未发送请求的不确定阻塞，并使用新ID；其它异常或旧无回执请求保持不确定、禁止自动重发。
- 15项controller/not_dispatched测试通过（2.929秒）：先未发送再显式推进可完成，连续6次明确未发送仍累计规划尝试，第7次推进不调用客户端，既有不确定请求停止规则仍通过。
- 仅mock客户端/只读工具，无实际API/SSH/GPU。规划上限是此研究账本既有6次尝试，不是账户费用或全项目Token保证；安装包尚未更新，完整上线目标仍未完成。
## 通用研究源码细读动作（2026-10-10）

- 通用controller新增模型可选read_source动作，仅仓库检查成功后可选。固定源码白名单/已tracked文件，参数path/start_line/max_lines/expected_sha256严格校验；每次最多100行/16KiB，文件读取≤1MiB，哈希变化拒绝，不静默换读最新内容。结果记录行号/总行数/EOF/完整文件SHA。
- read_source可选不同区间，成功执行过的完全相同参数拒绝；仍受同账本6次规划请求上限，未开放任意路径、shell或写代码。源码hash在inspect_repository输出中前置，便于有界历史中保留身份。
- 11项controller测试通过（2.931秒），含mock模型选择动作后的执行参数、真实Git tracked文件指定行读取、错误范围/路径/hash拒绝及文件改动拒绝。补充成功区间重复提议被拒绝、工具不重复执行的断言。
- 本轮无实际API/SSH/GPU；扩大只读研究能力不等于实现通用模型/harness修改或真实RSI效率提升，安装包未更新，完整上线目标仍未完成。
## 源码细读真实调用暴露的集成缺口（2026-10-10）

- 新增显式--live的tests/live_source_research_probe.py，真实本地仓库检查后预登记一次DeepSeek调用，目标固定controller.py第31行起20行，独立API账本上限1，不重试语义失败。
- 首次在API调用前发现实际仓库观察超Ledger 100000字符事件上限（runs/source-research-live/7cc659fd9b334308b04a9edbcbeae739）；当时未发API。修正inspect_repository最终序列化≤90000字符，为事件包装预留空间，按序省略片段/列表并明确报告省略/截断，完整文件hash尽量保留。
- 随后真实调用一次responded，prompt4737/completion155/total4892 reported tokens，额度剩0。模型选择read_source但返回JSON漏arguments，被协议校验拒绝，工具未执行，没有自动重试。证据runs/source-research-live/14201a53de0b42a6a176949ba3b7479a/{preregistered.json,evidence.json,research/research.sqlite3}；probe失败类型StopIteration来自未产生工具result，原规划响应/拒绝记录保留。
- 修正planner返回schema显式列出arguments四字段及read_source必需规则。11项controller测试通过（3.716秒），含大仓库观察可写入账本、模型收到完整参数schema。测试fixture曾漏objective/误用result事件，已纠正为合法evidence后重跑通过。
- 修正后的提示尚未再次真实调用，不把mock通过替代真实工具链成功。无SSH/GPU/训练，完整上线目标仍未完成。
## 研究上下文保留源码身份（2026-10-10）

- 修正参数schema后使用新独立上限1探针真实调用，仍未通过：模型选择read_source并提供path/range，但expected_sha256为空，协议拒绝、未执行工具、无自动重试。证据runs/source-research-live/55affeee5e02438a84af6160b6e5d78c/，reported prompt4821/completion162/total4983 tokens、1次responded。
- 定位真实根因：Ledger按key排序JSON，历史把完整observation转str截前10000字符时，source_excerpts先占满，后面的source_sha256丢失；单纯调整原dict插入顺序无效。
- 新增结构化observation_context：仓库观察优先保留至多64个源码hash及少量片段，明确总数/收入数/截断标记和完整观察digest，约束投影≤9000字符。源码行读取保留path/hash/行号/EOF，片段截断另标；其它观察采用显式文本投影与digest，原始账本不删。
- 12项controller测试通过（3.578秒），覆盖JSON排序回读后的hash保留、50K片段情况下实际模型提示仍含controller源码hash、128源码索引有界投影。测试fixture曾超过账本100K上限，调为50K后通过。投影修正尚未再次真实调用，不能宣称真实链路成功。
- 无SSH/GPU/训练，安装包未更新，真实训练/通用修改/RSI效果及完整上线门槛仍未完成。

## 真实源码研究链路与 dev3 回归（2026-10-10）

- 结构化上下文修复后，新独立探针 runs/source-research-live/2812b3c371014dc38f876c77a1948318/evidence.json 通过：真实 DeepSeek Flash 选择 read_source，携带仓库观察中的完整 SHA256，读取 controller.py 第31至50行，结果逐字匹配源码。1次 responded，reported prompt4489/completion186/total4675 tokens，独立调用额度剩0，无语义重试；此前失败记录原样保留。
- 此次只读源码身份为2f0d442f4ffcd0f8e9c98939d073c54c2e2b7eedc8ed2cbe284951e257bb4276，不证明自主研究质量、真实训练或RSI提升。无SSH/GPU。
- 当前产品代码完整回归384项通过（129.292秒），日志 runs/current-full-tests.log。开发版本更新为0.1.0.dev3，包含dev2之后的源码研究、事件评测和恢复改动。
- 新wheel runs/release-dev3/wheelhouse/vision_rsi_agent-0.1.0.dev3-py3-none-any.whl，SHA256=9a607d1aced6165df8b3d5d565f116e109a14e10bd23c8e120a093ee01f3b21d。新venv使用本地wheelhouse与哈希依赖锁离线安装，pip check通过；仓库外安装包回归尚待完成。
- GPU预算仍未设置，未启动真实COCO训练；完整上线目标尚未完成。
- dev3仓库外安装包验证已完成：192项测试通过，6个模块CLI帮助入口通过，安装文件集合及每个Python/HTML文件SHA与源码一致；证据 runs/release-dev3/installed-evidence.json 和 installed-tests.log。源码提交 f11edcd195b3e8371ff42bcb4ca7b85d74e0bcb9，安装控制器身份 source-sha256:bc6245be94709e18f3df4c698ea84f3a5796f15a56d442a60214f31c93257aa1。无API/SSH/GPU；不代表新机器验收或COCO质量达标。

## 结构化研究复盘（2026-10-10）

- 通用research controller的synthesize不再只返回固定limitation：现在要求findings、limitations、next_steps并持久保存至结果观察，每条finding必须引用成功完成且有结构化观察的工具result。目标、动作、失败/不存在的结果和已有模型解释不能作为finding引用。
- 列表、文本和引用均有长度边界；规划阶段与pending恢复执行阶段均重新检查证据。interpretation_only=true、experiment_executed=false，不把引用合法等同结论正确。旧无参数synthesis动作恢复将记录失败，不伪造历史报告。
- 24项controller/controller_budget/ledger测试通过（5.599秒），覆盖结构化报告持久化、目标引用拒绝且工具未执行、自引解释拒绝、源码细读和原有恢复。首次回归因提示缺少既有REQUIRED约定失败，恢复该约定后通过。
- 无真实API/SSH/GPU；最新dev3安装包仍对应f11edcd源码，不包含此次报告扩展。真实COCO训练、通用harness修改与RSI效果及完整上线目标仍未完成。

## 结构化研究报告真实调用验证（2026-10-10）

- 扩展显式--live探针的--synthesis模式：实际检查本仓库，预登记独立API上限1，要求synthesize；核验findings引用inspect:result、报告字段持久保存、interpretation_only=true、experiment_executed=false，无语义重试。修正原源码探针在规划拒绝时的StopIteration，改为明确未生成工具结果的AssertionError。
- 实际一次DeepSeek Flash调用通过上述机械协议检查：4条发现，reported prompt4592/completion970/total5562 tokens，额度剩0。原始证据 runs/source-research-live/2d8ef3064ecf41598f7744d521a844e8/{preregistered.json,evidence.json,report.json,research/research.sqlite3}；另从原始输出生成可读report.md。
- 不将passed等同研究内容正确：模型将original_excerpt_count描述为非空片段，计数语义未独立核对；引用有效只证明记录存在。evidence原scope沿用旧source-range措辞，已修改探针后续输出按模式区分，未改写这次原始记录。无SSH/GPU/训练，安装包未更新，完整上线目标未完成。

## 通用研究请求快照（2026-10-10）

- 研究规划现在在调用前持久保存实际messages/model/max_tokens/stream及thinking设置和request_snapshot_sha256，发送内容与账本快照相同；不保存API Key或连接配置。历史请求不回填虚构快照。
- 请求快照序列化限制90000字符，为Ledger事件预留空间；超限时移除最早历史投影并明确original/included/omitted计数，目标原样保留。目标本身过大则在请求事件/API调用前拒绝，避免产生假的不确定请求。原始历史事件保持不变。
- 32项controller/controller_budget/ledger/not_dispatched测试通过（6.190秒）：API mock执行时已能读到完整快照，快照SHA匹配，长历史有界，95K目标在预留前拒绝，既有恢复/不确定请求停止规则保持。无实际API/SSH/GPU，安装包未更新，真实训练和完整上线目标仍未完成。

## 通用研究控制器连接隔离代码候选（2026-10-10）

- 新增stage_candidate动作，配置research.allow_candidate_writes=true时开放，默认关闭；成功仓库检查后才可用，提案必须引用同Git基线结果。沿用Candidates的strategy/harness/adapter源码范围、语法及base_sha检查，不开放主仓库任意写入。
- 候选写入研究目录/candidates，绑定持久动作ID及目标SHA；执行时重核主仓库tracked clean和HEAD，Candidates.create按内容身份复用。结果标read_only=false、code_executed=false、adopted=false，不将语法检查称为行为验收。允许不同提案继续研究，完全相同成功提案拒绝，仍受原6次规划上限。
- 33项controller/controller_budget/ledger/not_dispatched测试通过（9.173秒），真实临时Git创建/提交/父提交核查/重复恢复通过，提案顶层raise未被执行，主仓库文件与HEAD未改变。LLM为mock，未调用真实API/SSH/GPU；尚未把远端沙箱检查接入此控制器，未声称完整代码RSI闭环或上线完成。
- 更新配置示例、README及应用目标能力说明。安装包未重建，真实训练和质量验证仍待完成。

## 通用研究控制器连接候选CPU沙箱（2026-10-10）

- 新增check_candidate动作，allow_candidate_checks显式开启后才开放；只接受同研究账本stage_candidate成功结果中的候选，规划/恢复阶段重核绑定。模块函数与1..16个keyword用例复用既有候选runtime校验，研究请求另限12000字符。
- 通过Candidates.check调用现有远端CPU沙箱；原始检查报告保留，研究账本记录runtime_status、报告路径/digest及有界response投影。质量验证/采用始终false，模型开发用例不能替代独立验收。
- 稳定check ID绑定目标SHA与完整候选/模块/函数/用例参数，跨新动作也复用已完成收据，已有reserved不确定检查拒绝重发；每轮新的开发用例可继续观察。未接入GPU训练或自动采用。
- 33项controller/controller_budget/ledger/not_dispatched测试通过（10.614秒），包含真实临时Git候选通过mock远端运输写回账本、同动作/新动作相同检查只调用一次运输、其它候选ID拒绝。此轮未实际调用SSH/LLM/GPU，不能声称新的控制器链真实沙箱已通过。配置/文档/应用能力说明同步，安装包未重建；完整上线目标未完成。

## 研究候选真实远端CPU链路（2026-10-10）

- 新增tests/live_research_candidate_probe.py --live-remote：固定非LLM开发候选，由research_step恢复预写stage/check动作；禁止任何规划API调用。候选绑定实际仓库检查基线，独立Git提交；实际SSH调用现有CPU沙箱。
- 真实探针通过，证据 runs/research-candidate-live/fcafdb462f674c2facb18d3815d8345a/{preregistered.json,evidence.json,controller-result.json,research/research.sqlite3}；候选原始检查报告在该研究目录/candidates下。输入1/3返回2/6，实际候选进程uid65534；返回运行限制gpu=false、network=false。未重新攻击验证全部隔离边界。
- 相同检查改用另一action绑定，禁止远端运输调用后仍成功复用报告且digest相同。真实远端失败反馈、模型自主提案选择、真实训练与RSI效果不在本探针范围；未调用LLM/GPU，未采用候选。安装包未更新，完整上线目标未完成。

## 真实失败反馈与修复探针暴露的协议缺口（2026-10-10）

- 为stage_candidate结果保留base_revision与source_edits，模型上下文结构化投影最多两文件/每文件3000字符、整体约9000字符，并标明截断；原始提案不截断。34项controller/controller_budget/ledger/not_dispatched测试通过（10.431秒），含源码可见性。
- 新增显式tests/live_research_repair_probe.py --live，预登记固定整数/字典输入、最多1次修正API、实际CPU检查且无GPU。首次实际运行 runs/research-repair-live/442c9a1b8ce047ae8ab946fbc549a68b 失败：初始沙箱确实因dict*int报TypeError；DeepSeek返回修复源码但外层JSON缺少闭合括号，JSONDecodeError拒绝，未创建/执行修复候选。reported prompt6239/completion504/total6743 tokens，1次responded，额度剩0，无语义重试。所有原始响应与快照保留。
- 另发现响应refs未包含主仓库检查结果，即使JSON有效也会被基线引用门槛拒绝；提示现显式要求引用git_revision等于base_revision的inspect_repository结果。原检查不放宽。
- 客户端新增可选llm.response_format=json_object并在调用前校验，发送response_format对象，研究请求快照同步记录；默认配置不改变，不自动回退或修补无效JSON。修复探针后续显式使用此选项，其实际服务支持尚未再次验证。本轮不增加第二次API。
- 本轮真实失败不等于修复闭环通过；未训练/未采用/未证明RSI提升，安装包未更新，完整上线目标未完成。
- JSON选项及研究控制器/未发送规则39项测试通过（11.298秒），覆盖HTTP载荷、无效选项发送前拒绝和请求快照记录一致。未声称服务端JSON格式保证已验证。

## JSON模式真实修复提案的字段歧义（2026-10-10）

- 新独立上限1探针 runs/research-repair-live/631df81e222641e780fc7ab4331b6478 实际调用JSON模式：服务接收并返回合法JSON，reported prompt6303/completion530/total6833 tokens。初始CPU字典输入TypeError再次确认。
- 修复闭环仍未通过：响应将修复参数放到candidate_arguments而非arguments，协议ValueError拒绝，未创建/执行修复候选、无自动重试。实际模型源码看似修复不能替代执行结果。
- 根因是planner schema把不同工具示例分别命名candidate_arguments/synthesis_arguments/check_arguments，模型复制了示例字段。现统一顶层arguments，通过tool_argument_shapes按真实工具名描述其内容，显式禁止替代字段；不接受错误字段别名、不自动改写原响应。前两次失败证据保持。
- 增加实际提示schema断言，不把提示改动当真实闭环通过。本轮无GPU、未训练/采用、安装包未更新，完整上线目标未完成。
- 39项controller/llm/not_dispatched回归通过（11.405秒）；修正后的统一参数提示尚未再次真实调用。

## 真实CPU失败→一次模型修复→复测通过（2026-10-10）

- 统一arguments提示后，新独立上限1探针通过：runs/research-repair-live/564b2ff507cb4c9cabff0d03129075cd/{preregistered.json,evidence.json,research/research.sqlite3}。真实DeepSeek Flash JSON模式一次responded，reported prompt6361/completion555/total6916 tokens，额度剩0，无语义重试。
- 初始候选7fba5aa08527a186cc4b2d36ced8e0fea7cbdbe7e0b2c79a42e2597b1f04d332实际CPU沙箱dict*int报TypeError；模型看到源码/失败结果后提出独立候选d1bfd68f14307264ca7f1c3de3cc45a736a07b34ebc754b640c73bad7b019417，predict增加dict取value键分支。控制器创建独立Git候选，原定输入1和{"value":3}复测输出value2/6、uid65534，原用例未改。
- 这是固定公开开发用例的真实反馈修正联调，不是独立保留质量或同预算RSI效率提升证明；设置/复测动作由固定探针安排，不能称全流程自主选择。无GPU/训练，候选未采用，前两次失败证据保留。
- 移除observatory中早期Demo固定COCO阻塞/GPU成本文字，改为明确需查看所选账本结果与审计；从原始成功账本重新生成观测页。3项ledger测试通过（0.124秒）。安装包未更新，完整上线目标未完成。

## 候选验证连接固定任务合同（2026-10-10）

- 新增check_contract研究动作：配置research.task_contract={path,sha256}且开启候选检查时可用。合同由本地配置固定原始文件SHA、读取≤512KiB；规划前和执行前重核，模型参数只含候选/模块/函数/样本，不接受合同覆盖。
- 输入样本与输出schema复用Candidates.check_adapter，1..16样本且研究参数≤12000字符，候选仍须属于本研究stage结果。结果区分adapter_contract_passed/failed，保留合同SHA、失败条目、原始adapter报告及有界响应；quality_verified/adopted始终false。
- 稳定检查身份额外绑定合同SHA；普通check_candidate旧ID算法保持，避免升级后重复发送历史检查。接口检查开发样本不构成独立任务质量或RSI验收。
- 34项controller/controller_budget/ledger/not_dispatched测试通过（12.193秒）：真实临时Git候选、mock运输下合规输出通过/负时间戳输出失败、合同改动发送前拒绝。未实际调用LLM/SSH/GPU，新的合同控制器链真实执行待验证；安装包未重建，完整上线目标仍未完成。

## 固定合同候选真实CPU验证（2026-10-10）

- 扩展tests/live_research_candidate_probe.py --live-remote --contract，使用examples/interface-contract.json的原始SHA固定接口，预设适配器返回符合/违反schema的输出；不读取图片或视频URI，不声称媒体模型推理。
- 首次 runs/research-candidate-live/9dd5352eed4a431b9c5040f55591fc7b 因探针tracked修改未提交，被stage候选clean门槛拒绝，未发SSH；原evidence沿用remote_requested=true措辞表示意图而非已调用，后续改为remote_allowed，原记录不改写。
- 提交bc8ced6后真实探针通过：runs/research-candidate-live/dfadd9649f2d4ae1b92013db00e69ac9/{preregistered.json,evidence.json,controller-result.json,rejected-output.json,research/research.sqlite3}。实际CPU沙箱合规输出adapter_contract_passed，负start_seconds输出adapter_contract_failed；同目标/候选/样本另动作绑定恢复，在禁止运输调用时复用原报告digest。
- 此轮无LLM/GPU，未训练/采用，不证明视觉效果或同预算RSI提升。安装包未更新，完整上线目标未完成。

## Training会话绑定通用研究入口（2026-10-10）

- 新增training research-init/research-step与task_research模块：只读Sessions读取已定义、无pending/review的任务，固定session/task/version/contract及需求turns摘要身份；研究目录独立导出原始字节固定的contract.json，目标不覆盖。需求/版本改变或冻结文件篡改/缺失拒绝，需新研究root。
- 第一次规划就携带完整固定任务接口，无需等待候选创建；保留原配置中的候选写入/检查权限。研究入口不启动GPU训练或注册能力，训练预算门槛保持。新增显式--repository、--research-root及源launcher调用者路径处理，README给出命令。
- 实际现有COCO会话df8e8f8991ee496d859e35fab2085d8f初始化成功，任务my-vision-task、接口v5、合同内容digest b434c6a2ead7c32f6ae8cd8fb9d6533f16e8754bcadad7627327c23d8821620e，导出原始文件SHA e97395b4f3bbee24130f065c2bfead78bdfe995f00e8897991771c05be2fe4fb；会话SQLite前后哈希相同。目录runs/task-research/该session，未调用API/SSH/GPU。
- 34项task_research/training_shell/cli_help/launcher_paths/controller测试通过（12.014秒），含幂等/需求和文件变化拒绝、首请求完整接口。首次命令误用不存在的test_launch_agent导致loader失败，更正为test_launcher_paths后重跑通过。测试fixture改用相对测试文件的绝对路径，避免仓库外安装验证依赖cwd；安装验证清单加入新模块，尚未重建安装包。
- 完整训练→真实效果达标→注册→推理及同预算RSI采用验收仍未完成。

## 现有COCO任务真实研究CLI推进与dev4准备（2026-10-10）

- tests/live_task_research_probe.py对现有会话df8e8f8991ee496d859e35fab2085d8f调用真实training research-step CLI，独立API上限1，候选写入/检查关闭，固定合同从会话研究目录自动带入。
- 实际通过：runs/task-research-live/81fe5c73c78e489f8922f5afe50b401d/{preregistered.json,evidence.json,cli-output.txt}，原始请求/响应在runs/task-research/该session/research.sqlite3。DeepSeek选择inspect_repository并完成，实际请求快照含精确导出合同及SHA，会话SQLite哈希不变。1次responded，reported prompt2123/completion191/total2314 tokens，额度剩0；无SSH/GPU/训练。
- 此证据证明会话→CLI→真实规划→本地只读工具→账本衔接，不证明长期研究质量或视觉指标达标。开发版本更新0.1.0.dev4，包含dev3之后研究候选/合同/CLI改动；安装验证待完成。

## dev4开发安装包完整验证（2026-10-10）

- 源码0b71a814245ca21849b541bab0c4398a4f88f72d完整回归394项通过（140.499秒），日志runs/dev4-full-tests.log。wheel runs/release-dev4/wheelhouse/vision_rsi_agent-0.1.0.dev4-py3-none-any.whl，SHA256=103701a781f49c930283a3ef3f8f126cbad57284c5e476b298617b24fe11671a。
- 新venv按本地wheelhouse和Windows依赖哈希清单离线安装，pip check通过。仓库外201项安装测试通过（30.749秒），6个模块CLI帮助入口通过，安装Python/HTML文件集合及各文件SHA与源码完全一致。证据runs/release-dev4/{installed-evidence.json,installed-tests.log}；控制器身份source-sha256:db6f9f7ac93a49d7e4cbde1258a12d4373f452790f525fd4ee68a795c1aff955。
- 另在F盘根目录用安装venv的python -m vision_rsi training research-init，显式指向原会话/研究根，成功读取task my-vision-task/v5并复用原研究。未调用API/SSH/GPU；不声称新机器认证、真实训练或上线质量门槛完成。

## 任务研究规划接收真实本地执行前提（2026-10-10）

- 核查候选→test发布路径：COCO注册仍要求训练验收与服务端独立效果验收，研究接口检查不会绕过该门槛。当前无已验证COCO能力，完整链路未完成。
- training research-step现在在模型调用前执行现有只读task_readiness，带入授权GPU预算/剩余快照/记录数/未结算运行/支持范围/阻塞与建议；task_research核对session/task/接口版本，首次/后续规划及完整请求快照均包含该上下文。保留所有真实训练门槛，不把建议动作当已执行、不把本地快照当实时远端或质量证明。
- 31项task_research/task_readiness/training_shell/controller测试通过（10.349秒）；补充实际提示含预算null/未结算ID的断言后6项task_research/task_readiness通过（0.378秒）。版本错配拒绝。
- 实际只读核查现有会话，证据runs/task-research/current-readiness.json；未调用LLM/SSH/GPU。已再次集中询问真实GPU预算但尚无答复，不设置预算、不启动训练。安装包仍是dev4旧源码，完整上线目标未完成。

## 配对研究独立API额度（2026-10-10）

- 发现两臂共享usage ledger会使先运行的一臂消耗另一臂额度，不能据此认定相同研究资源预算。spec新增显式可选llm_call_limit_per_arm，预登记每臂独立绝对路径账本与同一上限，campaign binding和step使用各臂execution_config；旧研究仍用旧pair config。
- 已配置全局usage ledger/call cap时拒绝此选项，不自动重置/扩容/复制全局授权；已有臂账本拒绝创建新研究重置。compare说明independent_per_arm或shared_or_unbounded，不声称Token/金额/CPU公平或自动采用。
- 22项paired_study/study_resources/llm_usage测试通过（1.523秒），含4个臂独立路径、执行配置精确传递、真实SQLite额度一臂耗尽另一臂可预留、旧全局预算保留及新选项冲突拒绝。首次fixture传dict给reserve导致类型失败，改为实际字节载荷后重跑通过。最后比较字段与变量命名改动未再次运行完整回归。
- 无实际API/SSH/GPU或真实配对研究，未采用候选。GPU预算仍待用户答复；安装包未更新，完整上线目标仍未完成。

## API预算数据库准入触发器完整性（2026-10-10）

- 外层配对审阅发现usage snapshot此前仅依据api_call_cap元数据称额度已执行，未检查准入触发器；UsageLedger的CREATE TRIGGER IF NOT EXISTS也会保留同名但已改写的触发器。
- 现核对规范化触发器SQL；已有额度绑定而触发器缺失/变化时构造客户端账本拒绝，不自动修复或重置。每次reserve先BEGIN IMMEDIATE，在同一事务内核验触发器后插入，防止已创建对象绕过后续改动。snapshot只读报告admission_trigger_verified，未验证时enforced=false、remaining=null。
- 41项llm_usage/llm/not_dispatched/paired_study测试通过（4.674秒）：同名空触发器与删除触发器均被拒绝、既有对象预留拒绝、账本计数保持；并发额度边界/旧预算恢复仍通过。首次fixture未关闭SQLite连接造成Windows清理失败，更正显式关闭后重跑通过。
- 只读实际历史调用账本runs/task-research-live/81fe5c73c78e489f8922f5afe50b401d/usage.sqlite3：calls1/cap1/触发器通过/remaining0，兼容旧SQL格式。无新API/SSH/GPU。SQL守卫不证明历史账本未被删改或金额账单准确；不改变RSI统计/独立性/自动采用门槛。安装包未更新，完整上线目标未完成。
