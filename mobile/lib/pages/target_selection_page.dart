import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';

import '../data/analysis_server_client.dart';

/// Rectangle coordinates use the exact displayed image extent, excluding bars.
class TargetSelectionPage extends StatefulWidget {
  const TargetSelectionPage({
    super.key,
    required this.client,
    required this.baseUrl,
    required this.videoId,
  });
  final AnalysisServerClient client;
  final String baseUrl;
  final String videoId;

  @override
  State<TargetSelectionPage> createState() => _TargetSelectionPageState();
}

class _TargetSelectionPageState extends State<TargetSelectionPage> {
  Map<String, dynamic>? _metadata;
  Uint8List? _image;
  Rect? _box;
  Offset? _origin;
  int _frame = 0;
  int? _start;
  int? _end;
  double _seek = 0;
  bool _busy = true;
  bool _confirmed = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _prepare();
  }

  Future<void> _prepare() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final meta = await widget.client.reviewMetadata(
        widget.baseUrl,
        widget.videoId,
      );
      if (!mounted) return;
      setState(() => _metadata = meta);
      await _load(0);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _busy = false;
        });
      }
    }
  }

  Future<void> _load(int frame) async {
    if (_metadata == null) return;
    final request = ++_request;
    final index = frame.clamp(0, (_metadata!['frame_count'] as int) - 1);
    setState(() {
      _busy = true;
      _error = null;
      _image = null;
      _frame = index;
      _seek = index.toDouble();
    });
    try {
      final bytes = await widget.client.reviewFrame(
        widget.baseUrl,
        widget.videoId,
        index,
      );
      if (!mounted || request != _request) return;
      setState(() {
        _image = bytes;
        _busy = false;
      });
    } catch (e) {
      if (mounted && request == _request) {
        setState(() {
          _error = '$e';
          _busy = false;
        });
      }
    }
  }

  Offset _normalized(Offset point, Size size) => Offset(
    (point.dx / size.width).clamp(0, 1),
    (point.dy / size.height).clamp(0, 1),
  );

  @override
  Widget build(BuildContext context) {
    final meta = _metadata;
    final ready =
        _start != null &&
        _end != null &&
        _end! > _start! &&
        _box != null &&
        _confirmed &&
        !_busy;
    return Scaffold(
      appBar: AppBar(title: const Text('锁定本次运动员')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('选择人物清晰、没有与其他人重叠的起始帧，在画面上拖动框住一个人的完整身体，再设置结束帧。分析只使用这个区间。'),
          const SizedBox(height: 8),
          const Text(
            '自动分析会连续关联此人；遇到丢失、外观不匹配或人物重叠会停止。人工计时仍需逐帧核对同一人，本页框选不代表已自动跟踪。',
          ),
          const SizedBox(height: 12),
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
          if (meta == null || _busy)
            const SizedBox(
              height: 200,
              child: Center(child: CircularProgressIndicator()),
            ),
          if (meta != null && !_busy && _image != null)
            AspectRatio(
              aspectRatio: (meta['width'] as num) / (meta['height'] as num),
              child: LayoutBuilder(
                builder: (context, constraints) => GestureDetector(
                  key: const Key('target-canvas'),
                  dragStartBehavior: DragStartBehavior.down,
                  behavior: HitTestBehavior.opaque,
                  onPanStart: (details) => setState(() {
                    _origin = _normalized(
                      details.localPosition,
                      constraints.biggest,
                    );
                    _box = null;
                    _start = null;
                    _end = null;
                    _confirmed = false;
                  }),
                  onPanUpdate: (details) => setState(() {
                    final point = _normalized(
                      details.localPosition,
                      constraints.biggest,
                    );
                    _box = Rect.fromPoints(_origin!, point);
                  }),
                  onPanEnd: (_) => setState(() {
                    if (_box != null &&
                        _box!.width >= .02 &&
                        _box!.height >= .05) {
                      _start = _frame;
                    } else {
                      _box = null;
                    }
                  }),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.memory(
                        _image!,
                        fit: BoxFit.fill,
                        key: ValueKey(_frame),
                      ),
                      if (_box != null && (_start == null || _frame == _start))
                        Positioned.fromRect(
                          rect: Rect.fromLTRB(
                            _box!.left * constraints.maxWidth,
                            _box!.top * constraints.maxHeight,
                            _box!.right * constraints.maxWidth,
                            _box!.bottom * constraints.maxHeight,
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
          if (meta != null) ...[
            Text('当前帧 $_frame · ${meta['fps']} fps'),
            Slider(
              value: _seek,
              min: 0,
              max: (meta['frame_count'] as int) - 1.0,
              onChanged: _busy ? null : (v) => setState(() => _seek = v),
              onChangeEnd: (v) => _load(v.round()),
            ),
            Wrap(
              spacing: 8,
              children: [
                for (final delta in [-10, -1, 1, 10])
                  OutlinedButton(
                    onPressed: _busy ? null : () => _load(_frame + delta),
                    child: Text('${delta > 0 ? '+' : ''}$delta 帧'),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              _start == null
                  ? '尚未框选运动员'
                  : '选人起始帧：$_start；结束帧：${_end ?? '尚未设置'}',
            ),
            OutlinedButton(
              onPressed:
                  !_busy && _start != null && _frame > _start! && _image != null
                  ? () => setState(() {
                      _end = _frame;
                      _confirmed = false;
                    })
                  : null,
              child: const Text('将当前帧设为结束帧'),
            ),
            if (_start != null)
              TextButton(
                onPressed: _busy ? null : () => _load(_start!),
                child: const Text('返回选人帧核对'),
              ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('框内只有目标运动员；已检查区间首尾，同一人完整可见，固定侧面无跟拍'),
              value: _confirmed,
              onChanged: (v) => setState(() => _confirmed = v ?? false),
            ),
            FilledButton(
              onPressed: !ready
                  ? null
                  : () => Navigator.pop(context, <String, dynamic>{
                      'protocol': 'athlete_lock_v1',
                      'frame': _start,
                      'end_frame': _end,
                      'bbox': [
                        _box!.left,
                        _box!.top,
                        _box!.right,
                        _box!.bottom,
                      ],
                      'confirmed': true,
                    }),
              child: const Text('确认人物和区间'),
            ),
          ],
        ],
      ),
    );
  }
}
