import 'package:flutter/material.dart';

import '../data/athlete_repository.dart';
import '../data/session_repository.dart';
import '../domain/athlete_record.dart';
import '../domain/session_record.dart';
import '../models/models.dart';
import 'athlete_list_page.dart' show eventLabelOf;
import 'refreshable.dart';
import 'report_page.dart';
import '../widgets/app_colors.dart';

/// 运动数据：汇总概览 + 按运动员查看历史记录。
///
/// 这是教练回顾训练效果的地方，所以重点是「谁、什么时候、测出了什么」。
class DataPage extends StatefulWidget {
  const DataPage({
    super.key,
    required this.athletes,
    required this.sessions,
  });

  final AthleteRepository athletes;
  final SessionRepository sessions;

  @override
  State<DataPage> createState() => DataPageState();
}

/// 公开（非 `_` 前缀）是为了让主界面能通过 `GlobalKey<DataPageState>`
/// 在切 Tab 时调用 reload()。见 refreshable.dart 的说明。
class DataPageState extends State<DataPage> implements Refreshable {
  List<AthleteRecord>? _athletes;
  List<SessionRecord> _all = [];
  Map<String, int> _counts = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// 切到本页时由主界面调用，重新读全部数据。
  @override
  Future<void> reload() => _load();

  Future<void> _load() async {
    final athletes = await widget.athletes.list();
    final sessions = await widget.sessions.list();
    final counts = await widget.sessions.countByAthlete();
    if (!mounted) return;
    setState(() {
      _athletes = athletes;
      _all = sessions;
      _counts = counts;
    });
  }

  Future<void> _openSession(SessionRecord s) async {
    final analysisId = s.analysisId;
    if (analysisId == null) {
      // 尚未分析：说明原因与下一步，而不是给个点不动的列表项
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_pendingReason(s)),
          duration: const Duration(seconds: 4),
        ),
      );
      return;
    }

    final result = await widget.sessions.loadAnalysis(analysisId);
    if (!mounted) return;

    if (result == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('分析结果读取失败，可能数据已损坏')),
      );
      return;
    }

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ReportPage(initialResult: result),
      ),
    );
  }

  String _pendingReason(SessionRecord s) => switch (s.status) {
        SessionStatus.uploaded => '视频已选好但还没提交分析',
        SessionStatus.queued => '分析已排队，等待服务端处理',
        SessionStatus.processing => '分析进行中',
        SessionStatus.failed => '分析失败：${s.errorMessage ?? "未知原因"}',
        SessionStatus.done => '分析已完成',
      };

  @override
  Widget build(BuildContext context) {
    final athletes = _athletes;

    return Scaffold(
      appBar: AppBar(title: const Text('运动数据')),
      body: athletes == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _SummaryCards(
                    athleteCount: athletes.length,
                    sessions: _all,
                  ),
                  const SizedBox(height: 20),
                  if (_all.isNotEmpty) ...[
                    const _SectionLabel('最近记录'),
                    const SizedBox(height: 8),
                    for (final s in _all.take(5))
                      _SessionTile(
                        session: s,
                        onTap: () => _openSession(s),
                      ),
                    const SizedBox(height: 20),
                  ],
                  const _SectionLabel('按运动员查看'),
                  const SizedBox(height: 8),
                  if (athletes.isEmpty)
                    const _EmptyHint(
                      icon: Icons.groups_outlined,
                      title: '还没有运动员',
                      detail: '先到「运动员」页添加，上传视频分析后这里会出现记录。',
                    )
                  else
                    for (final a in athletes)
                      _AthleteDataTile(
                        athlete: a,
                        sessionCount: _counts[a.athleteId] ?? 0,
                        onTap: () => _openAthlete(a),
                      ),
                  const SizedBox(height: 32),
                ],
              ),
            ),
    );
  }

  Future<void> _openAthlete(AthleteRecord a) async {
    final sessions = await widget.sessions.list(athleteId: a.athleteId);
    if (!mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => _AthleteSessionsPage(
          athlete: a,
          sessions: sessions,
          onOpen: (s) async {
            final result = s.analysisId == null
                ? null
                : await widget.sessions.loadAnalysis(s.analysisId!);
            if (!mounted || result == null) return;
            await Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => ReportPage(initialResult: result),
              ),
            );
          },
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _SummaryCards extends StatelessWidget {
  const _SummaryCards({required this.athleteCount, required this.sessions});

  final int athleteCount;
  final List<SessionRecord> sessions;

  @override
  Widget build(BuildContext context) {
    final analyzed = sessions.where((s) => s.isAnalyzed).length;
    final pending = sessions.where((s) => !s.isAnalyzed && !s.isFailed).length;
    final failed = sessions.where((s) => s.isFailed).length;

    return Row(
      children: [
        _Card(label: '运动员', value: '$athleteCount'),
        const SizedBox(width: 8),
        _Card(label: '已完成', value: '$analyzed'),
        const SizedBox(width: 8),
        _Card(label: '待处理', value: '$pending'),
        const SizedBox(width: 8),
        _Card(
          label: '失败',
          value: '$failed',
          highlight: failed > 0,
        ),
      ],
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({
    required this.label,
    required this.value,
    this.highlight = false,
  });

  final String label;
  final String value;
  final bool highlight;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Container(
          padding: EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: highlight
                ? context.errorSurface
                : context.subtleSurface,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            children: [
              Text(
                value,
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w600,
                  color: highlight ? context.errorText : null,
                ),
              ),
              const SizedBox(height: 2),
              Text(label,
                  style: TextStyle(fontSize: 11, color: context.mutedText)),
            ],
          ),
        ),
      );
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: TextStyle(fontSize: 13, color: context.faintText),
      );
}

