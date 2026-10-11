/// 训练计划的一条记录：某一天做了什么。
///
/// 设计上刻意做成"日历备注"而不是"结构化训练课表"。
///
/// 为什么不做成结构化的（几组几趟、配速区间、组间休息）：
///   · 不同项目的课表结构完全不同（短跑练起跑和加速，
///     长跑练配速和耐力），做一套通用结构会两边都不合用
///   · 教练现在用纸笔或微信群记训练安排，格式是自由的
///   · 强行结构化会让"记一笔"变成"填一张表"，用户就不记了
///
/// 所以这里只存一段文本。如果将来确实需要结构化，
/// 加字段即可，已有的文本内容不受影响。
class TrainingPlanEntry {
  const TrainingPlanEntry({
    required this.date,
    required this.content,
    required this.updatedAt,
  });

  /// 日期，格式 `YYYY-MM-DD`。
  ///
  /// ⚠️ 用字符串而不是 DateTime 作为主键，是刻意的：
  ///    DateTime 带时区和时分秒，跨时区或跨夏令时会比较出不相等，
  ///    而"这是哪一天"在用户心里就是日历上的那一格。
  ///    存成 YYYY-MM-DD 之后排序、比较、查找都是纯字符串操作，不会出错。
  final String date;

  /// 当天训练安排的正文。空串表示没有安排。
  final String content;

  /// 最后修改时间（ISO8601）。用于将来做同步时的冲突判断。
  final String updatedAt;

  Map<String, dynamic> toJson() => {
        'date': date,
        'content': content,
        'updated_at': updatedAt,
      };

  static TrainingPlanEntry? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    final d = json['date'] as String?;
    if (d == null || d.isEmpty) return null;
    return TrainingPlanEntry(
      date: d,
      content: (json['content'] as String?) ?? '',
      updatedAt: (json['updated_at'] as String?) ?? '',
    );
  }

  TrainingPlanEntry copyWith({String? content}) => TrainingPlanEntry(
        date: date,
        content: content ?? this.content,
        updatedAt: DateTime.now().toIso8601String(),
      );

  /// 这天是否有内容。
  bool get hasContent => content.trim().isNotEmpty;

  /// 列表里显示的摘要（第一行，截断）。
  String get summary {
    final first = content
        .split('\n')
        .map((l) => l.trim())
        .firstWhere((l) => l.isNotEmpty, orElse: () => '');
    return first.length > 18 ? '${first.substring(0, 18)}…' : first;
  }
}

/// 把 DateTime 转成存储用的日期字符串。
///
/// 抽成函数而不是散落各处 `toIso8601String().substring(0, 10)` ——
/// 后者在月/日不足两位时行为不同，而这是很容易只改一处的坑。
String dateKey(DateTime d) {
  final m = d.month.toString().padLeft(2, '0');
  final day = d.day.toString().padLeft(2, '0');
  return '${d.year}-$m-$day';
}

/// 从存储字符串解析回日期。失败返回 null。
DateTime? parseDateKey(String s) {
  final parts = s.split('-');
  if (parts.length != 3) return null;
  final y = int.tryParse(parts[0]);
  final m = int.tryParse(parts[1]);
  final d = int.tryParse(parts[2]);
  if (y == null || m == null || d == null) return null;
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  return DateTime(y, m, d);
}
