import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../data/video_probe.dart';
import '../pose/capture_quality.dart';
import '../pose/foot_derivation.dart';
import '../pose/keyframe_selection.dart';
import '../pose/pose_inference.dart';
import '../pose/pose_pipeline.dart';
import '../widgets/skeleton_view.dart';
import '../widgets/app_colors.dart';

/// 姿态识别页。
///
/// ## 这是两段式流程的第一段
///
/// ```
/// ①【本页】选视频 → 识别 → 出骨架图与关键帧
///                        ↑ 到这儿教练已经能看出姿势好不好了
/// ② 点「分析技术指标」→ 传给电脑算 20 个指标 → 完整报告
/// ```
///
/// **为什么分两段**：姿态提取在手机上要几十秒，而指标计算在电脑上
/// 只要 0.1 秒。先给用户看到骨架，他就不用干等 ——
/// 而且网络不通时第一段照样能用。
class PoseRecognitionPage extends StatefulWidget {
  const PoseRecognitionPage({super.key, this.model});

  /// 注入模型，便于测试。
  final PoseOnnxModel? model;

  @override
  State<PoseRecognitionPage> createState() => _PoseRecognitionPageState();
}

class _PoseRecognitionPageState extends State<PoseRecognitionPage> {
  final _probe = const VideoProbe();
  late final PoseExtractor _extractor;

  VideoMetadata? _video;

  bool _running = false;
  ExtractionProgress? _progress;
  PoseExtractionResult? _result;
  String? _error;
  int _frameIndex = 0;

  @override
  void initState() {
    super.initState();
    _extractor = PoseExtractor(model: widget.model);
  }

