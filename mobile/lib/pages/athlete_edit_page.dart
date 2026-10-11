import 'package:flutter/material.dart';

import '../data/athlete_repository.dart';
import '../domain/athlete_record.dart';
import '../models/models.dart';
import 'athlete_list_page.dart' show genderLabel, levelLabel;
import '../widgets/app_colors.dart';

/// 运动员档案的新增 / 编辑页。
///
/// 一个页面承载两种模式。表单字段与契约的 Athlete 一致 ——
/// 这些字段不是随便定的，每一个都有下游用途（见各字段的说明）。
class AthleteEditPage extends StatefulWidget {
  const AthleteEditPage({
    super.key,
    required this.repository,
    this.existing,
  });

  final AthleteRepository repository;
  final AthleteRecord? existing;

  bool get isEdit => existing != null;

  @override
  State<AthleteEditPage> createState() => _AthleteEditPageState();
}

class _AthleteEditPageState extends State<AthleteEditPage> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _height;
  late final TextEditingController _weight;
  late final TextEditingController _note;

  late AthleteGender _gender;
  late String _event;
  late AthleteLevel _level;

  bool _busy = false;

  static const _events = ['100m', '200m', '400m'];

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _name = TextEditingController(text: e?.name ?? '');
    _height = TextEditingController(
        text: e?.heightCm == null ? '' : e!.heightCm!.round().toString());
    _weight = TextEditingController(
        text: e?.weightKg == null ? '' : e!.weightKg!.round().toString());
    _note = TextEditingController(text: e?.note ?? '');
    _gender = e?.gender ?? AthleteGender.male;
    _event = e?.event ?? '100m';
    _level = e?.level ?? AthleteLevel.college;
  }

  @override
  void dispose() {
    _name.dispose();
    _height.dispose();
    _weight.dispose();
    _note.dispose();
    super.dispose();
  }

  double? _parseNum(TextEditingController c) {
    final t = c.text.trim();
    if (t.isEmpty) return null;
    return double.tryParse(t);
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _busy = true);

    final height = _parseNum(_height);
    final weight = _parseNum(_weight);

    if (widget.isEdit) {
      final e = widget.existing!;
      await widget.repository.update(e.copyWith(
        name: _name.text.trim(),
        gender: _gender,
        event: _event,
        level: _level,
        heightCm: height,
        weightKg: weight,
        note: _note.text,
        clearHeight: height == null,
        clearWeight: weight == null,
        clearNote: _note.text.trim().isEmpty,
      ));
    } else {
      await widget.repository.create(
        name: _name.text.trim(),
        gender: _gender,
        event: _event,
        level: _level,
        heightCm: height,
        weightKg: weight,
        note: _note.text,
      );
    }

    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  Future<void> _delete() async {
    final e = widget.existing!;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除运动员'),
        content: Text(
          '确定删除「${e.name}」吗？\n\n'
          '档案会被标记为已删除，历史分析记录仍保留。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(
              backgroundColor: context.errorText,
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    await widget.repository.softDelete(e.athleteId);
    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.isEdit ? '编辑档案' : '添加运动员'),
        actions: [
          if (widget.isEdit)
            IconButton(
              tooltip: '删除',
              onPressed: _busy ? null : _delete,
              icon: const Icon(Icons.delete_outline),
            ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _name,
              decoration: const InputDecoration(
                labelText: '姓名',
                border: OutlineInputBorder(),
              ),
              validator: (v) => (v ?? '').trim().isEmpty ? '请填写姓名' : null,
            ),
            const SizedBox(height: 16),

            _Label('性别'),
            SegmentedButton<AthleteGender>(
              segments: [
                for (final g in AthleteGender.values)
                  ButtonSegment(value: g, label: Text(genderLabel(g))),
              ],
              selected: {_gender},
              onSelectionChanged: (s) => setState(() => _gender = s.first),
            ),
            const SizedBox(height: 16),

            _Label('项目'),
            SegmentedButton<String>(
              segments: [
                for (final e in _events)
                  ButtonSegment(value: e, label: Text(e)),
              ],
              selected: {_event},
              onSelectionChanged: (s) => setState(() => _event = s.first),
            ),
            const SizedBox(height: 16),

            _Label('水平'),
            DropdownButtonFormField<AthleteLevel>(
              initialValue: _level,
              decoration: const InputDecoration(border: OutlineInputBorder()),
              items: [
                for (final l in AthleteLevel.values)
                  DropdownMenuItem(value: l, child: Text(levelLabel(l))),
              ],
              onChanged: (v) => setState(() => _level = v ?? _level),
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _height,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '身高（cm）',
                border: OutlineInputBorder(),
                helperText: '填写后步幅等位移类指标才能计算',
              ),
              validator: (v) {
                final t = (v ?? '').trim();
                if (t.isEmpty) return null;
                final n = double.tryParse(t);
                if (n == null) return '请填数字';
                // 生理上下限：超出必然是填错了，宁可拦下也不要产出错误分析
                if (n < 120 || n > 220) return '身高应在 120–220 cm 之间';
                return null;
              },
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _weight,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '体重（kg，选填）',
                border: OutlineInputBorder(),
              ),
              validator: (v) {
                final t = (v ?? '').trim();
                if (t.isEmpty) return null;
                final n = double.tryParse(t);
                if (n == null) return '请填数字';
                if (n < 25 || n > 150) return '体重应在 25–150 kg 之间';
                return null;
              },
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _note,
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: '备注（选填）',
                hintText: '伤病情况、技术特点等',
                border: OutlineInputBorder(),
                helperText: '伤病信息会影响训练处方的推荐',
              ),
            ),
            const SizedBox(height: 28),

            FilledButton(
              onPressed: _busy ? null : _save,
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: Text(widget.isEdit ? '保存修改' : '添加'),
            ),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(
          text,
          style: TextStyle(fontSize: 13, color: context.mutedText),
        ),
      );
}
