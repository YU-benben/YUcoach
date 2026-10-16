# 手机安装与版本更新

更新：2026-10-16。最新本地安装包是项目根目录 `YUcoach-target-lock.apk`，App版本1.1.1，构建号3。旧model-switch和manual-timing安装包已由此版本替代。

1. 将最新APK传到Android手机，打开后按系统提示允许该来源安装。
2. 优先覆盖安装；签名一致时可保留本机资料。签名不一致时先备份资料，再处理安装冲突，不要直接卸载丢数据。
3. 电脑停止旧分析服务，双击`打开App.bat`启动新版。手机和电脑需同时更新。
4. 保持同一Wi-Fi或热点，App填服务打印的`http://电脑IP:8770`地址。保持服务窗口开启。
5. 上传固定侧面120fps以上原片，框选运动员，再逐帧确认接触事件。详见 [人工计时](docs/18-固定侧面人工确认计时.md)。

## 自己修改版本号

打开mobile/pubspec.yaml，修改`version: 1.1.1+3`，例如下一版`1.1.2+4`；加号前是显示版本，加号后是递增构建号。然后执行：

```powershell
Set-Location D:\YUcoach\mobile
flutter build apk --release
```

产物位于mobile/build/app/outputs/flutter-apk/app-release.apk。将新产物复制为便于识别的交付文件名，核对版本后再分发。改配置不会自动更新已安装App，推送GitHub也不会自动安装或创建Release。后续正式发布需固定管理签名密钥；当前没有自动更新渠道。

人工计时不用GPU推理。模型切换与自动人物关联是实验功能，不保证自动空间指标正确；详情见 [模型切换](docs/16-App模型切换.md) 和 [人物锁定](docs/19-人物锁定.md)。
