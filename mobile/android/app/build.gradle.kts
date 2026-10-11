plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "cn.yucoach.yu_coach"
    compileSdk = flutter.compileSdkVersion

    // 不使用 flutter.ndkVersion（当前为 28.2.13676358），改用本机已安装的版本。
    //
    // 原因：Flutter 的 Gradle 插件会主动强制下载它指定的 NDK 版本
    // （见 flutter_tools 的 forceNdkDownload），而本机开发环境的
    // sdkmanager 仓库列表里没有该版本的条目，装不上。
    //
    // 本项目**没有任何 C/C++ 代码**，NDK 只是 Flutter 模板的默认要求；
    // 且 NDK 向后兼容，高版本可以编译面向低版本的目标。
    //
    // 换机器时若报「NDK not found」，改成本机已装版本即可：
    //     dir %ANDROID_HOME%\ndk
    ndkVersion = "30.0.16248370"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "cn.yucoach.yu_coach"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // ---- 只打包 arm64-v8a ----
        //
        // ## 为什么
        //
        // 1. **体积**：不限制的话会把 onnxruntime 的两份原生库都打进去
        //    （arm64 13.55 MB + armv7 9.37 MB）。加上模型文件，
        //    APK 会从 53 MB 涨到 80 MB 以上。只留一份能省近 10 MB。
        //
        // 2. **稳定性**：onnxruntime 在 **32 位 ARM 上有已知的崩溃问题**
        //    （microsoft/onnxruntime#27311，对齐访问导致的 bus error）。
        //    与其给 32 位用户一个会闪退的 App，不如明确不支持 ——
        //    他们仍然可以用「上传到电脑分析」的流程。
        //
        // ## 代价（必须知情）
        //
        // 2017 年以前的手机基本是 32 位，装不上。占比已经很低，
        // 但**不是零**。如果将来需要支持，去掉这一行并把 onnxruntime
        // 换成 64/32 都验证过的方案即可 —— 但那要先解决上面那个崩溃问题。
        //
        // ## 为什么 x86_64 也去掉
        //
        // 那是模拟器架构，真机用不到。开发时如果要在模拟器上跑，
        // 临时把 "x86_64" 加回来即可。
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
