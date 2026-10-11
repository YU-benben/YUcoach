import 'package:flutter/material.dart';

import '../data/session_repository.dart';
import '../data/training_plan_repository.dart';
import '../domain/local_user.dart';
import '../domain/session_record.dart';
import '../domain/training_plan_entry.dart';
import '../widgets/app_colors.dart';

/// 训练计划日历。
///
/// ## 它是什么
///
/// 一个月历，每天可以写训练安排（自由文本）。
/// 做过分析的日子会标一个点，点开能看到那天的记录。
///
/// ## 为什么把"分析记录"叠在日历上
///
/// 单独看日历只是记事本，单独看记录列表只是流水账。
/// 叠在一起才有用 —— 教练能看出"这天练了起跑，但数据不好"，
/// 或者"这周没拍，得补一次"。
///
/// 这是训练计划与分析数据之间**唯一真正有意义的关联**：
/// 计划说"打算练什么"，记录说"实际练成什么样"。
class TrainingPlanPage extends StatefulWidget {
  const TrainingPlanPage({
    super.key,
    required this.user,
    this.sessionRepository,
  });

  final LocalUser user;

  /// 允许外部注入，便于测试时不碰真实文件。
  final SessionRepository? sessionRepository;

  @override
  State<TrainingPlanPage> createState() => _TrainingPlanPageState();
}

class _TrainingPlanPageState extends State<TrainingPlanPage> {
  late final TrainingPlanRepository _plans;
  late final SessionRepository _sessions;

