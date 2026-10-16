import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../data/analysis_server_client.dart';
import '../data/athlete_repository.dart';
import '../data/session_repository.dart';
import '../data/video_probe.dart';
import '../domain/athlete_record.dart';
import '../domain/local_user.dart';
import '../domain/session_record.dart';
import '../models/models.dart';
import '../widgets/capture_info_form.dart';
import 'athlete_list_page.dart' show eventLabelOf;
import 'refreshable.dart';
import 'report_page.dart';
import 'manual_contact_review_page.dart';
import 'target_selection_page.dart';
import 'server_settings_page.dart';
import '../widgets/app_colors.dart';

/// 上传视频并提交分析。
///
/// 流程：选运动员 → 选视频 → 初级校验 → 填采集信息 → 上传 → 分析 → 看报告
///
/// 「初级校验」放在 App 端做的意义：让教练在**上传前**就知道素材是否可用，
/// 而不是传完几百 MB、等分析跑完才被告知「帧率不合格」。
/// 权威的帧率校验在服务端做（需要姿态分析反推步频），这里只能做自洽性检查。
class UploadPage extends StatefulWidget {
  const UploadPage({
    super.key,
    required this.athletes,
    required this.sessions,
    this.user,
  });

  final AthleteRepository athletes;
  final SessionRepository sessions;

  /// 当前登录的用户。
  ///
  /// 为什么上传页需要它：提交分析时服务端要求带 `username`，
  /// 用来确认账号并扣额度。**服务端的账号体系是独立的**——
  /// 它不认识 App 的本地账号，所以必须把这个身份显式传过去。
  ///
  /// 曾经这里没有这个参数，导致提交的 payload 里压根没有 username 字段，
  /// 服务端一律回「请先登录」——而用户明明已经登录了。
  final LocalUser? user;

  @override
  State<UploadPage> createState() => UploadPageState();
}

/// 公开（非 `_` 前缀）是为了让主界面能通过 `GlobalKey<UploadPageState>`
/// 在切 Tab 时调用 reload()。见 refreshable.dart 的说明。
class UploadPageState extends State<UploadPage> implements Refreshable {
  bool _manualTiming = true;
  final _probe = const VideoProbe();
  final _client = AnalysisServerClient();
  final _settings = ServerSettings();

  List<AthleteRecord> _athletes = [];
  bool _loading = true;

  AthleteRecord? _athlete;
  String? _fileName;
  int? _fileSize;
  String? _videoPath;
  VideoMetadata? _metadata;
  VideoValidation? _validation;

  CaptureInfo? _captureInfo;
  String _poseModel = 'yolov8n-pose.pt';
  int _poseImageSize = 960;

  bool _picking = false;
  bool _saving = false;
  String? _pickError;
  String? _saveMessage;

  // ---- 分析流程状态 ----
  //
  // 用枚举而不是若干个 bool 组合：多个 bool 会出现
  // "既在上传又在分析"这类不可能的状态，而枚举天然互斥。
  _Phase _phase = _Phase.idle;
  double _uploadProgress = 0;
  double _analysisProgress = 0;
  String _analysisStage = '';
  String? _analysisError;
  String? _analysisHint;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  Future<void> _load() async {
    final list = await widget.athletes.list();
    if (!mounted) return;
    setState(() {
      _athletes = list;
      _loading = false;

      final selectedId = _athlete?.athleteId;
      if (selectedId == null) return;

      // 把 _athlete 重新绑定到**本次读出来的实例**。
      //
      // 不能继续持有旧实例：reload() 会从文件重新反序列化，
      // 得到的是全新对象。旧对象的内容可能已经过期（比如用户刚改了身高），
      // 而表单里的身高预填、保存时的姓名都从 _athlete 读 ——
      // 不重绑就会用到过期数据。
      final fresh = list.where((a) => a.athleteId == selectedId).toList();

      if (fresh.isEmpty) {
        // 选中的运动员已被删除（在「运动员」页删掉了）。
        // 必须清掉选择，否则会停在一个不存在的档案上，
        // 保存出来的记录会指向无效的 athlete_id。
        _athlete = null;
        _captureInfo = null;
      } else {
        _athlete = fresh.first;
      }
    });
  }

  /// 切到本页时由主界面调用，重新读运动员列表。
  ///
  /// 必要性：本页的 initState 只在 App 启动时跑一次，那时可能还没有任何
  /// 运动员。用户在「运动员」页添加后切回来，必须重新读才能看到。
  @override
  Future<void> reload() => _load();