class _SessionTile extends StatelessWidget {
  const _SessionTile({required this.session, required this.onTap});

  final SessionRecord session;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: Color(0xFFE0E0E0)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              _StatusDot(status: session.status),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          session.athleteName,
                          style: theme.textTheme.bodyLarge
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          _dateLabel(session.recordedAt),
                          style: TextStyle(
                              fontSize: 12, color: context.faintText),
                        ),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(
                      _subtitle(session),
                      style: TextStyle(
                          fontSize: 12, color: context.mutedText),
                    ),
                  ],
                ),
              ),
              if (session.qualityScore != null)
                _QualityBadge(score: session.qualityScore!),
              Icon(Icons.chevron_right, color: context.hairline),
            ],
          ),
        ),
      ),
    );
  }

  static String _dateLabel(String iso) {
    if (iso.length < 16) return iso;
    return '${iso.substring(0, 10)} ${iso.substring(11, 16)}';
  }

  static String _subtitle(SessionRecord s) {
    final parts = <String>[
      viewLabel(s.view),
      testTypeLabel(s.testType),
      s.frameRateLabel,
    ];
    if (s.isFailed) parts.add('分析失败');
    return parts.join(' · ');
  }
}

/// 状态用颜色**加符号**表达，不只靠颜色 ——
/// 红绿色盲在男性中约占 8%，只靠颜色区分是不可用的。
class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.status});

  final SessionStatus status;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status) {
      SessionStatus.done => (context.okText, Icons.check),
      SessionStatus.failed => (context.errorText, Icons.close),
      SessionStatus.processing => (const Color(0xFF1565C0), Icons.sync),
      SessionStatus.queued => (Color(0xFFF57C00), Icons.schedule),
      SessionStatus.uploaded => (Color(0xFF9E9E9E), Icons.upload),
    };

    return Container(
      width: 28,
      height: 28,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      child: Icon(icon, size: 16, color: Colors.white),
    );
  }
}

class _QualityBadge extends StatelessWidget {
  const _QualityBadge({required this.score});

  final double score;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = score >= 75
        ? (context.okSurface, context.okText)
        : score >= 55
            ? (context.warnSurface, context.warnText)
            : (context.errorSurface, context.errorText);

    return Container(
      margin: const EdgeInsets.only(right: 6),
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '${score.round()}',
        style: TextStyle(
            fontSize: 12, fontWeight: FontWeight.w600, color: fg),
      ),
    );
  }
}