  /// 当前显示的月份（只用到年和月）。
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);

  Map<String, TrainingPlanEntry> _entries = {};

  /// 有分析记录的日期集合。`YYYY-MM-DD`。
  ///
  /// ⚠️ 存成 Set 而不是每次遍历记录列表：
  ///    日历一个月要渲染 30+ 格，每格都去遍历一遍记录列表
  ///    就是 30 × N 次比较。记录攒到几百条时会明显卡顿。
  Set<String> _analysisDays = {};

  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _plans = TrainingPlanRepository(userId: widget.user.userId);
    _sessions = widget.sessionRepository ??
        SessionRepository(teamId: widget.user.teamId);
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);

    final first = DateTime(_month.year, _month.month, 1);
    final last = DateTime(_month.year, _month.month + 1, 0);

    final entries = await _plans.range(first, last);

    // 分析记录：取全部再筛当月。
    // 为什么不按月查 —— 记录数通常不多（一个教练一学期几十到几百条），
    // 全量读一次比做索引简单，而且列表页本来也要全量读。
    final records = await _sessions.list();

    final days = <String>{};
    for (final r in records) {
      final d = _parseRecordedAt(r.recordedAt);
      if (d == null) continue;
      days.add(dateKey(d));
    }

    if (!mounted) return;
    setState(() {
      _entries = entries;
      _analysisDays = days;
      _loading = false;
    });
  }

  /// 解析记录时间。
  ///
  /// 记录里存的是 ISO8601 字符串，但**旧数据可能有各种格式**
  /// （早期版本用过 `yyyy-MM-dd HH:mm:ss`）。解析失败返回 null，
  /// 让它不在日历上出现，而不是让整个日历崩掉。
  static DateTime? _parseRecordedAt(String s) {
    if (s.isEmpty) return null;
    final iso = DateTime.tryParse(s);
    if (iso != null) return iso.toLocal();
    // 兜底：取前 10 位当日期
    if (s.length >= 10) return parseDateKey(s.substring(0, 10));
    return null;
  }

  void _shiftMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta);
    });
    _load();
  }

  Future<void> _editDay(DateTime day) async {
    final key = dateKey(day);
    final existing = _entries[key];
    final controller = TextEditingController(text: existing?.content ?? '');

    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,   // 键盘弹出时让面板升高，而不是遮住输入框
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          // 让面板避开键盘
          bottom: MediaQuery.of(ctx).viewInsets.bottom,
        ),
        child: _DayEditor(
          day: day,
          controller: controller,
          hasAnalysis: _analysisDays.contains(key),
        ),
      ),
    );

    if (!mounted || result == null) return;
    await _plans.save(day, result);

    // ⚠️ 就地更新内存里的条目，而不是 `await _load()` 重读文件。
    //
    // 为什么：重读文件后面板会重建，用户刚保存完就看到面板"闪"了一下。
    // 而且如果编辑面板是从查看面板里打开的，重读会让查看面板显示的
    // 还是旧内容（它拿的是打开时捕获的对象）。
    // 就地更新能保证"存了什么，立刻看到什么"。
    final trimmed = result.trim();
    setState(() {
      if (trimmed.isEmpty) {
        _entries.remove(key);
      } else {
        _entries[key] = TrainingPlanEntry(
          date: key,
          content: trimmed,
          updatedAt: DateTime.now().toIso8601String(),
        );
      }
    });

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(trimmed.isEmpty ? '已清空该日安排' : '已保存'),
        duration: const Duration(seconds: 1),
      ),
    );
  }

  /// 点某一天：默认**查看**，不是直接进编辑。
  ///
  /// ## 为什么要分开查看与编辑
  ///
  /// 原来的实现是点一下直接弹输入框。这有两个问题：
  ///
  ///   1. **容易误改**。用户只是想看看那天安排了什么，
  ///      结果弹出一个可以改的输入框，键盘还可能挡住内容。
  ///   2. **看不到分析记录**。有记录的日子本该优先展示记录，
  ///      却直接跳到了编辑。
  ///
  /// 所以改成：点日期先看，查看面板里有明确的「编辑」按钮。
  /// 想改的时候多按一次，但想看的时候永远不会误改。
  Future<void> _openDay(DateTime day) async {
    final key = dateKey(day);
    final records = (await _sessions.list())
        .where((r) => _sameDay(r.recordedAt, day))
        .toList();

    if (!mounted) return;
    final action = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => _DayViewSheet(
        day: day,
        plan: _entries[key],
        records: records,
      ),
    );

    if (!mounted || action == null) return;
    if (action == 'edit') {
      await _editDay(day);
    }
  }

  static bool _sameDay(String recordedAt, DateTime day) {
    final d = _parseRecordedAt(recordedAt);
    if (d == null) return false;
    return d.year == day.year && d.month == day.month && d.day == day.day;
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();

    return Scaffold(
      appBar: AppBar(
        title: const Text('训练计划'),
        actions: [
          IconButton(
            tooltip: '回到今天',
            onPressed: () {
              setState(() {
                _month = DateTime(today.year, today.month);
              });
              _load();
            },
            icon: const Icon(Icons.today_outlined),
          ),
        ],
      ),
      body: Column(
        children: [
          _MonthHeader(
            month: _month,
            onPrev: () => _shiftMonth(-1),
            onNext: () => _shiftMonth(1),
          ),
          const _WeekdayHeader(),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _MonthGrid(
                    month: _month,
                    today: today,
                    entries: _entries,
                    analysisDays: _analysisDays,
                    onTapDay: _openDay,
                  ),
          ),
          const _Legend(),
        ],
      ),
    );
  }
}

/// 月份标题与切换按钮。
class _MonthHeader extends StatelessWidget {
  const _MonthHeader({
    required this.month,
    required this.onPrev,
    required this.onNext,
  });