  Future<void> _pickVideo() async {
    setState(() {
      _picking = true;
      _pickError = null;
    });

    try {
      // file_picker 13.x：静态方法，返回 List，取消时是空列表而不是 null
      final picked = await FilePicker.pickFiles(
        type: FileType.video,
        dialogTitle: '选择跑姿视频',
      );

      if (picked.isEmpty) {
        // 用户取消不是错误
        if (mounted) setState(() => _picking = false);
        return;
      }

      final file = picked.first;

      // Android 相册选来的文件是 content:// URI（无需存储权限），
      // 本地文件则是 file:// 。原生的 ContentResolver 两种都能打开，
      // 所以直接把 URI 字符串传下去。
      //
      // 不能只用 file.path —— 对 content:// 它返回 null。
      // file_picker 会为相册素材生成一个真实的本地缓存路径。
      //
      // 优先用本地路径而不是 content:// URI：
      //   · 元数据探测：MediaMetadataRetriever 两种都支持，但本地路径更快
      //   · 上传：需要按字节流读，content:// 无法直接读
      // 只有两者都没有时才失败。
      final localPath = file.path;
      final uriString = file.uri.toString();
      final probeTarget = (localPath != null && localPath.isNotEmpty)
          ? localPath
          : uriString;

      if (probeTarget.isEmpty) {
        if (!mounted) return;
        setState(() {
          _picking = false;
          _pickError = '拿不到视频文件地址。请换一个来源再试。';
        });
        return;
      }

      final size = file.lengthSync();

      final metadata = await _probe.probe(probeTarget, fileName: file.name);
      final validated = validateVideo(metadata);

      if (!mounted) return;
      setState(() {
        _fileName = file.name;
        _fileSize = size;
        // 存本地路径（file_picker 已导出好的那份）。
        // 上传时直接流式读它，不需要再复制。
        _videoPath = (localPath != null && localPath.isNotEmpty)
            ? localPath
            : uriString;
        _metadata = metadata;
        _validation = validated;
        _picking = false;
        // 换了视频，之前填的采集信息仍然有效（同一场地同一机位），
        // 但校验结果变了，提交状态要重新评估
      });
    } on UnsupportedError catch (e) {
      if (!mounted) return;
      setState(() {
        _picking = false;
        _pickError =
            '${e.message}\n\n'
            '开发提示：读取视频元数据依赖 Android 原生接口，'
            '在 Windows 上跑只能测界面，测不了这一步。';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _picking = false;
        _pickError =
            '读取视频失败：$e\n\n'
            '可能原因：文件损坏、编码不支持，或文件权限已失效。';
      });
    }
  }

