import 'package:flutter/material.dart';

import '../data/analysis_repository.dart';
import '../data/analysis_server_client.dart';
import '../data/report_view_model.dart';
import '../models/models.dart';
import '../widgets/finding_card.dart';
import '../widgets/metric_row.dart';
import '../widgets/quality_banner.dart';
import '../widgets/app_colors.dart';
import 'server_settings_page.dart' show ServerSettings;

/// 报告页。
///
/// 首屏必须让教练不滚动就看到「该改什么」—— 这是报告存在的唯一目的。
/// 见 docs/09-报告与指导解析规范.md §1。
///
/// 两种进入方式：
///   · initialResult 为空  —— 开发模式，从内置假数据加载，右上角可切换三种状态
///   · initialResult 有值  —— 从数据页点进来，直接展示真实分析结果
class ReportPage extends StatefulWidget {
  const ReportPage({super.key, this.initialResult});

  final AnalysisResult? initialResult;

  @override
  State<ReportPage> createState() => _ReportPageState();
}

class _ReportPageState extends State<ReportPage> {
  final _repo = const FixtureDataSource();

  /// 分析服务地址。用来把关键帧图的**相对路径**拼成完整 URL。
  ///
  /// 为什么必须在这里读：报告里的 `image_url` 形如
  /// `keyframes/<任务ID>/f000014_touchdown.jpg` —— 是相对路径。
  /// 分析引擎不知道自己被哪个地址访问（见 analyze.py 的
  /// keyframe_url_prefix 注释），所以拼接只能由客户端做。
  ///
  /// 为空（用户还没连过服务）时，关键帧图解会给出提示而不是空白图。
  String? _baseUrl;

  /// 为空表示还没拿到数据；从数据页进入时构造时即有值
  late AnalysisResult? _result = widget.initialResult;
  String _scenario = 'normal';
  Object? _error;
  late bool _loading = widget.initialResult == null;

  /// 开发模式才会显示假数据切换器。从数据页进来是真实结果，不该能切换。
  bool get _isDevMode => widget.initialResult == null;

  @override
  void initState() {
    super.initState();
    _loadBaseUrl();
    if (_isDevMode) _load();
  }

  /// 读取已保存的服务地址。
  ///
  /// 失败不报错：报告的文字部分在没网时也能看，
  /// 不该因为取不到图片地址就让整页失败。
  Future<void> _loadBaseUrl() async {
    try {
      final url = await ServerSettings().baseUrl();
      if (!mounted) return;
      setState(() => _baseUrl = url);
    } catch (_) {
      // 读不到就保持 null，关键帧区会给出相应提示
    }
  }

  /// 把相对图片路径拼成完整 URL；地址缺失时返回 null。
  ///
  /// 拼接逻辑本身放在 ServerConfig.resolveUrl —— 那里有单元测试，
  /// 因为拼错的后果只是一张破图，不会抛异常，靠人工看很难发现。
  String? _imageUrlFor(String relative) =>
      ServerConfig.resolveUrl(_baseUrl, relative);

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await _repo.getAnalysis(_scenario);
      if (!mounted) return;
      setState(() {
        _result = result;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('YUcoach · 跑姿分析报告'),
        actions: [
          // 仅在开发模式（无真实数据）下提供假数据切换。
          // 从数据页点进来的真实报告不该能切换状态。
          if (_isDevMode)
            PopupMenuButton<String>(
              tooltip: '切换数据状态（开发用）',
              icon: const Icon(Icons.science_outlined),
              onSelected: (v) {
                setState(() => _scenario = v);
                _load();
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'normal', child: Text('① 指标正常')),
                PopupMenuItem(value: 'lowConfidence', child: Text('② 低置信')),
                PopupMenuItem(value: 'empty', child: Text('③ 全部测不出')),
              ],
            ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('加载失败：$_error'),
        ),
      );
    }

    final r = _result!;
    final metrics = r.metrics.map(toMetricView).toList();
    final sideMetrics = metrics
        .where((m) => _viewOf(r, m.metricId) == SessionView.side)
        .toList();
    final frontalMetrics = metrics
        .where((m) => _viewOf(r, m.metricId) != SessionView.side)
        .toList();

    final banner = qualityBannerFor(r.qualityScore);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _Header(result: r),
        if (banner != QualityBanner.none) ...[
          const SizedBox(height: 12),
          QualityBannerBar(banner: banner),
        ],
        const SizedBox(height: 16),
        _Summary(result: r),

        // 关键帧图解。数据不足时没有关键帧，这里要给出说明而不是留白。
        const SizedBox(height: 24),
        _SectionTitle('关键帧图解'),
        const SizedBox(height: 8),
        _KeyframeSection(result: r, resolveImage: _imageUrlFor),

