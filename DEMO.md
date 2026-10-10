# 真实远端 CPU 执行链路 Demo

2026-10-11 在当前源码完成。此 Demo 使用固定事件输出的开发用例，不是训练后的视觉模型，不验证视频理解、COCO AP60 或 RSI 效率。视频只是未经解码的传输用例。真实模型训练预算仍未授权。

已跑通：已冻结任务接口 → 实际 CPU 开发评测 → 暂停并封存研究账本 → 一次独立输入验收 → 两次实际 CPU 服务检查 → 晋升固定版本 → 正式 Test 单样本与联合媒体批量 → 缓存恢复及仓库外 CLI。

本机目录 `F:\vision-rsi-agent`，使用当前源码入口。以下命令复用已经完成的相同输入与执行记录；不要移动、修改或清除 Demo 的合同、媒体、账本及产物。实现或证据发生变化时会拒绝复用，不能将旧记录当作新版本验收。

```powershell
Set-Location F:\vision-rsi-agent
.\vision-rsi.cmd test --task-id delivery-fixture --version bd034cb74405ed0891caad134d5e54c4 --registry F:\vision-rsi-agent\runs\candidate-delivery-live\3ad98250c3a44fec8f94fcae1d6158ac\registry --input F:\vision-rsi-agent\runs\candidate-delivery-live\3ad98250c3a44fec8f94fcae1d6158ac\research\9eedb5bdaf0b4a69bc41998211bd0c60\single.json
.\vision-rsi.cmd test --task-id delivery-fixture --version bd034cb74405ed0891caad134d5e54c4 --registry F:\vision-rsi-agent\runs\candidate-delivery-live\3ad98250c3a44fec8f94fcae1d6158ac\registry --manifest F:\vision-rsi-agent\runs\candidate-delivery-live\3ad98250c3a44fec8f94fcae1d6158ac\research\9eedb5bdaf0b4a69bc41998211bd0c60\batch.jsonl --output-dir F:\vision-rsi-agent\runs\candidate-delivery-live\3ad98250c3a44fec8f94fcae1d6158ac\batch-output --resume
```

单样本输出含 `events: [{label: action, start_seconds: 0, end_seconds: 1}]`，批量摘要 `succeeded: 1, failed: 0`。联合多图/视频输入保持一个样本，不按图片数拆开。`acceptance.scope` 为选定研究账本及冻结验收集，`production_accepted` 为 false；它不保证任意新输入效果。

证据：`runs/candidate-delivery-live/3ad98250c3a44fec8f94fcae1d6158ac/evidence.json` 和 `delivery-result.json`。最终探针实际 CPU 调用6次、LLM0次、GPU未使用。第一次探针仅执行1次开发评测，因原 bundle 合同字节格式与新会话冻结合同不同而停止，失败记录保留在 `runs/candidate-delivery-live/712f999824db43b58c9421b1b5bea396/evidence.json`；随后从已验证源码按新冻结合同重新组装，没有放宽哈希检查。

需要重新执行实际远端验证时，使用 `tests/live_candidate_delivery_probe.py --help`，必须显式传 `--live-remote --bundle PATH --config PATH`。每次生成独立证据目录，最多6次CPU调用，不触发LLM或GPU；失败与不确定结果不会覆盖为成功。现有 dev8 安装包不包含当前源码的晋升链路。
