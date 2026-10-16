# App 模型切换

## 使用

更新：2026-10-16。当前 App 为 1.1.1+3，默认人工计时不运行模型。

安装根目录的 `YUcoach-target-lock.apk`，关闭原来的分析服务窗口，再运行 `打开App.bat`。
手机与电脑保持同一网络，在 App 连接分析服务。

上传页选择运动员和视频，视频校验通过后，先关闭默认的“固定侧面 · 人工确认计时”，再在提交区选择“分析模型”。实验模式也要框选人物与起止帧，当前 App 的选人流程限定固定侧面、高帧率原片。

| 选项 | 请求配置 | 足部关键点 |
|---|---|---|
| YOLOv8n（默认）/ s / m / l | `estimator=yolo`，对应 `model` | 几何推导 |
| RTMPose 轻量 / 均衡 / 高性能 | `estimator=rtm`，`rtm_mode=lightweight/balanced/performance` | 模型直接预测（不是仪器实测） |

YOLO 可选识别分辨率 640 / 960（默认）/ 1280。
RTMPose 使用所选档位内置的输入尺寸，不使用 YOLO 分辨率。
选择只影响新提交的任务；当前选择保留到本页面销毁，不跨 App 重启保存。
上传和分析期间禁止修改模型，以免显示选项与当前任务不一致。
首次使用未缓存的权重需要电脑联网下载，失败会显示分析错误，不会静默换回其他模型。

报告底部“模型”显示实际模型配置，例如：

```
yolov8-pose 8.4.175 [weights=yolov8n-pose.pt; imgsz=960]
rtmpose-halpe26 0.0.16 [mode=lightweight]
```

配置沿用契约的 `versions.model_version` 字符串保存，旧报告仍可读取。
切换模型会改变测量结果，长期趋势比较应尽量使用相同模型与采集条件。

## 实现

`upload_page.dart` → `AnalysisServerClient.submitAnalysis()` → `/api/analyze`
→ `pose_options_from_params()` → `run_pipeline()` → `_build_estimator()`。

服务端在扣额度前校验模型白名单和参数组合。非法选项返回 HTTP 400。
RTMPose 请求不能携带 YOLO 的 `model` 字段。
提取器将实际配置写入 `PoseSequence.model_config`，报告拼接配置用于溯源。
命令行也支持 `--estimator rtm --rtm-mode balanced`。

## 历史验证（2026-10-13，非当前测试计数）

- 后端快速回归：225 通过；1 个 slow 测试单独排除。
- Flutter 全部测试：190 通过；静态检查无问题。
- `scripts/verify_model_switch.py` 用相同样例视频前 60 帧分别运行 YOLOv8n 和 RTMPose lightweight；两者均输出 20 项指标，并正确记录各自模型配置。
- 报告保存在 `output/model_switch/`。

这次真实运行验证的是流程和配置记录，不是模型精度排名。其他 YOLO 权重与 RTMPose 档位的参数传递已接通，但未逐一进行真实视频评测。

自动人物关联的配置还会追加 `target_lock=position_velocity_hsv_v1`。锁定失败不生成报告；模型切换不解决旧空间计算与尺度问题，不能依据模型更大就认定测量更准确。当前版本验证见 [13](13-分析引擎实现进度.md)。
