import 'package:flutter/material.dart';

import '../../models/models.dart';
import '../widgets/app_colors.dart';

/// 采集信息表单的填写结果。
///
/// 这些字段都不是可有可无的元数据 —— 每一个都直接影响分析能不能算、算得准不准。
/// 所以界面上每一项都写了「为什么问这个」，而不是干巴巴一个输入框。
class CaptureInfo {
  const CaptureInfo({
    required this.testType,
    required this.view,
    required this.cameraDistanceM,
    required this.cameraHeightM,
    required this.hasLaneLine,
    required this.cameraFollowed,
    this.exposureLocked,
    this.athleteHeightCm,
  });

  final SessionTestType testType;
  final SessionView view;
  final double cameraDistanceM;
  final double cameraHeightM;

  /// 画面中是否有跑道分道线。决定位移类指标能否换算。
  final bool hasLaneLine;

  /// 镜头是否跟随运动员移动。跟踪引入透视误差，需单独处理。
  final bool cameraFollowed;

  final bool? exposureLocked;

  /// 运动员身高。档案里没填时在这里补，影响体型归一化。
  final double? athleteHeightCm;
}

/// 采集信息表单。
///
/// 设计原则：**只问用户知道的，不问用户不知道的。**
///
/// 反面例子（都改成用户能回答的形式）：
///   ✘ "镜头光轴偏角多少度？"  -> ✔ "拍摄方位是？侧 / 正 / 背"
///   ✘ "像素米比是多少？"      -> ✔ "画面里能看到分道线吗？"
///   ✘ "是否做过畸变校正？"    -> 不问。服务端按设备与标定档案判断
///
/// 用户不知道的字段，问了只会得到乱填的值 —— 而乱填的值比空值更危险。
class CaptureInfoForm extends StatefulWidget {
  const CaptureInfoForm({
    super.key,
    required this.onChanged,
    this.athleteHeightCm,
  });

  /// 表单变化时回调，交给父级决定是否允许提交
  final void Function(CaptureInfo?) onChanged;

  /// 运动员档案里已有的身高。有值时不再重复问。
  final double? athleteHeightCm;

  @override
  State<CaptureInfoForm> createState() => _CaptureInfoFormState();
}

class _CaptureInfoFormState extends State<CaptureInfoForm> {
  final _distance = TextEditingController(text: '10');
  final _height = TextEditingController(text: '1.2');
  final _athleteHeight = TextEditingController();

  SessionTestType _testType = SessionTestType.acceleration;
  SessionView? _view;
  bool? _hasLaneLine;
  bool? _cameraFollowed;
  bool? _exposureLocked;

  @override
  void initState() {
    super.initState();
    if (widget.athleteHeightCm != null) {
      _athleteHeight.text = widget.athleteHeightCm!.round().toString();
    }
    // 初始就通知一次，让父级知道还不完整
    WidgetsBinding.instance.addPostFrameCallback((_) => _notify());
  }

  @override
  void dispose() {
    _distance.dispose();
    _height.dispose();
    _athleteHeight.dispose();
    super.dispose();
  }

  double? _num(TextEditingController c) {
    final t = c.text.trim();
    if (t.isEmpty) return null;
    return double.tryParse(t);
  }

