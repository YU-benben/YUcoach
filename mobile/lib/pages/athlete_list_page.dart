import 'package:flutter/material.dart';

import '../data/athlete_repository.dart';
import '../domain/athlete_record.dart';
import '../models/models.dart';
import 'athlete_edit_page.dart';
import '../widgets/app_colors.dart';

/// 运动员列表。
///
/// 这是 App 的首页 —— 教练打开应用最想看到的是「我队里有谁」，
/// 而不是一堆功能入口。
class AthleteListPage extends StatefulWidget {
  const AthleteListPage({super.key, required this.repository});

  final AthleteRepository repository;

  @override
  State<AthleteListPage> createState() => _AthleteListPageState();
}

class _AthleteListPageState extends State<AthleteListPage> {
  List<AthleteRecord>? _athletes;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.repository.list();
      if (!mounted) return;
      setState(() {
        _athletes = list;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
    }
  }

  Future<void> _add() async {
    final created = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => AthleteEditPage(repository: widget.repository),
      ),
    );
    if (created == true) _load();
  }

  Future<void> _open(AthleteRecord a) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => AthleteEditPage(
          repository: widget.repository,
          existing: a,
        ),
      ),
    );
    if (changed == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final athletes = _athletes;

    return Scaffold(
      appBar: AppBar(
        title: const Text('运动员'),
        actions: [
          IconButton(
            tooltip: '添加运动员',
            onPressed: _add,
            icon: const Icon(Icons.person_add_alt),
          ),
        ],
      ),
      body: _buildBody(athletes),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _add,
        icon: const Icon(Icons.add),
        label: const Text('添加运动员'),
      ),
    );
  }

  Widget _buildBody(List<AthleteRecord>? athletes) {
    if (_error != null) {
      return _ErrorView(message: '$_error', onRetry: _load);
    }
    if (athletes == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (athletes.isEmpty) {
      // 空状态必须说明下一步做什么，不能只显示空白
      return const _EmptyView();
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
        itemCount: athletes.length,
        separatorBuilder: (_, _) => const SizedBox(height: 8),
        itemBuilder: (_, i) => _AthleteTile(
          athlete: athletes[i],
          onTap: () => _open(athletes[i]),
        ),
      ),
    );
  }
}

class _AthleteTile extends StatelessWidget {
  const _AthleteTile({required this.athlete, required this.onTap});

  final AthleteRecord athlete;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: Color(0xFFE0E0E0)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: theme.colorScheme.primaryContainer,
                child: Text(
                  athlete.name.characters.first,
                  style: TextStyle(
                    color: theme.colorScheme.onPrimaryContainer,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          athlete.name,
                          style: theme.textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(width: 8),
                        _MiniTag(text: athlete.event),
                        const SizedBox(width: 4),
                        _MiniTag(text: genderLabel(athlete.gender)),
                      ],
                    ),
                    SizedBox(height: 4),
                    Text(
                      _subtitle(athlete),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: context.mutedText),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: context.hairline),
            ],
          ),
        ),
      ),
    );
  }

  String _subtitle(AthleteRecord a) {
    final parts = <String>[levelLabel(a.level)];
    // 身高缺失会导致位移类指标不可用，在列表上就提示，别等分析完才发现
    parts.add(a.hasHeight ? '身高 ${a.heightCm!.round()} cm' : '未填身高');
    if (a.note != null && a.note!.isNotEmpty) parts.add(a.note!);
    return parts.join(' · ');
  }
}

class _MiniTag extends StatelessWidget {
  const _MiniTag({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(
          color: context.okSurface,
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(text, style: const TextStyle(fontSize: 11)),
      );
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.groups_outlined, size: 56, color: context.hairline),
              const SizedBox(height: 16),
              Text(
                '还没有运动员',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                '点击下方按钮添加第一名运动员。\n'
                '填上身高可以让步幅等位移类指标变得可用。',
                textAlign: TextAlign.center,
                style: TextStyle(color: context.mutedText, height: 1.6),
              ),
            ],
          ),
        ),
      );
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 40, color: Color(0xFFC62828)),
              const SizedBox(height: 12),
              const Text('读取运动员列表失败'),
              const SizedBox(height: 8),
              Text(
                message,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: context.mutedText),
              ),
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onRetry, child: const Text('重试')),
            ],
          ),
        ),
      );
}

// ---------------------------------------------------------------------------
// 枚举的用户化措辞。界面不显示契约里的英文值。
// ---------------------------------------------------------------------------

String genderLabel(AthleteGender g) => switch (g) {
      AthleteGender.male => '男',
      AthleteGender.female => '女',
    };

String levelLabel(AthleteLevel l) => switch (l) {
      AthleteLevel.elite => '精英',
      AthleteLevel.subElite => '次精英',
      AthleteLevel.college => '大学',
      AthleteLevel.highSchool => '中学',
      AthleteLevel.amateur => '业余',
    };

String eventLabelOf(String event) => switch (event) {
      '100m' => '100 米',
      '200m' => '200 米',
      '400m' => '400 米',
      _ => event,
    };