  void _reset() {
    setState(() {
      _fileName = null;
      _fileSize = null;
      _videoPath = null;
      _metadata = null;
      _validation = null;
      _pickError = null;
      _saveMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('上传视频')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_athletes.isEmpty)
                  const _NeedAthleteFirst()
                else ...[
                  _StepHeader(index: 1, title: '选择运动员', done: _athlete != null),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    // 用 id 而不是 AthleteRecord 对象作为下拉值。
                    //
                    // 为什么：DropdownButtonFormField 要求 value 能在 items 里
                    // **恰好匹配到一项**，用的是 == 比较。AthleteRecord 没有
                    // 覆写 ==，所以走引用比较 —— 而每次 reload() 都会从文件
                    // 反序列化出**全新实例**，内容一样但引用不同。
                    // 结果就是一个红色断言页：
                    //   There should be exactly one item with
                    //   [DropdownButton]'s value
                    //
                    // id 是稳定且唯一的，用它做值天然不会踩这个坑。
                    initialValue: _athlete?.athleteId,
                    decoration: const InputDecoration(labelText: '运动员'),
                    items: [
                      for (final a in _athletes)
                        DropdownMenuItem(
                          value: a.athleteId,
                          child: Text('${a.name} · ${eventLabelOf(a.event)}'),
                        ),
                    ],
                    onChanged: (id) => setState(() {
                      _athlete = id == null
                          ? null
                          : _athletes.firstWhere((a) => a.athleteId == id);
                    }),
                  ),

                  const SizedBox(height: 24),
                  _StepHeader(
                    index: 2,
                    title: '选择视频并校验',
                    done: _validation != null,
                  ),
                  const SizedBox(height: 8),
                  _pickCard(),
                  if (_pickError != null) ...[
                    const SizedBox(height: 12),
                    _ErrorBox(text: _pickError!),
                  ],
                  if (_validation != null) ...[
                    const SizedBox(height: 12),
                    _ValidationReport(
                      validation: _validation!,
                      metadata: _metadata!,
                      fileSize: _fileSize,
                    ),
                  ],

                  if (_validation?.canProceed == true) ...[
                    const SizedBox(height: 24),
                    _StepHeader(
                      index: 3,
                      title: '填写采集信息',
                      done: _captureInfo != null,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '带 * 的项必须填 —— 它们直接决定分析能不能算、算得准不准。',
                      style: TextStyle(fontSize: 11, color: context.faintText),
                    ),
                    const SizedBox(height: 14),
                    CaptureInfoForm(
                      // 换运动员时要重建表单，让身高预填跟着切换
                      key: ValueKey(_athlete?.athleteId),
                      athleteHeightCm: _athlete?.heightCm,
                      onChanged: (info) => setState(() => _captureInfo = info),
                    ),
                    _submitSection(),
                  ],
                ],
                const SizedBox(height: 24),
                // 把当前选的视角传进去 —— 拍摄要点里对应那一节默认展开，
                // 用户不用自己找。拍正面时还显示侧面的要点没有意义。
                _ShootingGuide(
                  view: switch (_captureInfo?.view) {
                    SessionView.front => 'front',
                    SessionView.back => 'back',
                    _ => 'side',
                  },
                ),
              ],
            ),
    );
  }

  /// 提交区。
  ///
  /// 按钮禁用时必须说明**缺什么** —— 灰掉的按钮不解释原因是常见的体验灾难。
  Widget _submitSection() {
    final info = _captureInfo;
    final ready = info != null && _validation?.canProceed == true;
    final busy = _phase == _Phase.uploading || _phase == _Phase.analyzing;

    // 缺项清单
    final missing = <String>[];
    if (_athlete == null) missing.add('选择运动员');
    if (_metadata == null) missing.add('选择视频');
    if (_metadata != null && info == null) missing.add('填写采集信息（带 * 的项）');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('固定侧面 · 人工确认计时（推荐）'),
          subtitle: const Text('至少 120 fps 原片。上传后逐帧确认接触；只计算时间指标。关闭后为实验性自动分析。'),
          value: _manualTiming,
          onChanged: busy ? null : (v) => setState(() => _manualTiming = v),
        ),
        if (!_manualTiming) ...[
          DropdownButtonFormField<String>(
            key: const Key('analysis-model'),
            initialValue: _poseModel,
            isExpanded: true,
            decoration: const InputDecoration(labelText: '分析模型'),
            items: const [
              DropdownMenuItem(
                value: 'yolov8n-pose.pt',
                child: Text('YOLOv8n · 快速（默认）'),
              ),
              DropdownMenuItem(
                value: 'yolov8s-pose.pt',
                child: Text('YOLOv8s · 小型'),
              ),
              DropdownMenuItem(
                value: 'yolov8m-pose.pt',
                child: Text('YOLOv8m · 中型'),
              ),
              DropdownMenuItem(
                value: 'yolov8l-pose.pt',
                child: Text('YOLOv8l · 大型'),
              ),
              DropdownMenuItem(
                value: 'lightweight',
                child: Text('RTMPose · 轻量（含足部点）'),
              ),
              DropdownMenuItem(
                value: 'balanced',
                child: Text('RTMPose · 均衡（含足部点）'),
              ),
              DropdownMenuItem(
                value: 'performance',
                child: Text('RTMPose · 高性能（含足部点）'),
              ),
            ],
            onChanged: busy
                ? null
                : (value) => setState(() => _poseModel = value!),
          ),
          const SizedBox(height: 8),
          Text(
            _poseModel.endsWith('.pt')
                ? 'YOLO 的脚尖、脚跟由几何推导。更大的模型通常耗时更长，效果需用实际视频比较。'
                : 'RTMPose 直接预测脚尖、脚跟。首次使用需由电脑下载模型，请保持联网；切换模型可能改变指标结果。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (_poseModel.endsWith('.pt')) ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              key: const Key('analysis-image-size'),
              initialValue: _poseImageSize,
              decoration: const InputDecoration(labelText: '识别分辨率'),
              items: const [
                DropdownMenuItem(value: 640, child: Text('640 · 较快')),
                DropdownMenuItem(value: 960, child: Text('960 · 默认')),
                DropdownMenuItem(value: 1280, child: Text('1280 · 较高分辨率')),
              ],
              onChanged: busy
                  ? null
                  : (value) => setState(() => _poseImageSize = value!),
            ),
            const SizedBox(height: 8),
            Text(
              '首次使用新模型需由电脑下载权重，请保持联网。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
        if (_saveMessage != null) ...[
          const SizedBox(height: 12),
          _SuccessBox(text: _saveMessage!),
        ],

        // 进行中的进度。上传与分析是两个阶段，分开显示 ——
        // 上传卡住和分析慢是两种完全不同的等待，混在一起会让用户
        // 无法判断该不该继续等。
        if (busy) ...[
          const SizedBox(height: 16),
          _ProgressBox(
            phase: _phase,
            uploadProgress: _uploadProgress,
            analysisProgress: _analysisProgress,
            stage: _analysisStage,
          ),
        ],

        if (_analysisError != null) ...[
          const SizedBox(height: 16),
          _ErrorBox(
            text: _analysisHint == null
                ? _analysisError!
                : '${_analysisError!}\n\n${_analysisHint!}',
          ),
        ],

        const SizedBox(height: 20),
        if (!ready && missing.isNotEmpty && !busy) ...[
          Container(
            padding: EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: context.subtleSurface,
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                Icon(Icons.info_outline, size: 16, color: context.faintText),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '还需要：${missing.join('、')}',
                    style: TextStyle(fontSize: 12, color: context.mutedText),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
        ],
        FilledButton(
          // 用 info != null 而不是 ready 做收窄条件，这样闭包里能用非空 info
          onPressed: (info == null || !ready || _saving)
              ? null
              : () => _save(info),
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 14),
          ),
          child: _saving
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('上传并分析'),
        ),
        const SizedBox(height: 10),
        _ServerHint(
          onConfigure: () => Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => ServerSettingsPage(settings: _settings),
            ),
          ),
        ),
      ],
    );
  }

  /// 完整的提交流程：保存本地记录 → 上传 → 分析 → 打开报告。
  ///
  /// 为什么先存本地记录再上传：如果上传或分析失败，
  /// 记录仍然在，教练可以在「数据」页看到它并知道发生过什么。
  /// 反过来先上传后记录，一旦中途失败就什么都不剩，
  /// 而用户已经等了几分钟，会觉得"白等了"。
  Future<void> _save(CaptureInfo info) async {
    final athlete = _athlete;
    final meta = _metadata;
    if (athlete == null || meta == null) return;
    if (info.view != SessionView.side || info.cameraFollowed != false) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('人物锁定首版请填写侧面视角，并确认没有镜头跟随。')));
      return;
    }

    setState(() {
      _saving = true;
      _saveMessage = null;
      _analysisError = null;
      _analysisHint = null;
      _uploadProgress = 0;
      _analysisProgress = 0;
      _analysisStage = '';
    });

    SessionRecord record;
    try {
      record = await widget.sessions.create(
        athleteId: athlete.athleteId,
        athleteName: athlete.name,
        testType: info.testType,
        view: info.view,
        videoPath: _videoPath,
        videoFileName: _fileName,
        fileSizeBytes: _fileSize,
        durationMs: meta.durationMs,
        width: meta.width,
        height: meta.height,
        fpsDeclared: meta.frameRate,
        frameCount: meta.frameCount,
        cameraDistanceM: info.cameraDistanceM,
        cameraHeightM: info.cameraHeightM,
        hasLaneLine: info.hasLaneLine,
        cameraFollowed: info.cameraFollowed,
        exposureLocked: info.exposureLocked,
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _pickError = '保存记录失败：$e';
      });
      return;
    }

    if (!mounted) return;
    setState(() => _saveMessage = '已保存「${athlete.name}」的记录');

    // ---- 没有配置分析服务时到此为止 ----
    final baseUrl = await _settings.baseUrl();
    if (!mounted) return;
    if (baseUrl == null || baseUrl.isEmpty) {
      setState(() {
        _saving = false;
        _phase = _Phase.idle;
        _analysisStage = '记录已保存，但未提交分析';
      });
      return;
    }

    final path = _videoPath;
    if (path == null) {
      setState(() {
        _saving = false;
        _analysisError = '拿不到视频文件，无法提交分析';
      });
      return;
    }

    // ---- 账号检查（放在上传之前）----
    //
    // 提交分析时服务端要求带 username 来认账号、扣额度。
    // 新注册的账号都有用户名；这里拦的是**老账号** ——
    // 它们是在"手机号 / 用户名二选一"那版注册的，可能没有用户名。
    //
    // ⚠️ 必须在上传**之前**拦：否则用户白等一次几百 MB 的上传
    //    才被告知账号不能用。
    final username = (widget.user?.username ?? '').trim();
    if (username.isEmpty) {
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        _analysisError = '这个账号还没有用户名，暂时无法提交分析';
        _analysisHint =
            '分析要在电脑上排队执行，服务端需要一个用户名来记账。'
            '你的账号是早期用手机号注册的，缺这一项。'
            '请到「我的 → 编辑资料」补一个用户名，回来后即可提交。'
            '这次的记录已存在本机，补完用户名后仍能在「数据」里看到。';
      });
      await widget.sessions.markFailed(record.sessionId, '账号没有用户名，未提交分析');
      return;
    }

    // ---- 上传 ----
    setState(() {
      _phase = _Phase.uploading;
      _analysisStage = '正在上传视频';
    });

    String videoId;
    try {
      // content:// URI 不能直接当文件读，先复制到本地缓存。
      final file = await _materializeVideo(path);
      videoId = await _client.uploadVideo(
        file,
        baseUrl: baseUrl,
        onProgress: (p) {
          if (mounted) setState(() => _uploadProgress = p);
        },
      );
    } on ServerException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        _analysisError = e.message;
        _analysisHint = e.hint;
      });
      await widget.sessions.markFailed(record.sessionId, '上传失败：${e.message}');
      return;
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        _analysisError = '上传失败：$e';
      });
      await widget.sessions.markFailed(record.sessionId, '上传失败：$e');
      return;
    }

    // ---- 提交分析 ----
    if (!mounted) return;
    setState(() {
      _phase = _Phase.analyzing;
      _analysisStage = '已提交，等待分析';
    });

    String jobId;
    try {
      final target = await Navigator.of(context).push<Map<String, dynamic>>(
        MaterialPageRoute(
          builder: (_) => TargetSelectionPage(
            client: _client,
            baseUrl: baseUrl,
            videoId: videoId,
          ),
        ),
      );
      if (!mounted) return;
      if (target == null) {
        await widget.sessions.markFailed(record.sessionId, '选人已取消，未提交分析');
        if (mounted) {
          setState(() {
            _saving = false;
            _phase = _Phase.failed;
            _analysisError = '选人已取消，未扣分析额度';
          });
        }
        return;
      }
      Map<String, dynamic>? review;
      if (_manualTiming) {
        review = await Navigator.of(context).push<Map<String, dynamic>>(
          MaterialPageRoute(
            builder: (_) => ManualContactReviewPage(
              client: _client,
              baseUrl: baseUrl,
              videoId: videoId,
              targetSelection: target,
            ),
          ),
        );
        if (!mounted) return;
        if (review == null) {
          await widget.sessions.markFailed(record.sessionId, '人工确认已取消，未提交分析');
          if (mounted) {
            setState(() {
              _saving = false;
              _phase = _Phase.failed;
              _analysisError = '人工确认已取消，未扣分析额度';
            });
          }
          return;
        }
      }
      jobId = await _client.submitAnalysis(
        manualReview: review,
        targetSelection: target,
        baseUrl: baseUrl,
        videoId: videoId,
        athleteId: athlete.athleteId,
        athleteName: athlete.name,
        gender: athlete.gender == AthleteGender.female ? 'female' : 'male',
        event: athlete.event,
        level: _levelToContract(athlete.level),
        heightCm: athlete.heightCm,
        view: info.view == SessionView.front
            ? 'front'
            : (info.view == SessionView.back ? 'back' : 'side'),
        testType: _testTypeToContract(info.testType),
        cameraDistanceM: info.cameraDistanceM,
        cameraHeightM: info.cameraHeightM,
        hasLaneLine: info.hasLaneLine,
        cameraFollowed: info.cameraFollowed,
        sessionId: record.sessionId,
        // 服务端靠它认账号、扣额度。为空时服务端会回「请先登录」——
        // 所以下面提交前会先拦一道，把话说明白。
        username: widget.user?.username,
        estimator: _poseModel.endsWith('.pt') ? 'yolo' : 'rtm',
        model: _poseModel,
        imgsz: _poseImageSize,
        rtmMode: _poseModel,
      );
      await widget.sessions.markQueued(record.sessionId, jobId);
    } on ServerException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        _analysisError = e.message;
        _analysisHint = e.hint;
      });
      await widget.sessions.markFailed(record.sessionId, '提交分析失败：${e.message}');
      return;
    }

    // ---- 轮询进度 ----
    try {
      await for (final p in _client.watchJob(baseUrl: baseUrl, jobId: jobId)) {
        if (!mounted) return;
        setState(() {
          _analysisProgress = p.progress;
          _analysisStage = p.stage;

          if (p.isDone && p.report != null) {
            _phase = _Phase.done;
            _saving = false;
          } else if (p.isFailed) {
            _phase = _Phase.failed;
            _saving = false;
            _analysisError = p.error ?? '分析失败';
            _analysisHint = '这条记录已标记为失败，可在「数据」页查看。';
          }
        });

        if (p.isDone && p.report != null) {
          // ---- 落库并打开报告 ----
          final result = AnalysisResult.fromJson(p.report!);
          final analysisId = result.analysisId.isNotEmpty
              ? result.analysisId
              : jobId;
          await widget.sessions.markAnalyzed(
            record.sessionId,
            analysisId,
            result,
          );

          if (!mounted) return;
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => ReportPage(initialResult: result),
            ),
          );
          return;
        }

        if (p.isFailed) {
          await widget.sessions.markFailed(record.sessionId, p.error ?? '分析失败');
          return;
        }
      }
    } on ServerException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        _analysisError = e.message;
        _analysisHint = e.hint;
      });
      await widget.sessions.markFailed(record.sessionId, '分析中断：${e.message}');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _phase = _Phase.failed;
        // 报告解析失败是最可能的失败原因，单独说清楚 ——
        // 这类问题需要开发者介入，不是用户能解决的。
        _analysisError = '分析完成但结果无法解析：$e';
        _analysisHint = '这通常是版本不匹配。请把这条信息反馈给开发者。';
      });
    }
  }

  /// 把视频 URI 解析成一个可读的本地文件。
  ///
  /// 为什么要区分情况：
  ///   · Android 相册选来的文件，`file_picker` 已经把内容导出到应用缓存，
  ///     并通过 `PlatformFile.path` 给出真实路径 —— 这时直接用，不要多复制一次。
  ///   · 少数来源（如某些云盘 App）只给 `content://` URI 而没有本地路径，
  ///     这种情况无法直接按字节读，需要如实报错而不是静默失败。
  ///
  /// 本方法只做**路径解析与存在性检查**，不做复制 ——
  /// 复制由 file_picker 在选取阶段完成，这里再复制一次纯属浪费
  /// （慢动作素材几百 MB，多复制一次要好几秒）。
  Future<File> _materializeVideo(String pathOrUri) async {
    final uri = Uri.tryParse(pathOrUri);

    if (uri != null && uri.scheme == 'file') {
      return File(uri.toFilePath());
    }

    final f = File(pathOrUri);
    if (await f.exists()) return f;

    throw StateError(
      '拿不到视频文件的本地副本，无法上传。\n'
      '这通常出现在从云盘类应用直接选择文件时 —— '
      '请先把视频保存到手机相册，再从相册选择。',
    );
  }

  static String _levelToContract(AthleteLevel l) => switch (l) {
    AthleteLevel.elite => 'elite',
    AthleteLevel.subElite => 'sub_elite',
    AthleteLevel.college => 'college',
    AthleteLevel.highSchool => 'high_school',
    AthleteLevel.amateur => 'amateur',
  };

  static String _testTypeToContract(SessionTestType t) => switch (t) {
    SessionTestType.blockStart => 'block_start',
    SessionTestType.acceleration => 'acceleration',
    SessionTestType.maxVelocity => 'max_velocity',
    SessionTestType.speedEndurance => 'speed_endurance',
  };

  Widget _pickCard() {
    final picked = _metadata != null;

    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(20),
      decoration: BoxDecoration(
        border: Border.all(
          color: picked ? context.okText : Color(0xFFBDBDBD),
          width: picked ? 1.5 : 1,
        ),
        borderRadius: BorderRadius.circular(8),
        color: picked ? context.okSurface : null,
      ),
      child: Column(
        children: [
          Icon(
            picked ? Icons.check_circle_outline : Icons.video_file_outlined,
            size: 40,
            color: picked ? context.okText : context.faintText,
          ),
          const SizedBox(height: 12),
          Text(
            _fileName ?? '从相册或文件中选择视频',
            textAlign: TextAlign.center,
            style: const TextStyle(fontWeight: FontWeight.w500),
          ),
          if (_fileSize != null) ...[
            const SizedBox(height: 2),
            Text(
              '${(_fileSize! / (1024 * 1024)).toStringAsFixed(1)} MB',
              style: TextStyle(fontSize: 12, color: context.faintText),
            ),
          ],
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              OutlinedButton.icon(
                onPressed: _picking ? null : _pickVideo,
                icon: _picking
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.folder_open),
                label: Text(picked ? '重新选择' : '选择视频文件'),
              ),
              if (picked) ...[
                const SizedBox(width: 8),
                TextButton(onPressed: _reset, child: const Text('清除')),
              ],
            ],
          ),
          if (!picked) ...[
            const SizedBox(height: 8),
            Text(
              '选完会先做一次校验：帧率、分辨率、时长是否达标。\n'
              '不合格会立刻告诉你，不用白等上传。',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 11,
                color: context.faintText,
                height: 1.5,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 校验结果展示
// ---------------------------------------------------------------------------

class _ValidationReport extends StatelessWidget {
  const _ValidationReport({
    required this.validation,
    required this.metadata,
    this.fileSize,
  });

  final VideoValidation validation;
  final VideoMetadata metadata;
  final int? fileSize;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _MetadataTable(metadata: metadata, fileSize: fileSize),
        const SizedBox(height: 12),
        if (validation.issues.isEmpty)
          _IssueBox(
            level: CheckLevel.ok,
            title: '素材检查通过',
            detail: '帧率、分辨率、时长都满足分析要求。',
          )
        else
          for (final issue in validation.issues) ...[
            _IssueBox(
              level: issue.level,
              title: issue.title,
              detail: issue.detail,
              suggestion: issue.suggestion,
            ),
            const SizedBox(height: 8),
          ],
        _CapabilitySummary(validation: validation),
      ],
    );
  }
}