  final DateTime month;
  final VoidCallback onPrev;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
      child: Row(
        children: [
          IconButton(
            onPressed: onPrev,
            icon: const Icon(Icons.chevron_left),
          ),
          Expanded(
            child: Text(
              '${month.year} 年 ${month.month} 月',
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontSize: 16, fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(
            onPressed: onNext,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    );
  }
}

class _WeekdayHeader extends StatelessWidget {
  const _WeekdayHeader();

  @override
  Widget build(BuildContext context) {
    // 周一起始 —— 国内训练安排通常按周一到周日排。
    // 用周日起始会让人看错格。
    const names = ['一', '二', '三', '四', '五', '六', '日'];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          for (var i = 0; i < 7; i++)
            Expanded(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: 6),
                child: Text(
                  names[i],
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 11.5,
                    color: i >= 5 ? context.faintText : context.mutedText,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 月历网格。
class _MonthGrid extends StatelessWidget {
  const _MonthGrid({
    required this.month,
    required this.today,
    required this.entries,
    required this.analysisDays,
    required this.onTapDay,
  });

  final DateTime month;
  final DateTime today;
  final Map<String, TrainingPlanEntry> entries;
  final Set<String> analysisDays;
  final ValueChanged<DateTime> onTapDay;

  @override
  Widget build(BuildContext context) {
    final first = DateTime(month.year, month.month, 1);
    final daysInMonth = DateTime(month.year, month.month + 1, 0).day;

    // 周一为一周的第一天。DateTime.weekday: 周一=1 … 周日=7
    final leading = first.weekday - 1;
    final cells = leading + daysInMonth;
    final rows = (cells / 7).ceil();

    return GridView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      itemCount: rows * 7,
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 7,
        // 稍微高一点，让"计划摘要 + 圆点"放得下
        childAspectRatio: 0.82,
      ),
      itemBuilder: (context, i) {
        final dayNum = i - leading + 1;
        if (dayNum < 1 || dayNum > daysInMonth) {
          return const SizedBox.shrink();
        }
        final day = DateTime(month.year, month.month, dayNum);
        final key = dateKey(day);

        return _DayCell(
          day: day,
          isToday: day.year == today.year &&
              day.month == today.month &&
              day.day == today.day,
          isWeekend: day.weekday >= 6,
          entry: entries[key],
          hasAnalysis: analysisDays.contains(key),
          onTap: () => onTapDay(day),
        );
      },
    );
  }
}

/// 一格。
class _DayCell extends StatelessWidget {
  const _DayCell({
    required this.day,
    required this.isToday,
    required this.isWeekend,
    required this.entry,
    required this.hasAnalysis,
    required this.onTap,
  });

  final DateTime day;
  final bool isToday;
  final bool isWeekend;
  final TrainingPlanEntry? entry;
  final bool hasAnalysis;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final hasPlan = entry?.hasContent ?? false;

    return Semantics(
      // 读屏软件念不出一个空格子是什么 —— 把状态说清楚。
      label: '${day.month} 月 ${day.day} 日'
          '${hasPlan ? "，有训练安排" : ""}'
          '${hasAnalysis ? "，有分析记录" : ""}',
      button: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          margin: EdgeInsets.all(2),
          padding: EdgeInsets.symmetric(horizontal: 3, vertical: 3),
          decoration: BoxDecoration(
            color: hasPlan ? context.okSurface : null,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: isToday
                  ? context.okText
                  : (hasPlan
                      ? context.hairline
                      : context.hairline),
              width: isToday ? 1.8 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    '${day.day}',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight:
                          isToday ? FontWeight.w700 : FontWeight.w500,
                      color: isToday
                          ? context.okText
                          : (isWeekend ? context.faintText : Colors.black87),
                    ),
                  ),
                  const Spacer(),
                  // 有分析记录就标一个点 —— 这是日历与数据的联结点
                  if (hasAnalysis)
                    Container(
                      width: 6,
                      height: 6,
                      decoration: const BoxDecoration(
                        color: Color(0xFFE64A19),
                        shape: BoxShape.circle,
                      ),
                    ),
                ],
              ),
              if (hasPlan) ...[
                const SizedBox(height: 2),
                Expanded(
                  child: Text(
                    entry!.summary,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 9,
                      height: 1.25,
                      color: Color(0xFF33691E),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
      child: Row(
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: const BoxDecoration(
              color: Color(0xFFE64A19),
              shape: BoxShape.circle,
            ),
          ),
          SizedBox(width: 5),
          Text('有分析记录',
              style: TextStyle(fontSize: 11, color: context.mutedText)),
          SizedBox(width: 16),
          Container(
            width: 14,
            height: 10,
            decoration: BoxDecoration(
              color: context.okSurface,
              borderRadius: BorderRadius.circular(2),
              border: Border.all(color: context.hairline),
            ),
          ),
          const SizedBox(width: 5),
          Text('已安排训练',
              style: TextStyle(fontSize: 11, color: context.mutedText)),
          Spacer(),
          Text('点击日期编辑',
              style: TextStyle(fontSize: 11, color: context.faintText)),
        ],
      ),
    );
  }
}

/// 编辑某一天的训练安排。
class _DayEditor extends StatelessWidget {
  const _DayEditor({
    required this.day,
    required this.controller,
    required this.hasAnalysis,
  });

