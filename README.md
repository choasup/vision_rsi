# Vision RSI Agent

**用自然语言定义视觉任务，让 Agent 组织实验、评估结果并迭代，最终交付可按任务代号调用的视觉能力。**

COCO 目标检测是第一个验证实验。项目面向不同视觉任务，包含单图、联合多图和视频任务的接口设计。

> **状态：开发预览版。** 已跑通真实 COCO 训练与评测闭环；通用 harness 自动组装、学习型多图/视频后端和外层 RSI 的效率提升尚未完成验证。当前不建议作为生产服务部署。

[使用说明](USER_GUIDE.md) · [安装说明](INSTALL.md) · [Demo 与证据范围](DEMO.md) · [项目计划](PLAN.md) · [开发接口参考](docs/DEVELOPMENT_REFERENCE.md)

## 两种使用模式

### Training：从需求到可验证的任务能力

你描述任务代号、目标、输入、输出和效果要求，Agent 通过自然语言反复澄清，整理并固定任务接口，再开展有预算约束的研究。

```text
我要实现 COCO 80 类目标检测，任务代号 coco-detector。
输入一张图片，输出类别、置信度和原图像素坐标的检测框。
按完整 COCO val2017 官方 box AP 验收，目标至少 60。
先整理需求和资源计划，再执行训练与迭代。
```

设计中的完整流程：

```text
需求澄清 → 冻结接口与验收要求 → 组装 harness → 实验与错误分析
                                              ↑           │
                                              └── 迭代 ───┘
                         → 独立验收 → 服务检查 → 固定版本交付
```

当前真实训练支持固定的 Faster R-CNN 检测器及有限配方搜索。任意视觉任务自动获得适用的训练和推理后端，是后续工作。

### Test：调用已验收的固定版本

使用任务代号、版本和符合合同的输入执行推理，支持单样本及批量调用。

- **单图**：一张图片构成一个任务样本。
- **联合多图**：多张图片构成一个样本，按合同联合输出一个结果。
- **视频**：一段视频构成一个样本，输出形式由任务合同定义。
- **批量**：多个独立样本组成 JSONL 清单，与联合多图不同。

这些是接口层的支持范围，实际可执行类型由已验收后端决定。目前 COCO 后端只接受单图，尚无达标的 AP≥60 COCO 发布版本。

## 快速试用

### 1. 获取源码

Windows PowerShell：

```powershell
git clone https://github.com/choasup/vision_rsi.git
cd vision_rsi
.\vision-rsi.cmd --help
```

需要本机 Python 3.10 或以上；源码启动器优先使用显式 `VISION_RSI_PYTHON`、项目 `.venv` 或本机 Codex Python，再尝试 PATH。远端训练环境另需配置 PyTorch、torchvision 和 COCO 依赖。

`.cmd` 入口不受 PowerShell 脚本执行策略限制。

### 2. 创建本地配置

首次使用且尚无配置文件时：

```powershell
.\vision-rsi.cmd workspace-init --directory .
```

编辑生成的 `config.local.json`，填写 LLM 和远端 SSH、工作目录、数据资源配置。已有配置时直接使用，初始化命令不会覆盖它。

默认 LLM 接口为 DeepSeek Flash，通过 `DEEPSEEK_API_KEY` 环境变量读取密钥。也可替换为支持当前客户端协议的 OpenAI-compatible 服务。密钥不应写进配置或提交 Git。

```powershell
.\vision-rsi.cmd doctor --config config.local.json
```

`doctor` 仅检查本地配置，不访问 API/SSH，也不证明模型达标。实验规划会将需求、指标、配方和预算提供给所配置的 LLM 服务。

### 3. 用自然语言定义任务

```powershell
.\vision-rsi.cmd training start --task-id my-vision-task --interactive --config config.local.json
```

直接输入需求，按提示补充信息。无需手写内部 schema。常用会话命令：