class _MetadataTable extends StatelessWidget {
  const _MetadataTable({required this.metadata, this.fileSize});

  final VideoMetadata metadata;
  final int? fileSize;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Color(0xFFFAFAFA),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: context.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '文件信息',
            style: TextStyle(fontSize: 13, color: context.faintText),
          ),
          const SizedBox(height: 8),
          _row(context, '时长', metadata.durationLabel),
          _row(context, '分辨率', metadata.resolutionLabel),
          _row(context, '声明帧率', metadata.frameRateLabel),
          _row(context, '总帧数', metadata.frameCountLabel),
          if (fileSize != null)
            _row(
              context,
              '文件大小',
              '${(fileSize! / (1024 * 1024)).toStringAsFixed(1)} MB',
            ),
          if (metadata.mimeType != null)
            _row(context, '编码', metadata.mimeType!),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, String k, String v) => Padding(
    padding: const EdgeInsets.only(bottom: 3),
    child: Row(
      children: [
        SizedBox(
          width: 72,
          child: Text(
            k,
            style: TextStyle(fontSize: 12, color: context.faintText),
          ),
        ),
        Expanded(child: Text(v, style: const TextStyle(fontSize: 13))),
      ],
    ),
  );
}

class _IssueBox extends StatelessWidget {
  const _IssueBox({
    required this.level,
    required this.title,
    required this.detail,
    this.suggestion,
  });