        // 指标对比：必须按视角分组。
        // 侧面与额状面测的是完全不同的几何量，混在一起会让教练误读。
        const SizedBox(height: 24),
        _SectionTitle('指标对比'),
        const SizedBox(height: 8),
        if (sideMetrics.isNotEmpty) ...[
          _ViewGroupLabel('侧面视角（矢状面）'),
          ...sideMetrics.map((m) => MetricRow(view: m)),
          const SizedBox(height: 16),
        ],
        if (frontalMetrics.isNotEmpty) ...[
          _ViewGroupLabel('正面 / 背面视角（额状面）'),
          ...frontalMetrics.map((m) => MetricRow(view: m)),
        ],

        const SizedBox(height: 24),
        _SectionTitle('指导解析'),
        const SizedBox(height: 8),
        _FindingsSection(result: r),

        const SizedBox(height: 24),
        _Appendix(result: r),
        const SizedBox(height: 32),
      ],
    );
  }

  /// 指标所属视角来自指标本身，不来自 Session —— 同一份报告可能同时包含
  /// 侧面与额状面指标（教练传了两段视频时）。
  SessionView _viewOf(AnalysisResult result, String metricId) {
    final m = result.metrics.firstWhere((x) => x.metricId == metricId);
    return m.view;
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final s = result.session;
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${s.athlete.name} · ${s.athlete.event} · ${result.versions.modelVersion.contains('manual-contact') ? '人工确认计时' : '运动分析'}',
          style: theme.textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(height: 4),
        Row(
          children: [
            Text(
              s.recordedAt.split('T').first,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: context.mutedText,
              ),
            ),
            const SizedBox(width: 12),
            _Chip(label: '${viewLabel(s.view)}视角'),
            const SizedBox(width: 8),
            _Chip(label: '拍摄质量 ${result.qualityScore.round()} 分'),
          ],
        ),
        SizedBox(height: 6),
        Text(
          '分析口径 ${result.versions.algoVersion} · '
          '模型 ${result.versions.modelVersion} · '
          '规则 ${result.versions.ruleVersion} · '
          '标准值 ${result.versions.stdVersion}',
          style: theme.textTheme.bodySmall?.copyWith(color: context.faintText),
        ),
      ],
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = result.summary;
    final insufficient = result.metrics
        .where((m) => m.insufficient != null || m.value == null)
        .length;

    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.subtleSurface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            s.headline,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          SizedBox(height: 8),
          Text(
            '发现 ${s.majorCount + s.minorCount} 处可改进'
            '${insufficient > 0 ? " · $insufficient 项数据不足" : ""}',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.mutedText,
            ),
          ),
        ],
      ),
    );
  }
}

/// 把相对图片路径解析成完整 URL 的函数。
///
/// 返回 null 表示「解析不了」—— 通常是用户还没配置分析服务地址，
/// 或读了设置但没读到。调用方要据此给出提示，而不是显示一张破图。
typedef ImageUrlResolver = String? Function(String relativePath);

class _KeyframeSection extends StatelessWidget {
  const _KeyframeSection({required this.result, required this.resolveImage});

  final AnalysisResult result;
  final ImageUrlResolver resolveImage;

  @override
  Widget build(BuildContext context) {
    final keyframes = result.keyframes;

    if (keyframes.isEmpty) {
      // 数据不足时没有关键帧。不能留白 —— 留白会被理解成「系统坏了」。
      return const _Placeholder(
        text:
            '本次没有可用的关键帧。\n'
            '关键帧来自识别出的着地、离地等动作时刻；'
            '本次素材未能识别出完整步次，因此无法生成图解。',
      );
    }

    return Column(
      children: keyframes
          .map(
            (k) => _KeyframeCard(
              keyframe: k,
              view: result.session.view,
              resolveImage: resolveImage,
            ),
          )
          .toList(),
    );
  }
}

/// 关键帧图片。
///
/// 三种状态都必须有明确表现 —— 空着会被当成「系统坏了」：
///   加载中  进度指示
///   加载失败 说明原因（最常见的是分析服务没开）
///   未配置  提示去哪配地址
class _KeyframeImage extends StatelessWidget {
  const _KeyframeImage({required this.url, required this.frameIndex});