class _AthleteDataTile extends StatelessWidget {
  const _AthleteDataTile({
    required this.athlete,
    required this.sessionCount,
    required this.onTap,
  });

  final AthleteRecord athlete;
  final int sessionCount;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Card(
        margin: const EdgeInsets.only(bottom: 8),
        elevation: 0,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: Color(0xFFE0E0E0)),
          borderRadius: BorderRadius.circular(8),
        ),
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor: context.okSurface,
            child: Text(athlete.name.characters.first),
          ),
          title: Text(athlete.name),
          subtitle: Text(
            sessionCount == 0
                ? '${eventLabelOf(athlete.event)} · 暂无分析记录'
                : '${eventLabelOf(athlete.event)} · $sessionCount 次记录',
            style: const TextStyle(fontSize: 12),
          ),
          trailing: Icon(Icons.chevron_right, color: context.hairline),
          onTap: onTap,
        ),
      );
}

/// 某个运动员的全部记录。
class _AthleteSessionsPage extends StatelessWidget {
  const _AthleteSessionsPage({
    required this.athlete,
    required this.sessions,
    required this.onOpen,
  });

  final AthleteRecord athlete;
  final List<SessionRecord> sessions;
  final Future<void> Function(SessionRecord) onOpen;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${athlete.name} · 记录')),
      body: sessions.isEmpty
          ? const _EmptyHint(
              icon: Icons.videocam_off_outlined,
              title: '还没有记录',
              detail: '到「上传」页选一段视频，分析完成后记录会出现在这里。',
            )
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _AthleteProfileCard(athlete: athlete),
                const SizedBox(height: 16),
                for (final s in sessions)
                  _SessionTile(session: s, onTap: () => onOpen(s)),
              ],
            ),
    );
  }
}

class _AthleteProfileCard extends StatelessWidget {
  const _AthleteProfileCard({required this.athlete});

  final AthleteRecord athlete;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, String)>[
      ('项目', eventLabelOf(athlete.event)),
      ('水平', levelLabelOf(athlete.level)),
      ('身高', athlete.hasHeight ? '${athlete.heightCm!.round()} cm' : '未填'),
      if (athlete.weightKg != null)
        ('体重', '${athlete.weightKg!.round()} kg'),
      if (athlete.note != null && athlete.note!.isNotEmpty)
        ('备注', athlete.note!),
    ];

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Color(0xFFFAFAFA),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: context.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final (k, v) in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 48,
                    child: Text(k,
                        style: TextStyle(
                            fontSize: 12, color: context.faintText)),
                  ),
                  Expanded(child: Text(v, style: const TextStyle(fontSize: 13))),
                ],
              ),
            ),
          if (!athlete.hasHeight)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                '未填身高时，步幅等位移类指标无法计算。'
                '到「运动员」页编辑档案即可补上。',
                style: TextStyle(
                    fontSize: 11, color: Color(0xFFE65100), height: 1.5),
              ),
            ),
        ],
      ),
    );
  }
}

class _EmptyHint extends StatelessWidget {
  const _EmptyHint({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.symmetric(vertical: 48),
        child: Column(
          children: [
            Icon(icon, size: 52, color: context.hairline),
            const SizedBox(height: 14),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              detail,
              textAlign: TextAlign.center,
              style: TextStyle(color: context.mutedText, height: 1.6),
            ),
          ],
        ),
      );
}

// ---------------------------------------------------------------------------

String viewLabel(SessionView v) => switch (v) {
      SessionView.side => '侧面',
      SessionView.front => '正面',
      SessionView.back => '背面',
    };

String testTypeLabel(SessionTestType t) => switch (t) {
      SessionTestType.blockStart => '起跑',
      SessionTestType.acceleration => '加速段',
      SessionTestType.maxVelocity => '途中跑',
      SessionTestType.speedEndurance => '速度耐力',
    };

String levelLabelOf(AthleteLevel l) => switch (l) {
      AthleteLevel.elite => '精英',
      AthleteLevel.subElite => '次精英',
      AthleteLevel.college => '大学',
      AthleteLevel.highSchool => '中学',
      AthleteLevel.amateur => '业余',
    };