  void _notify() {
    final d = _num(_distance);
    final h = _num(_height);

    // 只在必填项齐全时才产出结果。缺项时传 null，
    // 由父级禁用提交按钮 —— 比提交后报错体验好得多。
    if (_view == null || d == null || h == null ||
        _hasLaneLine == null || _cameraFollowed == null) {
      widget.onChanged(null);
      return;
    }

    widget.onChanged(CaptureInfo(
      testType: _testType,
      view: _view!,
      cameraDistanceM: d,
      cameraHeightM: h,
      hasLaneLine: _hasLaneLine!,
      cameraFollowed: _cameraFollowed!,
      exposureLocked: _exposureLocked,
      athleteHeightCm: _num(_athleteHeight),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Question(
          label: '测试类型',
          why: '不同阶段的判定标准不同，必须先确定分析哪一段',
          child: SegmentedButton<SessionTestType>(
            segments: const [
              ButtonSegment(
                  value: SessionTestType.blockStart, label: Text('起跑')),
              ButtonSegment(
                  value: SessionTestType.acceleration, label: Text('加速段')),
              ButtonSegment(
                  value: SessionTestType.maxVelocity, label: Text('途中跑')),
            ],
            selected: {_testType},
            onSelectionChanged: (s) {
              setState(() => _testType = s.first);
              _notify();
            },
          ),
        ),

        _Question(
          label: '拍摄方位',
          why: '决定能分析哪些指标：侧面看关节角度，正/背面看骨盆控制与左右对称',
          required: true,
          child: _ViewSelector(
            value: _view,
            onChanged: (v) {
              setState(() => _view = v);
              _notify();
            },
          ),
        ),

        _Question(
          label: '相机到跑道的距离',
          why: '过近畸变大，过远关键点看不清',
          required: true,
          child: _NumberField(
            controller: _distance,
            suffix: '米',
            hint: '建议 8–15 米',
            validator: (v) => (v < 3 || v > 40) ? '应在 3–40 米之间' : null,
            onChanged: _notify,
          ),
        ),

        _Question(
          label: '相机高度',
          why: '偏离髋高会产生透视变形，角度会算偏',
          required: true,
          child: _NumberField(
            controller: _height,
            suffix: '米',
            hint: '建议与运动员髋同高，约 1.0–1.3 米',
            validator: (v) => (v < 0.3 || v > 3.0) ? '应在 0.3–3 米之间' : null,
            onChanged: _notify,
          ),
        ),

        _Question(
          label: '画面里能看到跑道分道线吗',
          why: '分道线间距是标准 1.22 米，用它才能把画面尺寸换算成实际距离。'
              '看不到的话，步幅等位移类指标算不出来',
          required: true,
          child: _YesNoUnknown(
            value: _hasLaneLine,
            yesLabel: '能看到',
            noLabel: '看不到',
            onChanged: (v) {
              setState(() => _hasLaneLine = v);
              _notify();
            },
          ),
        ),

        _Question(
          label: '镜头是否跟随运动员移动',
          why: '镜头转动会让运动员偏离画面中心，产生透视误差。'
              '跟随拍摄下位移类指标需要额外处理',
          required: true,
          child: _YesNoUnknown(
            value: _cameraFollowed,
            yesLabel: '跟着移动',
            noLabel: '固定不动',
            onChanged: (v) {
              setState(() => _cameraFollowed = v);
              _notify();
            },
          ),
        ),

        if (widget.athleteHeightCm == null)
          _Question(
            label: '运动员身高',
            why: '档案里没填。身高用于体型归一化，缺失时位移类指标精度受限',
            child: _NumberField(
              controller: _athleteHeight,
              suffix: 'cm',
              hint: '选填，但建议填上',
              validator: (v) => (v < 120 || v > 220) ? '应在 120–220 cm' : null,
              onChanged: _notify,
            ),
          ),

        _Question(
          label: '曝光是否锁定',
          why: '自动曝光会让关键点位置随亮度漂移，影响精度',
          child: _YesNoUnknown(
            value: _exposureLocked,
            yesLabel: '已锁定',
            noLabel: '自动',
            unknownAllowed: true,
            onChanged: (v) {
              setState(() => _exposureLocked = v);
              _notify();
            },
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------

class _Question extends StatelessWidget {
  const _Question({
    required this.label,
    required this.why,
    required this.child,
    this.required = false,
  });

  final String label;
  final String why;
  final Widget child;
  final bool required;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (required)
                  const Text('* ',
                      style: TextStyle(color: Color(0xFFC62828), fontSize: 14)),
                Expanded(
                  child: Text(
                    label,
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w500),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              why,
              style: TextStyle(
                  fontSize: 11, color: context.faintText, height: 1.4),
            ),
            const SizedBox(height: 8),
            child,
          ],
        ),
      );
}

class _NumberField extends StatefulWidget {
  const _NumberField({
    required this.controller,
    required this.suffix,
    required this.hint,
    required this.validator,
    required this.onChanged,
  });

  final TextEditingController controller;
  final String suffix;
  final String hint;
  final String? Function(double) validator;
  final VoidCallback onChanged;

  @override
  State<_NumberField> createState() => _NumberFieldState();
}

class _NumberFieldState extends State<_NumberField> {
  String? _error;

  void _handle(String _) {
    final t = widget.controller.text.trim();
    final v = double.tryParse(t);
    setState(() {
      _error = (t.isEmpty || v == null) ? null : widget.validator(v);
    });
    widget.onChanged();
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: widget.controller,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: _handle,
            decoration: InputDecoration(
              suffixText: widget.suffix,
              hintText: widget.hint,
              errorText: _error,
            ),
          ),
        ],
      );
}

class _YesNoUnknown extends StatelessWidget {
  const _YesNoUnknown({
    required this.value,
    required this.yesLabel,
    required this.noLabel,
    required this.onChanged,
    this.unknownAllowed = false,
  });

