# 11 · Fixture 规范（无后端开发）

更新：2026-10-16。本文描述当前实现；未来工作明确标为待完成。

## 三份当前fixture

| 文件 | 场景 |
|---|---|
| analysis_normal.json | 有指标与结论的展示样例 |
| analysis_low_confidence.json | 低可靠性/数据不足提示 |
| analysis_empty.json | 无可用测量结果 |

源文件在 [samples/fixtures](../samples/fixtures)，副本在 [mobile/assets/fixtures](../mobile/assets/fixtures)。它们是界面和契约样本，不能作为真实运动员记录或模型准确性证据。旧设计中的六份场景尚未全部成为独立文件。

## 更新方式

只修改源文件；执行：

```powershell
.\.venv\Scripts\python.exe scripts/check_contracts.py --dir samples/fixtures --sync-mobile
.\.venv\Scripts\python.exe scripts/gen_models.py --check
```

FixtureDataSource加载时移除顶层_开头的元数据，避免与additionalProperties约束冲突。真实服务由AnalysisServerClient接入；原有“无后端开发”的标题不再代表项目当前状态。

## 新协议回归

人工计时与框选不只靠静态fixture验证，还由后端真实编码合成视频和Flutter交互测试覆盖。未来添加默认人工模式、无完整同脚周期、跟踪失败等展示样例时，保留原始帧号、版本与缺失原因。不能手填假测量值并标称实测。

姿态对拍的samples/pose_fixtures和相关测试工具仍保留；手机端移除推理不意味着这些回归资产已过时。