| 命令 | 作用 |
| --- | --- |
| `/show`、`/contract` | 查看需求摘要与完整接口 |
| `/budget N` | 明确设置初始 GPU 小时上限 |
| `/prepare` | 核查计划与远端资源，不启动训练 |
| `/run`、`/watch` | 推进执行或持续观察，会产生真实用量 |
| `/job`、`/logs` | 查询远端状态与日志 |
| `/pause` | 暂停后续决策，已有作业继续运行 |
| `/quit` | 保存并退出交互 |

建议第一次先完成需求定义和准备检查，确认理解正确后再启动训练。8 张卡运行 1 小时计为 **8 GPU 小时**；预算不会根据示例自动授权。

### 4. 观测和调用

记下会话 ID，查询已有记录：

```powershell
.\vision-rsi.cmd training list
.\vision-rsi.cmd training show --session-id SESSION_ID
.\vision-rsi.cmd training runs --session-id SESSION_ID --json
```

有已验收发布版本后，才执行 Test：

```powershell
.\vision-rsi.cmd test --task-id TASK_ID --version VERSION --input sample.json --output result.json
.\vision-rsi.cmd test --task-id TASK_ID --version VERSION --manifest samples.jsonl --output-dir results
```

`SESSION_ID`、`TASK_ID` 和 `VERSION` 均需替换为真实值。完整样本格式、恢复、取消和验收说明见 [使用说明](USER_GUIDE.md)。

## 当前验证结果

截至 2026-10-12，首个任务使用 COCO 2017，完整 val2017 共 5000 张图，以官方 bbox AP 评测：

| 实验 | box AP | 结论 |
| --- | ---: | --- |
| torchvision Faster R-CNN ResNet50 FPN v2 官方 COCO 预训练权重 | 46.7097 | 完整 CPU 基线，已独立复算 |
| 相同检测器与预训练权重，8 卡微调 1 轮 | 45.5969 | 真实完整评测，未达到目标 60 |
| 降低学习率至 0.0001，训练 2 轮 | 待评测 | 后续实验，不预设提升 |

训练完成、loss 下降和测试通过均不等于 AP 达标。当前没有证明 AP≥60，也没有证明 Agent 自身的研究策略已经通过 RSI 获得效率提升。

## 架构与 RSI

当前架构中，Windows CLI 负责交互与控制，独立 GPU 服务器执行训练和评测，LLM 通过独立服务提供规划。已提交的远端训练可独立运行，本地持续决策仍依赖控制进程存活。

计划将控制器迁为服务器常驻服务，Windows 保留任务提交和观测入口。该改造尚未完成，不能把当前实现当作已部署的长程服务。

项目将两层迭代分开：

- **内层研究**：选择实验、调整代码或配方、训练、评测与错误分析。
- **外层 RSI**：改进 Agent 的实验选择策略、记忆与工具，通过独立、同预算比较决定是否采用。

现有外层研究程序不等于已经验证 RSI 成功。效果结论需要实际对照证据。

关键执行约束：

- 调度、预算准入、断点恢复和指标计算由确定性程序负责。
- 使用 Git、冻结源码与结构化账本追踪实验和候选。
- 保留不确定请求，不因观察超时自动重复提交。
- 将开发反馈和独立验收分开，隐藏测试不作为反复搜索反馈。
- 密钥、数据集、权重与训练输出不纳入源码仓库。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [USER_GUIDE.md](USER_GUIDE.md) | 首次试用、自然语言 training、观测、取消与 Test |
| [INSTALL.md](INSTALL.md) | 安装与离线开发包说明；包版本可能落后于源码 |
| [DEMO.md](DEMO.md) | 可复查 Demo 及其证据边界 |
| [PLAN.md](PLAN.md) | 实施计划、历史记录和未完成项 |
| [开发接口参考](docs/DEVELOPMENT_REFERENCE.md) | 候选交付、研究账本、评测及底层开发命令 |

源码包中的 `run`、`demo` 等历史入口可能使用合成数据；其结果不代表真实视觉性能。详细参考文档保留了历史阶段说明，最新使用入口以本 README 和使用说明为准。