  final bool? value;
  final String yesLabel;
  final String noLabel;
  final void Function(bool?) onChanged;

  /// 是否允许「不确定」。
  ///
  /// 有些项必须允许 —— 逼用户猜会得到错误数据，
  /// 而允许「不确定」则服务端可以按最坏情况处理。
  final bool unknownAllowed;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      children: [
        ChoiceChip(
          label: Text(yesLabel),
          selected: value == true,
          onSelected: (_) => onChanged(true),
        ),
        ChoiceChip(
          label: Text(noLabel),
          selected: value == false,
          onSelected: (_) => onChanged(false),
        ),
        if (unknownAllowed)
          ChoiceChip(
            label: const Text('不确定'),
            selected: value == null,
            onSelected: (_) => onChanged(null),
          ),
      ],
    );
  }
}

/// 拍摄方位选择器。
///
/// 必须用图示 + 文字双重表达：教练不是工程师，
/// 「侧面 / 正面 / 背面」这三个词在没有图示时的理解差异很大。
class _ViewSelector extends StatelessWidget {
  const _ViewSelector({required this.value, required this.onChanged});

  final SessionView? value;
  final void Function(SessionView) onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            _Option(
              value: SessionView.side,
              current: value,
              icon: Icons.compare_arrows,
              title: '侧面',
              detail: '镜头在跑道旁边\n拍到侧身',
              gives: '关节角度、躯干前倾、步幅',
              onChanged: onChanged,
            ),
            const SizedBox(width: 8),
            _Option(
              value: SessionView.front,
              current: value,
              icon: Icons.south,
              title: '正面',
              detail: '镜头在运动员前方\n拍到他迎面跑来',
              gives: '骨盆控制、膝内扣、着地宽度',
              onChanged: onChanged,
            ),
            const SizedBox(width: 8),
            _Option(
              value: SessionView.back,
              current: value,
              icon: Icons.north,
              title: '背面',
              detail: '镜头在运动员后方\n拍到他跑远',
              gives: '同正面，另可看足跟外翻',
              onChanged: onChanged,
            ),
          ],
        ),
      ],
    );
  }
}

class _Option extends StatelessWidget {
  const _Option({
    required this.value,
    required this.current,
    required this.icon,
    required this.title,
    required this.detail,
    required this.gives,
    required this.onChanged,
  });

  final SessionView value;
  final SessionView? current;
  final IconData icon;
  final String title;
  final String detail;
  final String gives;
  final void Function(SessionView) onChanged;

  @override
  Widget build(BuildContext context) {
    final selected = current == value;

    return Expanded(
      child: InkWell(
        onTap: () => onChanged(value),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: EdgeInsets.all(10),
          decoration: BoxDecoration(
            border: Border.all(
              color: selected
                  ? Theme.of(context).colorScheme.primary
                  : context.hairline,
              width: selected ? 2 : 1,
            ),
            borderRadius: BorderRadius.circular(8),
            color: selected ? context.okSurface : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(icon, size: 16),
                  const SizedBox(width: 4),
                  Text(title,
                      style: const TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w600)),
                ],
              ),
              const SizedBox(height: 6),
              Text(detail,
                  style: TextStyle(
                      fontSize: 11, color: context.mutedText, height: 1.4)),
              const SizedBox(height: 6),
              Text('可测：$gives',
                  style: const TextStyle(
                      fontSize: 10, color: Color(0xFF2E7D32), height: 1.4)),
            ],
          ),
        ),
      ),
    );
  }
}