  /// 完整 URL；null 表示没能解析出地址。
  final String? url;
  final int frameIndex;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    Widget message(IconData icon, String title, String hint) => Container(
      height: 180,
      width: double.infinity,
      decoration: BoxDecoration(
        color: context.subtleSurface,
        borderRadius: BorderRadius.circular(6),
      ),
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 28, color: context.faintText),
          const SizedBox(height: 8),
          Text(
            title,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: context.mutedText,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            hint,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: context.faintText,
            ),
          ),
        ],
      ),
    );

    final u = url;
    if (u == null || u.isEmpty) {
      return message(
        Icons.cloud_off_outlined,
        '还没连接分析服务',
        '关键帧图存在电脑上，需要先在「我的 → 分析服务」里填地址。',
      );
    }

    return ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: Image.network(
        u,
        height: 180,
        width: double.infinity,
        fit: BoxFit.cover,
        loadingBuilder: (ctx, child, progress) {
          if (progress == null) return child;
          // 局域网下通常一闪而过，但大图或慢 WiFi 时要有反馈
          final total = progress.expectedTotalBytes;
          final value = total != null
              ? progress.cumulativeBytesLoaded / total
              : null;
          return Container(
            height: 180,
            alignment: Alignment.center,
            color: context.subtleSurface,
            child: SizedBox(
              width: 28,
              height: 28,
              child: CircularProgressIndicator(value: value, strokeWidth: 2.5),
            ),
          );
        },
        errorBuilder: (ctx, err, stack) => message(
          Icons.broken_image_outlined,
          '取不到这张图（帧 $frameIndex）',
          '确认电脑上的分析服务还开着、手机与电脑在同一网络。\n'
              '图片按任务保存在电脑上，服务关闭后就取不到了。',
        ),
      ),
    );
  }
}

class _KeyframeCard extends StatelessWidget {
  const _KeyframeCard({
    required this.keyframe,
    required this.view,
    required this.resolveImage,
  });