  final DateTime day;
  final TextEditingController controller;
  final bool hasAnalysis;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${day.year} 年 ${day.month} 月 ${day.day} 日',
                style: const TextStyle(
                    fontSize: 15.5, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              if (hasAnalysis)
                Container(
                  padding: EdgeInsets.symmetric(
                      horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: context.errorSurface,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text(
                    '当天有分析记录',
                    style: TextStyle(
                        fontSize: 10.5, color: Color(0xFFE64A19)),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            maxLines: 6,
            minLines: 4,
            autofocus: true,
            textInputAction: TextInputAction.newline,
            decoration: const InputDecoration(
              hintText: '例如：\n起跑器练习 6 组 × 30 米\n重点：第一步蹬伸角度',
              border: OutlineInputBorder(),
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '内容留空则清除这一天。',
            style: TextStyle(fontSize: 11, color: context.faintText),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => Navigator.of(context).pop(''),
                  child: const Text('清空'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                flex: 2,
                child: FilledButton(
                  onPressed: () =>
                      Navigator.of(context).pop(controller.text),
                  child: const Text('保存'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 查看某一天的安排与分析记录。
///
/// 这是**只读**的 —— 唯一的写操作是底部的「编辑」按钮，
/// 点了才进入可编辑状态。这样"只是想看看"永远不会误改。
class _DayViewSheet extends StatelessWidget {
  const _DayViewSheet({
    required this.day,
    required this.plan,
    required this.records,
  });

  final DateTime day;
  final TrainingPlanEntry? plan;
  final List<SessionRecord> records;

  @override
  Widget build(BuildContext context) {
    final hasPlan = plan?.hasContent ?? false;
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ---- 标题 ----
            Row(
              children: [
                Text(
                  '${day.year} 年 ${day.month} 月 ${day.day} 日',
                  style: const TextStyle(
                      fontSize: 15.5, fontWeight: FontWeight.w600),
                ),
                const SizedBox(width: 8),
                Text(
                  _weekdayZh(day.weekday),
                  style: TextStyle(
                      fontSize: 12, color: theme.colorScheme.outline),
                ),
              ],
            ),
            const SizedBox(height: 16),

            // ---- 训练安排（只读展示）----
            const _SheetLabel('训练安排'),
            const SizedBox(height: 6),
            if (hasPlan)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest
                      .withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  plan!.content,
                  style: const TextStyle(fontSize: 13, height: 1.6),
                ),
              )
            else
              Text(
                '这一天还没有安排',
                style: TextStyle(
                    fontSize: 12.5, color: theme.colorScheme.outline),
              ),

            // ---- 分析记录 ----
            if (records.isNotEmpty) ...[
              const SizedBox(height: 18),
              _SheetLabel('分析记录（${records.length} 条）'),
              const SizedBox(height: 6),
              for (final r in records)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 2, right: 8),
                        child: Icon(Icons.insights_outlined,
                            size: 16, color: Color(0xFFE64A19)),
                      ),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              r.athleteName,
                              style: const TextStyle(
                                  fontSize: 13.5,
                                  fontWeight: FontWeight.w500),
                            ),
                            const SizedBox(height: 1),
                            Text(
                              '${_viewZh(r.view)} · ${_testZh(r.testType)}',
                              style: TextStyle(
                                  fontSize: 11.5,
                                  color: theme.colorScheme.outline),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              Text(
                '在「数据」页可以看到完整报告与关键帧图片。',
                style: TextStyle(
                    fontSize: 11, color: theme.colorScheme.outline),
              ),
            ],

            const SizedBox(height: 20),
            // ---- 唯一的写操作入口 ----
            SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                onPressed: () => Navigator.of(context).pop('edit'),
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: Text(hasPlan ? '编辑这一天的安排' : '添加训练安排'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _weekdayZh(int weekday) => const [
        '周一', '周二', '周三', '周四', '周五', '周六', '周日',
      ][weekday - 1];

  static String _viewZh(dynamic view) {
    final s = view.toString();
    if (s.contains('front')) return '正面';
    if (s.contains('back')) return '背面';
    return '侧面';
  }

  static String _testZh(dynamic testType) {
    final s = testType.toString();
    if (s.contains('block')) return '起跑';
    if (s.contains('maxVelocity')) return '最高速度';
    if (s.contains('speedEndurance')) return '速度耐力';
    return '加速跑';
  }
}

class _SheetLabel extends StatelessWidget {
  const _SheetLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: TextStyle(
          fontSize: 12,
          color: Theme.of(context).colorScheme.outline,
        ),
      );
}
