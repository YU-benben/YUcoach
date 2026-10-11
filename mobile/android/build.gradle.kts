allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
// ---------------------------------------------------------------------------
// 关于 onnxruntime 的 compileSdk 问题 —— 已由另外两处解决，这里不需要代码
//
// 出现过的问题：pub 上的 `onnxruntime` 1.4.1 以 android-33 编译，
// 与当前 AndroidX 依赖链（要求 34+）冲突，AGP 的 AAR 元数据校验硬失败。
//
// 试过两条路，都不行：
//   ✗ `android.suppressUnsupportedCompileSdk=33`  —— 只对应用模块生效
//   ✗ 在本文件里用 afterEvaluate 反射改子项目的 compileSdk —— 改不动，
//      AGP 在 evaluation 阶段就把值锁定了
//
// 最终解法是**把这个包放进项目里**（mobile/third_party/onnxruntime），
// 直接改它构建文件里的那一个数字。见该目录下 android/build.gradle 的说明。
//
// 所以本文件保持原样，不引入任何 Gradle 技巧 ——
// 能用配置解决的事不要用构建脚本的黑魔法。
// ---------------------------------------------------------------------------

subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
