# COCO RSI Agent

Windows 本地研究控制器，通过 SSH 调度独立 8 卡 H20 服务器；LLM 服务独立且可替换。
当前目标暂定 COCO 目标检测 box AP。当前版本只有确定性模拟闭环，**没有真实训练、COCO 指标计算或 LLM API 调用**。

## 本地运行

需要 Python 3.10+ 和 Git；没有第三方依赖。从仓库根目录执行：

```powershell
python -m unittest discover -s tests -v
python -m coco_rsi doctor
python -m coco_rsi run --run-dir runs/demo
python -m coco_rsi run --run-dir runs/demo
```

第二次运行恢复相同结果，不重复消耗模拟预算。更改配置或提交版本后使用新 run-dir。
配置示例是模拟专用；`synthetic_box_ap` 不是检测性能，`spent_gpu_hours` 是模拟成本。
状态保存在忽略的 runs/ 中。当前单进程顺序执行，不支持多个控制器同时写同一目录。

## 配置与秘密

复制 config.example.json 到本地配置文件并填写 SSH 主机别名、远端目录、COCO 路径、准确模型 ID 和 Base URL。
API Key 仅从 DEEPSEEK_API_KEY 环境变量读取，doctor 只报告是否存在，绝不打印值。
不将密钥放入配置、Git 或聊天。远程执行和 OpenAI-compatible HTTP 适配器留待接入；当前真实模式主动报错。
检测器、预训练权重、数据划分尚未选定，不推断 DeepSeek Flash 的准确模型名或服务地址。

## 研究约束

- 首先锁定检测器、权重校验和、数据版本、训练配方和评测协议，建立可复现基线。
- 内层规划实验、修改候选代码、训练、验证、分析错误；候选代码使用独立 Git 提交记录。
- 外层比较相同 GPU、LLM token 和时间预算下旧策略与新策略的研究效率。
- 调度、成本、恢复和指标计算由确定性程序负责。远端执行须记录真实 GPU 数量乘运行时间。
- 研究反馈使用固定本地验证集；隐藏测试不参与反复搜索。
- 数据集、模型权重、训练输出、SSH 私钥和 API Key 不进入 Git；不配置远端、不推送。

详见 PLAN.md。当前记录仅包含配置哈希、Git 提交、候选和模拟结果；尚无代码修改执行器。
