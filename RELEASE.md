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