  final CheckLevel level;
  final String title;
  final String detail;
  final String? suggestion;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, icon) = switch (level) {
      CheckLevel.ok => (
        context.okSurface,
        context.okText,
        Icons.check_circle_outline,
      ),
      CheckLevel.warning => (
        context.warnSurface,
        context.warnText,
        Icons.warning_amber_outlined,
      ),
      CheckLevel.blocking => (
        context.errorSurface,
        context.errorText,
        Icons.error_outline,
      ),
    };

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: fg),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    color: fg,
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            detail,
            style: const TextStyle(
              fontSize: 13,
              color: Colors.black87,
              height: 1.5,
            ),
          ),
          if (suggestion != null) ...[
            const SizedBox(height: 6),
            Text(
              '建议：$suggestion',
              style: TextStyle(
                fontSize: 13,
                color: context.mutedText,
                height: 1.5,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 明确告诉教练「这次素材能算出哪些指标、算不出哪些」。
///
/// 这一块是整个上传流程里最有价值的部分 ——
/// 它把「帧率不足」这个技术事实，翻译成教练能理解并行动的后果。
class _CapabilitySummary extends StatelessWidget {
  const _CapabilitySummary({required this.validation});

  final VideoValidation validation;

  @override
  Widget build(BuildContext context) {
    final temporal = validation.temporalMetricsUsable;

    return Container(
      padding: EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.subtleSurface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '本次素材可分析的指标',
            style: TextStyle(fontSize: 13, color: context.faintText),
          ),
          const SizedBox(height: 8),
          _line(context, '关节角度（膝角、胫骨角、躯干前倾）', true),
          _line(context, '步频、步幅', true),
          _line(context, '触地时间、腾空时间、占空比', temporal),
          const SizedBox(height: 6),
          Text(
            temporal
                ? '帧率充足，时间类指标可用。'
                : '帧率不足，时间类指标无法计算。'
                      '这不是系统缺陷 —— 触地仅 80–120 毫秒，'
                      '帧率不够就数不出足够多的帧。',
            style: TextStyle(
              fontSize: 11,
              color: context.faintText,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _line(BuildContext context, String label, bool ok) => Padding(
    padding: const EdgeInsets.only(bottom: 4),
    child: Row(
      children: [
        Icon(
          ok ? Icons.check : Icons.remove,
          size: 15,
          color: ok ? context.okText : Color(0xFF9E9E9E),
        ),
        SizedBox(width: 6),
        Expanded(
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              color: ok ? Colors.black87 : context.faintText,
            ),
          ),
        ),
      ],
    ),
  );
}

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------

/// 提交后的阶段。
///
/// 用枚举而不是若干个 bool 组合：多个 bool 会出现
/// 「既在上传又在分析」这类不可能的状态，而枚举天然互斥。
enum _Phase {
  idle, // 还没提交
  uploading, // 正在把视频传到分析服务
  analyzing, // 服务端正在算
  done,
  failed,
}

/// 进度展示。
///
/// 上传与分析分开显示是刻意的：
///   上传慢是网络问题（换个位置、缩短片段），
///   分析慢是算力问题（服务端在忙，只能等）。
///   混成一根进度条会让用户无法判断该不该继续等。
class _ProgressBox extends StatelessWidget {
  const _ProgressBox({
    required this.phase,
    required this.uploadProgress,
    required this.analysisProgress,
    required this.stage,
  });

  final _Phase phase;
  final double uploadProgress;
  final double analysisProgress;
  final String stage;

  @override
  Widget build(BuildContext context) {
    final uploading = phase == _Phase.uploading;
    final value = uploading ? uploadProgress : analysisProgress;

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFE3F2FD),
        borderRadius: BorderRadius.circular(8),
      ),
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
                  uploading ? '正在上传视频' : '正在分析（在电脑上运行）',
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
              ),
              Text(
                '${(value * 100).round()}%',
                style: TextStyle(fontSize: 13, color: context.mutedText),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              // 分析阶段的进度来自服务端的阶段划分，
              // 不是精确的百分比 —— 所以有值时显示，无值时用不确定态。
              value: value > 0 ? value : null,
              minHeight: 5,
            ),
          ),
          if (!uploading && stage.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              stage,
              style: TextStyle(fontSize: 12, color: context.mutedText),
            ),
          ],
          if (uploading) ...[
            const SizedBox(height: 8),
            Text(
              '上传期间请保持 App 在前台、WiFi 不要断开。',
              style: TextStyle(fontSize: 11, color: context.faintText),
            ),
          ],
        ],
      ),
    );
  }
}