  final Keyframe keyframe;
  final SessionView view;
  final ImageUrlResolver resolveImage;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      margin: EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        border: Border.all(color: context.hairline),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
            child: Row(
              children: [
                Text(
                  '${eventLabel(keyframe.event)} · '
                  '第 ${keyframe.stepIndex ?? "?"} 步 · '
                  '${phaseLabel(keyframe.phase)}',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w500,
                  ),
                ),
                Spacer(),
                _Chip(label: '${viewLabel(view)}视角'),
              ],
            ),
          ),
          // 图片区域：服务端渲染好的骨骼标注图 ——
          // 含骨架连线、角度弧线与尺度条（见 backend/analysis/keyframes.py）。
          //
          // ⚠️ 这里曾经是一个**写死的文字占位块**。数据一直有
          //    （Keyframe.imageUrl 早就解析了），只是没人用它取图，
          //    于是教练永远看不到标注图。2026-10-13 接通。
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: _KeyframeImage(
              url: resolveImage(keyframe.imageUrl),
              frameIndex: keyframe.frameIndex,
            ),
          ),
          // 尺度条。跟踪拍摄下每帧的像素米比不同，不标注会让教练误判体型变化。
          Padding(
            padding: EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Row(
              children: [
                Container(
                  width: 42,
                  height: 6,
                  decoration: BoxDecoration(
                    border: Border.all(color: context.mutedText),
                  ),
                ),
                SizedBox(width: 6),
                Text(
                  '0.5 m'
                  '${keyframe.pixelsPerMeter != null ? "（${keyframe.pixelsPerMeter!.round()} px/m）" : ""}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: context.mutedText,
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
            child: Wrap(
              spacing: 16,
              runSpacing: 4,
              children: keyframe.annotations
                  .map(
                    (a) => Text(
                      '${a.metricId == "shank_angle_touchdown"
                          ? "胫骨角"
                          : a.metricId == "knee_angle_touchdown"
                          ? "膝角"
                          : a.metricId == "trunk_lean"
                          ? "躯干前倾"
                          : a.metricId} '
                      '${a.value.toStringAsFixed(1)}${unitLabel(a.unit)}'
                      '${a.refLow != null ? "  [标准 ${a.refLow!.toStringAsFixed(0)}–${a.refHigh!.toStringAsFixed(0)}°]" : ""}',
                      style: theme.textTheme.bodyMedium,
                    ),
                  )
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class _FindingsSection extends StatelessWidget {
  const _FindingsSection({required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final findings = result.findings;

    // 报告主体最多 3 条：给教练 10 条问题等于没给，他一条都不会改。
    final actionable = findings
        .where(
          (f) =>
              f.severity == FindingSeverity.major ||
              f.severity == FindingSeverity.minor,
        )
        .take(3)
        .toList();
    final insufficient = findings
        .where((f) => f.severity == FindingSeverity.insufficientData)
        .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ...actionable.map((f) => FindingCard(finding: f)),
        if (actionable.isEmpty && insufficient.isEmpty)
          const _Placeholder(text: '本次未生成结论。'),
        ...insufficient.map(
          (f) => FindingCard(finding: f, isInsuffcient: true),
        ),
      ],
    );
  }
}

class _Appendix extends StatelessWidget {
  const _Appendix({required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = result.session;
    final v = s.capture.fpsVerify;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Color(0xFFFAFAFA),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: context.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '附录 · 数据可信度',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          // 帧率是必填字段（可空类型表示值本身可为 null），故用直接访问
          _kv(
            context,
            '帧率声明 / 校验',
            '${s.capture.fpsDeclared?.toStringAsFixed(1) ?? "未知"} fps → '
                '${s.capture.fpsVerified?.toStringAsFixed(1) ?? "无法校验"} fps',
          ),
          _kv(context, '帧率校验方法', v.methods.map((m) => m.toJson()).join('、')),
          _kv(context, '校验一致性', '${v.agreementPct.toStringAsFixed(1)}%'),
          _kv(context, '镜头运动', cameraMotionLabel(s.cameraMotion.level)),
          _kv(context, '参考尺度', referenceScaleLabel(s.referenceScale.method)),
          _kv(
            context,
            '畸变校正',
            s.capture.distortionCorrected == true ? '已执行' : '未执行',
          ),
          if (result.perspectiveErrorEstimate != null)
            _kv(
              context,
              '透视误差量级',
              '±${result.perspectiveErrorEstimate!.toStringAsFixed(1)}°',
            ),
          SizedBox(height: 12),
          Text(
            '本报告基于二维视频分析，用于技术动作的观察与趋势对比。'
            '不构成医学诊断，不替代教练的专业判断，'
            '不可用于反推地面反作用力或关节负荷。'
            '可靠性等级为 C 的指标仅适用于趋势对比。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: context.mutedText,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _kv(BuildContext context, String k, String v) => Padding(
    padding: const EdgeInsets.only(bottom: 4),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 110,
          child: Text(k, style: TextStyle(color: context.mutedText)),
        ),
        Expanded(child: Text(v)),
      ],
    ),
  );
}

class _Placeholder extends StatelessWidget {
  const _Placeholder({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.subtleSurface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(color: context.mutedText, height: 1.5),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Text(
    text,
    style: Theme.of(context).textTheme.titleMedium
        ?.copyWith(fontWeight: FontWeight.w600),
  );
}

class _ViewGroupLabel extends StatelessWidget {
  const _ViewGroupLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Text(
      text,
      style: TextStyle(
        fontSize: 13,
        color: context.faintText,
        letterSpacing: 0.5,
      ),
    ),
  );
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      color: context.okSurface,
      borderRadius: BorderRadius.circular(4),
    ),
    child: Text(label, style: const TextStyle(fontSize: 12)),
  );
}

// ---------------------------------------------------------------------------
// 枚举的用户化措辞。界面不得直接显示契约里的英文枚举值。
// ---------------------------------------------------------------------------

String viewLabel(SessionView v) => switch (v) {
  SessionView.side => '侧面',
  SessionView.front => '正面',
  SessionView.back => '背面',
};

String eventLabel(TimeBaseEvent e) => switch (e) {
  TimeBaseEvent.touchdown => '着地',
  TimeBaseEvent.midstance => '支撑中期',
  TimeBaseEvent.toeOff => '离地',
  TimeBaseEvent.swingPeak => '摆动最高点',
  TimeBaseEvent.setPosition => '预备就位',
  TimeBaseEvent.gunFire => '发令',
  TimeBaseEvent.blockClearance => '蹬离起跑器',
  TimeBaseEvent.finish => '终点',
};

String phaseLabel(MetricPhase p) => switch (p) {
  MetricPhase.setValue => '预备',
  MetricPhase.start => '起动',
  MetricPhase.acceleration => '加速段',
  MetricPhase.transition => '过渡段',
  MetricPhase.maxVelocity => '途中跑',
  MetricPhase.deceleration => '减速段',
  MetricPhase.wholeRun => '所选区间（未分期）',
};

String cameraMotionLabel(CameraMotionLevel? l) => switch (l) {
  CameraMotionLevel.fixed => '固定机位',
  CameraMotionLevel.slightPan => '轻度跟随',
  CameraMotionLevel.strongPan => '明显跟随（精度受限）',
  null => '未知',
};

String referenceScaleLabel(ReferenceScaleMethod? m) => switch (m) {
  ReferenceScaleMethod.laneLine => '跑道分道线（精度高）',
  ReferenceScaleMethod.calibrationRod => '标定杆',
  ReferenceScaleMethod.heightDerived => '由身高推算（误差约 5-10%）',
  ReferenceScaleMethod.none => '无（位移类指标不可用）',
  null => '未知',
};
