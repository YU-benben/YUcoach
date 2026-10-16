# YUcoach 短跑视频分析

更新：2026-10-16。Android App + 电脑分析服务。当前推荐**固定侧面、高帧率原片、人工确认接触帧**，先获得可复核的时间测量；姿态模型自动分析仍属实验功能。

| 版本 | 当前值 |
|---|---|
| App | 1.1.1+3（Android versionName / versionCode：1.1.1 / 3） |
| 报告契约 | 1.2.0 |
| 分析算法 / 规则 | 0.4.0 / 0.3.0 |
| 报告 std_version / YAML库标识 | 0.1.0 / 2026Q1 |

## 当前能做什么

- 上传视频，框选运动员，确认原视频起止帧；逐帧标注左右脚着地和离地。
- 计算触地时间、腾空时间、步频和同脚完整周期占空比，显示原始事件画面。
- 成功任务将原视频、运动员信息、人工确认记录和报告保存到电脑 `data/manual_timing/<job_id>/`。
- 实验模式可选 YOLOv8n/s/m/l 或 RTMPose 三个档位，按位置、运动预测和衣着颜色关联已选人物；检测不确定时停止，不自动换人续算。
- 参考值按人群、视角、阶段、测量窗口、步次和负荷严格匹配。条件缺失时不做优劣判断。

人工模式不运行姿态模型、不输出空间指标或自动训练建议。框选只明确分析对象，人工仍须逐帧确认同一人。实验模式的自动接触、尺度和空间几何尚有已知问题；锁定人物不能证明测量准确。现有模型未证明是高速短跑的最优模型。

## 目录

```text
backend/       分析、规则、服务端与测试
mobile/        Flutter App、契约模型与交互测试
docs/          当前规范、操作说明和历史验证记录
data/          模型清单、参考库、规则；本地人工数据集不入 Git
samples/       契约及姿态对拍样本；私有视频不入 Git
scripts/       校验、评测、文献与资源工具
.cache/        权重、上传、账号和临时产物（不可整体随意清空）
output/        本机分析与调研产物，不入 Git
```

## 电脑准备与启动

以下为 Windows PowerShell，在项目目录执行。已有 `.venv` 时直接启动，不必重新安装。新环境需 Python 3.13；依赖锁定来自开发机，其他平台需验证兼容性。

```powershell
Set-Location D:\YUcoach
py -3.13 -m venv --copies .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m backend.server.app --host 0.0.0.0 --port 8770
```

也可双击 `打开App.bat`。服务窗口需保持开启。手机与电脑在同一网络，在 App 中填写服务打印的手机访问地址，例如 `http://电脑局域网IP:8770`。IP 随网络变化，不能照抄别人的地址。连接失败先检查地址、同网、端口 8770 的防火墙权限及热点隔离。

人工计时不依赖 GPU 推理。完整依赖表含实验模型组件；YOLO 的 PyTorch 会被依赖解析安装，若要使用 NVIDIA GPU，应按 [PyTorch 官方安装说明](https://pytorch.org/get-started/locally/) 安装与显卡驱动兼容的构建，并实际检查 CUDA。不要把某台开发机的耗时视为性能保证。RTMPose 的 ONNX Runtime GPU 还需要匹配 CUDA/cuDNN；GPU 版与 CPU 版不要同时安装。权重首次使用可能联网下载。

服务基于 Python `http.server`，已有账号、额度、兑换码等功能，但请求身份与权限尚不足以支持公网部署。目前限可信局域网原型使用。

## 手机操作

安装最新本地包 `YUcoach-target-lock.apk`（1.1.1+3），电脑服务同步更新。详见 [手机安装说明](手机上安装App.md)。

1. 固定侧面拍摄，至少 120 fps，推荐 240 fps，脚底清晰。上传未变速、未补帧、未重定时的原片。
2. 选择运动员与视频，保留默认「固定侧面 · 人工确认计时」，填写不跟拍。
3. 上传后框住一个完整运动员，选起止帧；区间内避免遮挡、交叉和出画。
4. 逐帧确认左/右脚着地、离地，至少两个完整接触，最好三个以上；左右以运动员自身为准。
5. 确认原片时间基准、固定侧面、同一运动员、区间无漏标四项，再提交计算。

文件时间戳恒定不等于相机真实以该帧率拍摄。服务无法单独证明原始拍摄速度或识别所有补帧，人工确认不可省略。报告质量分是覆盖评分，不是测量误差或准确率。

## 数据与参考库

成功的人工标注或框选任务归档原片、`review.json`、`report.json`，自动模式另存 `target_tracking.json`。失败跟踪只留临时诊断，不进入成功数据集。临时上传按 24 小时清理；任务映射在内存，服务重启后 App 不能直接恢复服务任务。

`data/manual_timing/` 不自动清理，也不上传 GitHub；需另行备份。`.cache/accounts.json` 是账号数据，不能当可再生缓存删除。详见 [数据管理](docs/20-数据管理与后续训练.md)。

生产参考库保留 5 条可审计旧记录，但其跑动条件未确认，目前不能用于自动判定。文献调研候选值没有直接导入生产库。无人群匹配或无结论不代表各项正常，也不自动训练或更新模型。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q -m "not slow"
.\.venv\Scripts\python.exe scripts/check_contracts.py --dir samples/fixtures --sync-mobile
.\.venv\Scripts\python.exe scripts/gen_models.py --check
Set-Location mobile
flutter analyze
flutter test
flutter build apk --release
```

APK 默认产物：`mobile/build/app/outputs/flutter-apk/app-release.apk`。发布前修改 `mobile/pubspec.yaml` 的 `version`，递增构建号并重建；仅改文件不会更新手机已安装的包。同签名升级才能保留原 App 数据；发布签名与自动更新仍待完善。GitHub 推送源码不会自动发布 APK。

`scripts/check_all.py` 是包含 GPU、权重及旧自动指标的扩展门禁，不是人工模式的最低运行条件；通过合成测试也不能证明真实短跑精度。版本验证与已知边界见 [实现进度](docs/13-分析引擎实现进度.md)。

## 文档入口

完整目录见 [docs/README.md](docs/README.md)。日常使用优先阅读 [人工计时](docs/18-固定侧面人工确认计时.md)、[人物锁定](docs/19-人物锁定.md)、[模型切换](docs/16-App模型切换.md) 和 [参考值匹配](docs/17-参考值严格匹配.md)。[版本记录](CHANGELOG.md) 说明本次更新与清理范围。