/// 分析服务的连接状态提示。
///
/// 未配置时不能只是"按钮点了没反应"—— 那用户会以为是 App 坏了。
class _ServerHint extends StatefulWidget {
  const _ServerHint({required this.onConfigure});

  final VoidCallback onConfigure;

  @override
  State<_ServerHint> createState() => _ServerHintState();
}

class _ServerHintState extends State<_ServerHint> {
  String? _url;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final u = await ServerSettings().baseUrl();
    if (!mounted) return;
    setState(() => _url = u);
  }

  @override
  Widget build(BuildContext context) {
    final configured = _url != null && _url!.isNotEmpty;

    return InkWell(
      onTap: () async {
        widget.onConfigure();
        // 从设置页返回后重新读一次，让状态立即反映改动
        await Future<void>.delayed(Duration(milliseconds: 400));
        await _load();
      },
      borderRadius: BorderRadius.circular(6),
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              configured ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
              size: 15,
              color: configured ? context.okText : context.warnText,
            ),
            SizedBox(width: 6),
            Flexible(
              child: Text(
                configured ? '分析服务：$_url' : '还没设置分析服务 — 点击设置',
                style: TextStyle(
                  fontSize: 11,
                  color: configured ? context.faintText : context.warnText,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: context.errorSurface,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.error_outline, size: 18, color: Color(0xFFC62828)),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: Color(0xFFC62828),
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ),
      ],
    ),
  );
}

