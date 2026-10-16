import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../data/analysis_server_client.dart';

/// Labels refer to original decoded frames, zero based, never preview playback.
class ManualContactReviewPage extends StatefulWidget {
  const ManualContactReviewPage({
    super.key,
    required this.client,
    required this.baseUrl,
    required this.videoId,
    this.targetSelection,
  });
  final AnalysisServerClient client;
  final String baseUrl;
  final String videoId;
  final Map<String, dynamic>? targetSelection;

  @override
  State<ManualContactReviewPage> createState() =>
      _ManualContactReviewPageState();
}

class _ManualContactReviewPageState extends State<ManualContactReviewPage> {
  Map<String, dynamic>? _meta;
  Uint8List? _image;
  String? _error;
  bool _loading = true;
  int _request = 0;
  int _frame = 0;
  double _seek = 0;
  String _side = 'left';
  final _events = <Map<String, dynamic>>[];
  final _confirmed = [false, false, false, false];

  @override
  void initState() {
    super.initState();
    _prepare();
  }

  Future<void> _prepare() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final meta = await widget.client.reviewMetadata(
        widget.baseUrl,
        widget.videoId,
      );
      if (!mounted) return;
      setState(() => _meta = meta);
      await _load(widget.targetSelection?['frame'] as int? ?? 0);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  Future<void> _load(int frame) async {
    if (_meta == null) return;
    final request = ++_request;
    final index = frame.clamp(
      widget.targetSelection?['frame'] as int? ?? 0,
      widget.targetSelection?['end_frame'] as int? ??
          (_meta!['frame_count'] as int) - 1,
    );
    setState(() {
      _frame = index;
      _seek = index.toDouble();
      _image = null;
      _error = null;
      _loading = true;
    });
    try {
      final image = await widget.client.reviewFrame(
        widget.baseUrl,
        widget.videoId,
        index,
      );
      if (mounted && request == _request) {
        setState(() {
          _image = image;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted && request == _request) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  void _add(String type) {
    if (_image == null || _loading) return;
    if (_events.any((e) => e['frame'] == _frame)) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('该帧已有事件，请先删除再修改')));
      return;
    }
    setState(() {
      _events.add({'frame': _frame, 'side': _side, 'type': type});
      _events.sort((a, b) => (a['frame'] as int).compareTo(b['frame'] as int));
      _confirmed[3] = false;
    });
  }

  String? _validation() {
    if (_events.length < 4 || _events.length.isOdd) {
      return '至少标注两个完整接触；每次包含同脚着地和离地';
    }
    for (var i = 0; i < _events.length; i += 2) {
      final a = _events[i], b = _events[i + 1];
      if (a['type'] != 'touchdown' ||
          b['type'] != 'toe_off' ||
          a['side'] != b['side']) {
        return '请按同脚着地→同脚离地→另一脚着地排序；删除两端不完整事件';
      }
      if (i > 0 && _events[i - 2]['side'] == a['side']) {
        return '相邻接触应左右脚交替，请检查漏标';
      }
    }
    if (!_confirmed.every((x) => x)) return '完成下方四项确认后才能提交';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final meta = _meta;
    final problem = _validation();
    return Scaffold(
      appBar: AppBar(title: const Text('逐帧确认接触事件')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            '仅适用于固定侧面、原始恒定高帧率短跑视频。建议 240 fps，至少 120 fps。先选一个连续清晰区间，标全区间内同一人的左右脚接触。',
          ),
          const SizedBox(height: 8),
          if (widget.targetSelection != null) ...[
            Text(
              '已选运动员：起始帧 ${widget.targetSelection!["frame"]}，允许标注至帧 ${widget.targetSelection!["end_frame"]}。请始终核对同一人；选人框不会自动跟随。',
            ),
            TextButton(
              onPressed: _loading
                  ? null
                  : () => _load(widget.targetSelection!['frame'] as int),
              child: const Text('返回选人帧核对身份'),
            ),
          ],
          const Text(
            '着地：鞋底首次接触地面的帧。离地：鞋底首次完全离开地面的帧。左右按运动员自身区分；模糊或遮挡无法确认时，请退出并换素材。首尾不完整接触不标。',
          ),
          if (meta != null)
            Text(
              '${meta['fps']} fps · ${meta['frame_count']} 帧 · 单帧 ${(meta['frame_interval_ms'] as num).toStringAsFixed(3)} ms',
            ),
          if (_error != null) ...[
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
            TextButton(
              onPressed: () => meta == null ? _prepare() : _load(_frame),
              child: const Text('重试'),
            ),
          ],
          SizedBox(
            height: 280,
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _image == null
                ? const Center(child: Text('没有可标注的画面'))
                : InteractiveViewer(
                    minScale: 1,
                    maxScale: 5,
                    child: Center(
                      child: AspectRatio(
                        aspectRatio: meta != null && meta['width'] != null
                            ? (meta['width'] as num) / (meta['height'] as num)
                            : 16 / 9,
                        child: LayoutBuilder(
                          builder: (context, constraints) => Stack(
                            fit: StackFit.expand,
                            children: [
                              Image.memory(
                                _image!,
                                key: ValueKey(_frame),
                                fit: BoxFit.fill,
                              ),
                              if (widget.targetSelection != null &&
                                  _frame == widget.targetSelection!['frame'])
                                Positioned.fromRect(
                                  rect: Rect.fromLTRB(
                                    (widget.targetSelection!['bbox'][0]
                                            as num) *
                                        constraints.maxWidth,
                                    (widget.targetSelection!['bbox'][1]
                                            as num) *
                                        constraints.maxHeight,
                                    (widget.targetSelection!['bbox'][2]
                                            as num) *
                                        constraints.maxWidth,
                                    (widget.targetSelection!['bbox'][3]
                                            as num) *
                                        constraints.maxHeight,
                                  ),
                                  child: IgnorePointer(
                                    child: Container(
                                      decoration: BoxDecoration(
                                        border: Border.all(
                                          color: Colors.greenAccent,
                                          width: 3,
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
          ),
          if (meta != null) ...[
            Text(
              '帧号 $_frame（从 0 开始） · 时间 ${(_frame * 1000 / (meta['fps'] as num)).toStringAsFixed(2)} ms',
            ),
            Slider(
              value: _seek,
              min: (widget.targetSelection?['frame'] as int? ?? 0).toDouble(),
              max:
                  (widget.targetSelection?['end_frame'] as int? ??
                          (meta['frame_count'] as int) - 1)
                      .toDouble(),
              onChanged: _loading ? null : (v) => setState(() => _seek = v),
              onChangeEnd: (v) => _load(v.round()),
            ),
            Wrap(
              spacing: 8,
              children: [
                for (final delta in [-10, -1, 1, 10])
                  OutlinedButton(
                    onPressed: _loading ? null : () => _load(_frame + delta),
                    child: Text('${delta > 0 ? '+' : ''}$delta 帧'),
                  ),
              ],
            ),
            DropdownButton<String>(
              value: _side,
              isExpanded: true,
              items: const [
                DropdownMenuItem(value: 'left', child: Text('运动员左脚')),
                DropdownMenuItem(value: 'right', child: Text('运动员右脚')),
              ],
              onChanged: (v) => setState(() => _side = v!),
            ),
            Wrap(
              spacing: 8,
              children: [
                FilledButton(
                  onPressed: _image == null ? null : () => _add('touchdown'),
                  child: const Text('标记着地'),
                ),
                FilledButton(
                  onPressed: _image == null ? null : () => _add('toe_off'),
                  child: const Text('标记离地'),
                ),
              ],
            ),
          ],
          for (final e in _events)
            ListTile(
              title: Text(
                '${e['side'] == 'left' ? '左脚' : '右脚'} ${e['type'] == 'touchdown' ? '着地' : '离地'} · 帧 ${e['frame']}',
              ),
              onTap: _loading ? null : () => _load(e['frame'] as int),
              trailing: IconButton(
                icon: const Icon(Icons.delete_outline),
                tooltip: '删除标注',
                onPressed: () => setState(() {
                  _events.remove(e);
                  _confirmed[3] = false;
                }),
              ),
            ),
          for (var i = 0; i < _confirmed.length; i++)
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _confirmed[i],
              title: Text(
                const [
                  '这是未剪辑、未变速、未补帧的原片，文件帧率就是实际拍摄帧率',
                  '全程固定侧面，没有跟拍、移动或变焦',
                  '所有标注均属于同一运动员，左右脚已核对',
                  '所选首末接触之间无漏标，边界清晰可见',
                ][i],
              ),
              onChanged: (v) => setState(() => _confirmed[i] = v ?? false),
            ),
          const Text(
            '确认后，原视频、标注和报告会保存在分析电脑的 data/manual_timing 中，供后续人工复核。它们不会自动成为训练真值。',
          ),
          if (problem != null) Text(problem),
          FilledButton(
            onPressed: problem != null || _loading || _image == null
                ? null
                : () => Navigator.pop(context, <String, dynamic>{
                    'protocol': 'manual_side_v1',
                    'original_cfr_confirmed': true,
                    'fixed_side_confirmed': true,
                    'same_athlete_confirmed': true,
                    'all_contacts_confirmed': true,
                    'events': _events,
                  }),
            child: const Text('确认标注并计算'),
          ),
        ],
      ),
    );
  }
}
