# Windows 开发版安装

当前版本为 `0.1.0.dev8`。这是本机验证的开发交付包，真实模型效果、COCO AP60 和完整上线验收尚未完成。

需要 Windows x64 和 Python 3.12。离线包包含 Agent wheel 与锁定版本的控制端依赖，不包含 Python、API Key、数据集或模型权重。

1. 解压 `runs/release-dev8/vision-rsi-agent-0.1.0.dev8-windows-py312.zip` 到一个新目录。
2. 进入解压后的 `vision-rsi-agent` 目录，执行：

   ```powershell
   py -3.12 install.py
   .\vision-rsi.cmd --help
   ```

安装器先校验文件 SHA256，再创建独立虚拟环境，全程使用本地 wheel。已有虚拟环境不会被覆盖；请使用新解压目录安装。校验用于发现文件变化，不代表发布者签名认证。`.cmd` 入口不需要更改 PowerShell 脚本执行策略。

创建独立任务工作目录后，使用安装目录中 `vision-rsi.cmd` 的绝对路径调用：

```powershell
& 'F:\你的安装目录\vision-rsi-agent\vision-rsi.cmd' workspace-init --directory 'F:\你的任务工作区'
Set-Location 'F:\你的任务工作区'
& 'F:\你的安装目录\vision-rsi-agent\vision-rsi.cmd' doctor --config config.local.json
& 'F:\你的安装目录\vision-rsi-agent\vision-rsi.cmd' training --help
& 'F:\你的安装目录\vision-rsi-agent\vision-rsi.cmd' test --help
```

按任务配置本机 API 环境变量、SSH、远端目录、数据和权重路径；不要把密钥写入接口文件或 Git。`doctor` 仅检查本地配置，不证明真实服务已连通。真实训练需任务的明确 GPU 小时预算，不能由 Agent 默认授权。

训练与推理仅能使用当前实现支持的适配器。通用候选 bundle 的注册、独立验收和 CPU 服务检查不自动变为正式可调用能力；不能把合成示例或 CPU 接口检查解释为真实模型达标。详细边界及验证记录见 `RELEASE.md`。