// ---------------------------------------------------------------------------
// 静态内容
// ---------------------------------------------------------------------------

class _NeedAthleteFirst extends StatelessWidget {
  const _NeedAthleteFirst();

  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: context.warnSurface,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(
      children: [
        Icon(Icons.info_outline, color: Color(0xFFE65100), size: 32),
        SizedBox(height: 12),
        Text(
          '请先添加运动员',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        SizedBox(height: 6),
        Text(
          '分析结果需要归到具体运动员名下。\n'
          '请先到「运动员」页添加，再回来上传。',
          textAlign: TextAlign.center,
          style: TextStyle(color: context.mutedText, height: 1.6),
        ),
      ],
    ),
  );
}

class _StepHeader extends StatelessWidget {
  const _StepHeader({
    required this.index,
    required this.title,
    required this.done,
  });

  final int index;
  final String title;
  final bool done;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      CircleAvatar(
        radius: 12,
        backgroundColor: done ? context.okText : context.hairline,
        child: done
            ? const Icon(Icons.check, size: 14, color: Colors.white)
            : Text(
                '$index',
                style: TextStyle(fontSize: 12, color: context.mutedText),
              ),
      ),
      const SizedBox(width: 8),
      Text(
        title,
        style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ],
  );
}

/// 保存成功提示。
class _SuccessBox extends StatelessWidget {
  const _SuccessBox({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: context.okSurface,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      children: [
        const Icon(
          Icons.check_circle_outline,
          size: 18,
          color: Color(0xFF2E7D32),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: Color(0xFF2E7D32),
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ),
      ],
    ),
  );
}

/// 拍摄要点。
///
/// ## 为什么按视角分开写
///
/// 三个视角测的是**完全不同的量**，而且互不通用：
///
///     侧面  →  矢状面角度（躯干前倾、膝角、胫骨角）与时间量（触地、腾空）
///     正面  →  额状面（骨盆是否下沉、膝是否内扣、着地是否过中线）
///     背面  →  同上，但**左右判读相反** —— 这是最容易搞错的地方
///
/// 所以拍法要求也不同。原来只写了「机位固定在侧面」，
/// 用户拍正面/背面时得不到任何指导，拍出来的素材往往不可用。
///
/// ## 为什么分成「通用」和「分视角」两块
///
/// 帧率、曝光、防抖这几条对三个视角都成立，重复写三遍会让用户
/// 以为它们是不同要求。分成两块，用户知道哪些是共同的。
class _ShootingGuide extends StatelessWidget {
  const _ShootingGuide({this.view = 'side'});

  /// 当前选择的视角。用于**默认展开**对应那一节。
  final String view;

  /// 三个视角通用的要求。
  static const _commonItems = <(String, String)>[
    (
      '帧率 ≥120 fps',
      '用手机「慢动作」模式。低于这个值，触地时间、腾空时间都测不准 —— '
          '30 fps 每帧间隔 33 毫秒，而触地本身只有 80–120 毫秒。',
    ),
    ('曝光与对焦锁定', '自动曝光会让关键点位置随亮度漂移。拍摄前长按屏幕锁定，或用专业模式。'),
    (
      '关闭电子防抖',
      '防抖会引入帧间几何变形（画面被拉伸或旋转），反而让测量不准。'
          '光学防抖可以保留。',
    ),
    ('运动员占画面高度 1/3 以上', '太小人就糊，关键点会飘。宁可只拍有效的一段，也不要拍成一个人影。'),
    (
      '背景尽量干净',
      '画面里出现路人时，姿态识别可能落到别人身上。'
          '训练场边上有人走动时尤其要注意。',
    ),
  ];