  @override
  void dispose() {
    // 页面退出时取消正在跑的提取 ——
    // 否则它会继续跑完剩下的帧，白耗电。
    _extractor.cancel();
    _extractor.dispose();
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // 选视频
  // -------------------------------------------------------------------------

  Future<void> _pickVideo() async {
    try {
      // file_picker 13.x：静态方法，返回 List，取消时是空列表而不是 null
      final picked = await FilePicker.pickFiles(
        type: FileType.video,
        dialogTitle: '选择跑姿视频',
      );
      if (picked.isEmpty) return;

      final f = picked.first;

      // Android 相册选来的文件是 content:// URI（无需存储权限），
      // 本地文件则是普通路径。优先用本地路径：
      //   · 原生的 MediaMetadataRetriever 两种都能打开，但本地路径更快
      //   · 取帧时也是同样的道理
      //
      // ⚠️ 不能只用 `f.path` —— 对某些来源它是 null。
      //    所以要有退回。
      final localPath = f.path;
      final uri = (localPath != null && localPath.isNotEmpty)
          ? localPath
          : f.uri.toString();

      if (uri.isEmpty) {
        setState(() => _error = '拿不到视频文件地址。请换一个来源再试。');
        return;
      }

      // 读元数据。这一步很便宜，而且能在跑之前就发现明显问题
      // （比如视频太短、没有视频轨）。
      VideoMetadata? meta;
      try {
        meta = await _probe.probe(uri, fileName: f.name);
      } catch (e) {
        // 元数据读不到不致命 —— 还能试着取帧。
        // 但要在界面上说一声，而不是静默继续。
        meta = VideoMetadata(uri: uri, fileName: f.name);
      }

      if (!mounted) return;
      setState(() {
        _video = meta;
        _result = null;
        _error = null;
        _progress = null;
        _frameIndex = 0;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '选择文件失败：$e');
    }
  }

  // -------------------------------------------------------------------------
  // 跑识别
  // -------------------------------------------------------------------------

  Future<void> _run() async {
    final video = _video;
    if (video == null || _running) return;

    setState(() {
      _running = true;
      _error = null;
      _result = null;
      _progress = const ExtractionProgress(phase: '准备中', fraction: 0);
    });

    try {
      final result = await _extractor.run(
        videoUri: video.uri,
        onProgress: (p) {
          if (!mounted) return;
          setState(() => _progress = p);
        },
      );

      if (!mounted) return;
      setState(() {
        _result = result;
        _running = false;
        _frameIndex = result?.sequence.isEmpty ?? true
            ? 0
            : result!.sequence.frames.first.frameIndex;
      });
    } on PoseInferenceException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.userMessage;
        _running = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        // 非预期异常也给人话，而不是让界面崩掉。
        _error = '识别失败：$e';
        _running = false;
      });
    }
  }

  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('姿态识别')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _videoCard(),
          const SizedBox(height: 16),
          if (_error != null) ...[
            _errorCard(_error!),
            const SizedBox(height: 16),
          ],
          if (_running) ...[
            _progressCard(),
            const SizedBox(height: 16),
          ],
          if (_result != null) ...[
            _resultCard(_result!),
            const SizedBox(height: 16),
            _skeletonSection(_result!),
          ],
          if (_video == null && !_running) _hintCard(),
        ],
      ),
    );
  }

  // ---- 视频信息卡 ----

  Widget _videoCard() {
    final v = _video;

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.videocam_outlined,
                    size: 20, color: context.okText),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    v == null ? '还没有选择视频' : (v.fileName ?? '已选视频'),
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            if (v != null) ...[
              const SizedBox(height: 10),
              _kv('时长', v.durationLabel),
              _kv('分辨率', v.resolutionLabel),
              _kv('帧率', v.frameRate == null
                  ? '未知（容器没提供）'
                  : '${v.frameRate!.toStringAsFixed(0)} fps'),
              _kv('帧数', v.frameCount?.toString() ?? '未知'),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _running ? null : _pickVideo,
                    icon: const Icon(Icons.folder_open, size: 18),
                    label: const Text('选择视频'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: (v == null || _running) ? null : _run,
                    icon: _running
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child:
                                CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.play_arrow, size: 18),
                    label: Text(_running ? '识别中…' : '开始识别'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(
          children: [
            SizedBox(
              width: 64,
              child: Text(k,
                  style: TextStyle(fontSize: 12, color: context.mutedText)),
            ),
            Expanded(
              child: Text(v, style: const TextStyle(fontSize: 12.5)),
            ),
          ],
        ),
      );

  // ---- 进度 ----

  Widget _progressCard() {
    final p = _progress;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    p?.phase ?? '准备中',
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                ),
                Text('${((p?.fraction ?? 0) * 100).round()}%',
                    style: TextStyle(
                        fontSize: 12, color: context.mutedText)),
              ],
            ),
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: p?.fraction ?? 0,
                minHeight: 5,
              ),
            ),
            if (p != null && p.detail.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(p.detail,
                  style: TextStyle(
                      fontSize: 11.5, color: context.mutedText)),
            ],
            const SizedBox(height: 10),
            Text(
              '识别在手机上完成，不需要联网。首次运行会慢一些。',
              style: TextStyle(fontSize: 11, color: context.faintText),
            ),
          ],
        ),
      ),
    );
  }

  // ---- 结果概览 ----

  Widget _resultCard(PoseExtractionResult r) {
    final quality = assessCaptureQuality(
      seq: r.sequence,
      fps: _video?.frameRate,
      personHeights: r.personHeights.values.toList(),
      ambiguousFrames: r.ambiguousFrames,
      expectedFrames: r.framesDecoded,
    );

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  quality.hasBlocking
                      ? Icons.warning_amber_outlined
                      : Icons.check_circle_outline,
                  size: 20,
                  color: quality.hasBlocking
                      ? context.warnText
                      : context.okText,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    quality.verdict,
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // 性能数字。这是最有用的一条 —— 决定将来怎么优化。
            _kv('总耗时', '${(r.elapsedMs / 1000).toStringAsFixed(1)} 秒'),
            _kv('处理帧数', '${r.framesDecoded}'),
            _kv('检出姿态', '${r.framesWithPose} 帧'),
            _kv('每帧耗时',
                '${r.msPerFrame.toStringAsFixed(0)} 毫秒'),
            _kv('关键帧', '${r.keyframes.length} 张'),
            _kv('事件', r.events.isEmpty
                ? '未检出'
                : '${r.events.stepCount} 步（${r.events.reliability}）'),

            if (quality.issues.isNotEmpty) ...[
              const SizedBox(height: 12),
              for (final issue in quality.issues) ...[
                _issueTile(issue),
                const SizedBox(height: 8),
              ],
            ],

            if (r.notes.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                r.notes.take(3).join('\n'),
                style: TextStyle(
                    fontSize: 11, color: context.faintText, height: 1.5),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _issueTile(CaptureIssue issue) {
    final (bg, fg, icon) = switch (issue.level) {
      CaptureIssueLevel.blocking => (
          context.errorSurface,
          context.errorText,
          Icons.error_outline,
        ),
      CaptureIssueLevel.warning => (
          context.warnSurface,
          context.warnText,
          Icons.warning_amber_outlined,
        ),
      CaptureIssueLevel.ok => (
          context.okSurface,
          context.okText,
          Icons.check_circle_outline,
        ),
    };

    return Container(
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: fg),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(issue.title,
                    style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: fg)),
                const SizedBox(height: 3),
                Text(issue.detail,
                    style: const TextStyle(fontSize: 11.5, height: 1.45)),
                const SizedBox(height: 4),
                Text(issue.suggestion,
                    style: TextStyle(
                        fontSize: 11.5,
                        height: 1.45,
                        color: context.mutedText)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ---- 骨架 ----

  Widget _skeletonSection(PoseExtractionResult r) {
    if (r.sequence.isEmpty) {
      return Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            '没有检出任何姿态。\n\n'
            '常见原因：\n'
            '· 运动员在画面里太小\n'
            '· 画面太暗或太模糊\n'
            '· 视频里没有人',
            style: TextStyle(
                fontSize: 12.5, color: context.mutedText, height: 1.6),
          ),
        ),
      );
    }

    final frames = r.sequence.frames;
    final idx = frames.indexWhere((f) => f.frameIndex == _frameIndex);
    final current = idx >= 0 ? frames[idx] : frames.first;
    final derived = r.derivedFrames.firstWhere(
      (d) => d.frame.frameIndex == current.frameIndex,
      orElse: () => deriveFrame(current),
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('骨架',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SkeletonView(
          derived: derived,
          aspectRatio: _videoAspect(),
        ),
        const SizedBox(height: 10),

        // ---- 时间轴 ----
        //
        // 拖动看骨架动起来。这比几张静态图直观得多 ——
        // 教练能看出动作的连贯性。
        Row(
          children: [
            Text('第 ${current.frameIndex} 帧',
                style: TextStyle(fontSize: 12, color: context.mutedText)),
            const Spacer(),
            Text('共 ${frames.length} 帧',
                style: TextStyle(fontSize: 12, color: context.mutedText)),
          ],
        ),
        Slider(
          value: idx >= 0 ? idx.toDouble() : 0,
          min: 0,
          max: (frames.length - 1).toDouble(),
          divisions: frames.length > 1 ? frames.length - 1 : null,
          onChanged: (v) {
            setState(() {
              _frameIndex = frames[v.round()].frameIndex;
            });
          },
        ),

        // ---- 关键帧快捷跳转 ----
        if (r.keyframes.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('关键帧',
              style: TextStyle(fontSize: 12, color: context.mutedText)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final k in r.keyframes)
                ActionChip(
                  label: Text(
                    '第${k.stepIndex ?? "?"}步 · ${EventName.zh(k.event)}',
                    style: const TextStyle(fontSize: 11.5),
                  ),
                  onPressed: () {
                    setState(() => _frameIndex = k.frameIndex);
                  },
                ),
            ],
          ),
        ],
      ],
    );
  }

  double _videoAspect() {
    final v = _video;
    final w = v?.width;
    final h = v?.height;
    if (w == null || h == null || w <= 0 || h <= 0) return 16 / 9;
    return w / h;
  }

  // ---- 错误与提示 ----

  Widget _errorCard(String msg) => Card(
        margin: EdgeInsets.zero,
        color: context.errorSurface,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.error_outline,
                  size: 18, color: context.errorText),
              const SizedBox(width: 8),
              Expanded(
                child: Text(msg,
                    style: TextStyle(
                        fontSize: 12.5,
                        color: context.errorText,
                        height: 1.5)),
              ),
            ],
          ),
        ),
      );

  Widget _hintCard() => Card(
        margin: EdgeInsets.zero,
        color: context.okSurface,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.info_outline,
                      size: 16, color: context.okText),
                  const SizedBox(width: 6),
                  Text('这个功能做什么',
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: context.okText)),
                ],
              ),
              const SizedBox(height: 8),
              const Text(
                '选一段视频，在你手机本地提取运动员的骨骼关键点，'
                '并挑出起跑、加速、途中跑的关键帧。\n\n'
                '全程不联网，视频不会上传。\n\n'
                '识别完之后，可以点「分析技术指标」把骨架数据'
                '（约 200 KB）传给电脑，算出 20 个技术指标。',
                style: TextStyle(fontSize: 12, height: 1.6),
              ),
            ],
          ),
        ),
      );
}

/// 判断文件是否可能是视频（用于错误提示）。
bool looksLikeVideo(String path) {
  final ext = path.split('.').last.toLowerCase();
  return const ['mp4', 'mov', 'avi', 'mkv', '3gp', 'webm'].contains(ext);
}

/// 桌面端不支持取帧时的提示。
String? platformSupportWarning() {
  if (Platform.isAndroid) return null;
  return '姿态识别目前只支持 Android 手机。\n'
      '当前平台：${Platform.operatingSystem}';
}
