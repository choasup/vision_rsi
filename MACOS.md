# 在 macOS 上开发和运行

Mac 作为交互与控制端，通过 SSH 调度 Linux GPU 服务器。无需在 Mac 安装 CUDA 或本地训练检测器。当前提供源码入口；Windows 离线 ZIP 不能用于 macOS。本项目尚未在真实 Mac 上完成端到端验证。

## 安装源码

需要 Git、Python 3.10+（建议使用与现有开发环境一致的 Python 3.12）和 SSH 客户端。终端检查：

```sh
git --version
python3 --version
ssh -V
git clone https://github.com/choasup/vision_rsi.git
cd vision_rsi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
sh ./vision-rsi.sh --help
```

CLI 的标准依赖为空。媒体处理、COCO 复算及 GPU 训练需要对应额外依赖，不要把仅 CLI 安装成功理解为训练环境已就绪。可直接使用 `python -m vision_rsi` 或安装后的 `vision-rsi`；下面统一使用源码启动器，以保留与 Windows 相同的路径处理。

## 配置本机密钥与远端

```sh
sh ./vision-rsi.sh workspace-init --directory .
```

编辑生成的 `config.local.json`。已有配置时不要重建。默认 DeepSeek Flash；密钥仅放环境变量。zsh 中可用隐藏输入，避免把实际 Key 写进命令历史：

```sh
read -rs 'DEEPSEEK_API_KEY?DeepSeek API key: '
export DEEPSEEK_API_KEY
printf '\n'
```

该变量只在当前终端及子进程中生效。重开终端后重新设置，或使用你自己的本机密钥管理方式。不要将 Key 写进仓库。

按当前服务器信息填写配置的 `remote` 字段：

```json
{
  "ssh_host": "root@42.192.34.154",
  "ssh_port": 10820,
  "workspace": "/home/tione/notebook/choasliu/vision-rsi-agent",
  "python": "python3"
}
```

这是 `remote` 字段示意，不能代替完整配置；数据、权重路径及哈希等仍须按实际准备阶段配置。Windows 本地 `F:\...` 路径不能直接用于 Mac，应改为对应的 macOS 路径；Linux 服务器路径保留。SSH 私钥需要在 Mac 本机配置，不要复制到 Git。

```sh
ssh -p 10820 root@42.192.34.154
# 成功连接后退出远端，再执行本机检查
sh ./vision-rsi.sh doctor --config config.local.json
```

初次 SSH 连接应核对服务器指纹。`doctor` 仅做本地配置检查。下面两条才会真实访问服务，其中 LLM 检查产生 API 用量：

```sh
sh ./vision-rsi.sh remote-check --config config.local.json
sh ./vision-rsi.sh llm-check --config config.local.json
```

## 首次试用

使用新的任务代号，先体验需求交互：

```sh
sh ./vision-rsi.sh training start --task-id mac-trial --interactive --config config.local.json
```

自然语言描述目标、输入、输出和验收要求。用 `/show`、`/contract` 检查理解，`/prepare` 核对资源。确认后才显式启动训练。新任务需要明确初始 GPU 预算，不自动继承现有 COCO 会话的192 GPU小时授权。

已验收版本的推理方式与 Windows 相同：

```sh
sh ./vision-rsi.sh test --task-id TASK_ID --version VERSION --input /Users/you/data/sample.json --output /Users/you/data/result.json
sh ./vision-rsi.sh test --task-id TASK_ID --version VERSION --manifest /Users/you/data/samples.jsonl --output-dir /Users/you/data/results
```

示例 ID、版本和路径需要替换。当前没有达标的 AP≥60 COCO 发布版本。更多交互与取消操作见 [使用说明](USER_GUIDE.md)；其中 `.\vision-rsi.cmd` 在 Mac 替换为 `sh ./vision-rsi.sh`，本地路径改为 macOS 路径。

## 继续开发与现有任务迁移

```sh
git pull --ff-only
python -m unittest discover -s tests -v
```

测试可能涉及平台差异；真实 Mac 测试结果仍需实测，不承诺全套已通过。

**克隆代码不会带来已有任务记录。** `runs/`、配置、数据和权重被 Git 忽略。Mac 无法仅凭任务代号接管 Windows 上的会话和预算账本。

现有 COCO 实验仍在服务器运行，其权威控制记录目前在 Windows。当前不应在 Mac 为同一实验新建192 GPU小时预算、重复提交或同时运行第二个控制器。迁移需先停止旧控制器写入，等待/收集在途作业，完整备份会话、训练账本及依赖产物，处理冻结绝对路径与源码身份，再验证新端恢复；不能直接复制正在写入的 SQLite 文件并双端运行。

如果只想马上试用，使用上面的 `mac-trial` 新会话即可；如果要接管已有实验，应安排单独的一致性迁移。服务器常驻控制器正在规划中，尚不能通过 Mac 客户端自动接管。