  /// 按视角的具体要求。
  static const _viewItems = <String, _ViewGuide>{
    'side': _ViewGuide(
      label: '侧面',
      icon: Icons.compare_arrows,
      measures: '测得出：躯干前倾、膝角、胫骨角、踝角、步频、触地与腾空时间',
      items: [
        ('机位距离 8–15 米，高度约等于髋高', '镜头光轴尽量垂直于跑动方向。太高或太低都会让角度看起来偏大或偏小。'),
        ('让分道线入画', '有分道线才能把画面尺寸换算成实际距离，步幅这类指标才算得出来。'),
        (
          '镜头跟随要平滑',
          '运动员尽量保持在画面中央 —— 越靠边透视误差越大。'
              '这也是本 App 在跟拍素材上不算绝对速度的原因：'
              '画面里的位移 = 运动员位移 + 镜头位移，单目分不开。',
        ),
      ],
    ),
    'front': _ViewGuide(
      label: '正面',
      icon: Icons.arrow_downward,
      measures: '测得出：骨盆下沉、膝内扣、着地是否过中线、躯干左右晃动',
      items: [
        (
          '机位在跑道正前方，运动员朝镜头跑来',
          '必须正对。偏一点就会有左右透视差，额状面角度全错，'
              '而且错得看不出来 —— 数值看起来完全正常。',
        ),
        ('镜头高度齐胸或齐腰', '太高会俯视，把左右差异压扁；太低会仰视，夸大差异。'),
        (
          '不要跟随平移',
          '正面拍摄时镜头固定即可，让运动员从远到近。'
              '跟随会改变透视，破坏左右对称性 —— 而对称性正是额状面指标的基础。',
        ),
        ('尽量在直道上拍', '弯道上运动员身体本来就向内倾，会被误读成姿势问题。'),
      ],
    ),
    'back': _ViewGuide(
      label: '背面',
      icon: Icons.arrow_upward,
      measures: '测得出：与正面相同的额状面指标',
      items: [
        ('机位在运动员身后，拍他跑远', '与正面一样必须正对跑道。'),
        (
          '⚠️ 左右判读与正面相反',
          '背面拍摄时画面左边的腿是运动员的**左腿**。'
              'App 已按拍摄视角做了转换，但你看图时仍要留意，'
              '别和正面素材混着比较。',
        ),
        (
          '不要把正面和背面的素材当成同一组数据',
          '两者测的是同一类指标，但左右基准不同，'
              '混在一起看会得出矛盾的结论。',
        ),
      ],
    ),
  };

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.okSurface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                Icons.tips_and_updates_outlined,
                size: 18,
                color: Color(0xFF2E7D32),
              ),
              SizedBox(width: 6),
              Text(
                '拍摄要点',
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF2E7D32),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // ---- 通用要求 ----
          const _GuideSectionTitle('三个视角都适用'),
          const SizedBox(height: 8),
          for (final (title, detail) in _commonItems) ...[
            _GuideItem(title: title, detail: detail),
            const SizedBox(height: 9),
          ],

          const Divider(height: 24, color: Color(0x222E7D32)),

          // ---- 分视角要求 ----
          const _GuideSectionTitle('按视角的额外要求'),
          const SizedBox(height: 6),
          Text(
            '三个视角量的东西不一样，不能混用。'
            '同一个指标换个视角拍，数值会完全变味。',
            style: TextStyle(
              fontSize: 11.5,
              color: context.mutedText,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 12),

          for (final entry in _viewItems.entries) ...[
            _ViewGuideCard(
              data: entry.value,
              initiallyExpanded: entry.key == view,
            ),
            const SizedBox(height: 8),
          ],
        ],
      ),
    );
  }
}

/// 一条要点的标题 + 说明。
class _GuideItem extends StatelessWidget {
  const _GuideItem({required this.title, required this.detail});

  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
        ),
        Text(
          detail,
          style: TextStyle(fontSize: 12, color: context.mutedText, height: 1.4),
        ),
      ],
    );
  }
}

class _GuideSectionTitle extends StatelessWidget {
  const _GuideSectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 12.5,
        fontWeight: FontWeight.w700,
        color: Color(0xFF2E7D32),
        letterSpacing: 0.3,
      ),
    );
  }
}

/// 单个视角的要点卡片。
///
/// 可折叠 —— 三个视角全展开会让这一屏特别长，
/// 而用户一次只拍一个视角，没必要看另外两个的细节。
class _ViewGuideCard extends StatelessWidget {
  const _ViewGuideCard({required this.data, required this.initiallyExpanded});

  final _ViewGuide data;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    return Theme(
      // 去掉 ExpansionTile 的分隔线，让卡片看起来是一体的
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.72),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: initiallyExpanded ? context.okText : const Color(0x222E7D32),
            width: initiallyExpanded ? 1.3 : 1,
          ),
        ),
        child: ExpansionTile(
          initiallyExpanded: initiallyExpanded,
          tilePadding: const EdgeInsets.symmetric(horizontal: 12),
          childrenPadding: EdgeInsets.fromLTRB(12, 0, 12, 12),
          dense: true,
          title: Row(
            children: [
              Icon(data.icon, size: 16, color: context.okText),
              const SizedBox(width: 6),
              Text(
                data.label,
                style: const TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              if (initiallyExpanded) ...[
                const SizedBox(width: 6),
                Container(
                  padding: EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(
                    color: context.okText,
                    borderRadius: BorderRadius.circular(3),
                  ),
                  child: const Text(
                    '当前选择',
                    style: TextStyle(fontSize: 10, color: Colors.white),
                  ),
                ),
              ],
            ],
          ),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                data.measures,
                style: const TextStyle(
                  fontSize: 11.5,
                  color: Color(0xFF1B5E20),
                  height: 1.4,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
            const SizedBox(height: 10),
            for (final (title, detail) in data.items) ...[
              _GuideItem(title: title, detail: detail),
              const SizedBox(height: 8),
            ],
          ],
        ),
      ),
    );
  }
}

/// 一个视角的拍摄要点。
class _ViewGuide {
  const _ViewGuide({
    required this.label,
    required this.icon,
    required this.measures,
    required this.items,
  });

  final String label;
  final IconData icon;

  /// 这个视角**能测出什么**。
  ///
  /// 写这一行是因为用户最常问的是"我该拍哪个视角" ——
  /// 与其解释几何原理，不如直接告诉他每个视角能得到什么。
  final String measures;

  final List<(String, String)> items;
}
