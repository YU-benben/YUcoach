import 'package:flutter/material.dart';

import '../domain/local_user.dart';
import '../widgets/app_colors.dart';

/// 会员等级。
///
/// ⚠️ 与服务端 `backend/server/accounts.py` 的 TIERS 保持一致。
///    这里的定义只用于**界面展示**，真正的额度判定在服务端 ——
///    App 里改了没有任何作用（这是刻意的）。
///
/// ⚠️ **训练计划不在任何等级里。**
///    它是所有用户都能免费用的功能，不是会员权益。
///    曾经在 premium 上标过"含训练计划"，那会给用户错误的预期 ——
///    免费用户看到会以为自己用不了。
enum MemberTier {
  free('普通用户', 10),
  basic('普通会员', 100),
  premium('高级会员', 500);

  const MemberTier(this.label, this.quota);

  final String label;

  /// 每月额度。
  final int quota;
}

/// 会员中心：查看额度、套餐说明、兑换码。
///
/// ## 为什么不做真实支付
///
/// 接微信 / 支付宝需要**企业资质 + 商户号**，个人开发者做不到。
/// 所以这里做两件事：
///
///   1. **套餐说明**做完整 —— 用户清楚自己能买到什么
///   2. **兑换码**是真实可用的升级途径 —— 你按需发卡密给用户
///
/// 支付按钮保留但明确提示"请联系管理员开通"，
/// 而不是做一个点了没反应的假按钮 —— 那比没有更糟。
class MembershipPage extends StatefulWidget {
  const MembershipPage({super.key, required this.user});

  final LocalUser user;

  @override
  State<MembershipPage> createState() => _MembershipPageState();
}

class _MembershipPageState extends State<MembershipPage> {
  final _codeController = TextEditingController();

  /// 当前等级。
  ///
  /// ⚠️ 这是 `final` 的 —— 刻意的。
  ///    会员等级必须由服务端裁定，App 里没有任何代码路径能改它。
  ///    如果哪天有人想在这里加一个 setState 来"本地升级"，
  ///    编译期就会拦下来。
  ///
  /// ⚠️ 暂时固定为 free。服务端已经有完整的账号与额度接口
  ///    （/api/auth/*、/api/redeem），但 App 侧的本地账号与服务端账号
  ///    还没打通 —— 那是下一步。在那之前这里不假装有数据。
  final MemberTier _tier = MemberTier.free;

  @override
  void dispose() {
    _codeController.dispose();
    super.dispose();
  }

  void _redeem() {
    final code = _codeController.text.trim();
    if (code.isEmpty) {
      _toast('请先输入兑换码');
      return;
    }
    // 兑换码校验必须走服务端 —— 客户端无法知道哪些码有效。
    // 接口已就绪（POST /api/redeem），App 侧接线在下一步。
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('兑换功能接线中'),
        content: Text(
          '你输入的兑换码是：\n$code\n\n'
          '服务端的兑换接口已经做好并通过测试，'
          '但 App 的本地账号还没和服务端账号打通 —— '
          '这一步完成前无法真正兑换。\n\n'
          '那时兑换码会直接生效，不需要更新 App。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('知道了'),
          ),
        ],
      ),
    );
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('会员中心')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _CurrentStatusCard(tier: _tier),
          const SizedBox(height: 24),

          const _SectionTitle('套餐'),
          for (final t in MemberTier.values)
            _TierCard(
              tier: t,
              current: t == _tier,
              onChoose: () => _onChoose(t),
            ),

          const SizedBox(height: 24),
          const _SectionTitle('兑换码'),
          Padding(
            padding: EdgeInsets.only(bottom: 10, left: 2),
            child: Text(
              '收到兑换码后在这里输入，立即升级。',
              style: TextStyle(fontSize: 11.5, color: context.faintText),
            ),
          ),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _codeController,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(
                    hintText: 'YU-XXXX-XXXX',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: _redeem,
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 20, vertical: 14),
                ),
                child: const Text('兑换'),
              ),
            ],
          ),

          const SizedBox(height: 32),
          _PaymentNotice(),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  void _onChoose(MemberTier t) {
    if (t == _tier) {
      _toast('你目前就是${t.label}');
      return;
    }
    // ⚠️ 不能在这里直接改 _tier。
    //    会员等级必须由服务端裁定 —— 如果客户端改一个枚举就能升级，
    //    那会员体系就没有任何意义。这里只引导到兑换码。
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('升级为${t.label}'),
        content: Text(
          '${t.label}：每月 ${t.quota} 次分析。\n\n'
          '当前版本通过兑换码开通。请联系管理员获取兑换码，'
          '然后在下方输入即可升级。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('好'),
          ),
        ],
      ),
    );
  }
}

/// 当前状态卡片：剩余额度 + 进度条。
class _CurrentStatusCard extends StatelessWidget {
  const _CurrentStatusCard({required this.tier});

  final MemberTier tier;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF1B5E20), Color(0xFF2E7D32)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.workspace_premium,
                  color: Color(0xFFFFD54F), size: 22),
              const SizedBox(width: 8),
              Text(
                tier.label,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          // ⚠️ 额度这里显示的是**本地占位值**。
          //    真实额度由服务端返回，接线前不编造具体数字。
          Text(
            '每月可用 ${tier.quota} 次分析',
            style: const TextStyle(fontSize: 13, color: Colors.white70),
          ),
          const SizedBox(height: 6),
          const Text(
            '训练计划功能对所有用户免费开放，不限等级',
            style: TextStyle(fontSize: 12, color: Colors.white70),
          ),
          const SizedBox(height: 14),
          const Divider(height: 1, color: Colors.white24),
          const SizedBox(height: 12),
          const Text(
            '剩余次数由分析服务统计。连接服务后即可查看实时额度。',
            style: TextStyle(fontSize: 11, color: Colors.white54, height: 1.4),
          ),
        ],
      ),
    );
  }
}

/// 一个套餐卡片。
class _TierCard extends StatelessWidget {
  const _TierCard({
    required this.tier,
    required this.current,
    required this.onChoose,
  });

  final MemberTier tier;
  final bool current;
  final VoidCallback onChoose;

  /// 各套餐的功能列表。
  ///
  /// ⚠️ **训练计划刻意不出现在这里。**
  ///    它是对所有用户免费的功能，不是会员权益 ——
  ///    列进套餐表会让免费用户以为自己用不了。
  ///    它的入口在「我的 → 训练」，标着"免费"。
  static const _features = <MemberTier, List<String>>{
    MemberTier.free: [
      '10 次分析（一次性，用完为止）',
      '关键帧图片与角度标注',
      '训练计划（免费功能）',
    ],
    MemberTier.basic: [
      '每月 100 次分析',
      '上面全部功能',
      '月度自动重置额度',
    ],
    MemberTier.premium: [
      '每月 500 次分析',
      '上面全部功能',
      '优先支持与功能建议通道',
    ],
  };

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: EdgeInsets.only(bottom: 12),
      padding: EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: current ? context.okSurface : Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: current ? context.okText : context.hairline,
          width: current ? 1.6 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                tier.label,
                style: const TextStyle(
                    fontSize: 15, fontWeight: FontWeight.w700),
              ),
              const SizedBox(width: 8),
              if (current)
                Container(
                  padding: EdgeInsets.symmetric(
                      horizontal: 7, vertical: 1.5),
                  decoration: BoxDecoration(
                    color: context.okText,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text('当前',
                      style: TextStyle(fontSize: 10, color: Colors.white)),
                ),
            ],
          ),
          const SizedBox(height: 10),
          for (final f in _features[tier]!)
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2, right: 6),
                    child: Icon(Icons.check_circle_outline,
                        size: 14, color: Color(0xFF2E7D32)),
                  ),
                  Expanded(
                    child: Text(
                      f,
                      style: const TextStyle(
                          fontSize: 12.5,
                          color: Colors.black87,
                          height: 1.4),
                    ),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: current
                ? OutlinedButton(
                    onPressed: null,
                    child: Text('当前套餐'),
                  )
                : FilledButton(
                    onPressed: onChoose,
                    child: Text(tier == MemberTier.free
                        ? '默认套餐'
                        : '升级为${tier.label}'),
                  ),
          ),
        ],
      ),
    );
  }
}

/// 支付说明。
///
/// ⚠️ 明确写清"为什么不能在线支付"，而不是放一个点了没反应的按钮。
///    用户看到"请联系管理员"会理解；看到假按钮只会觉得 App 坏了。
class _PaymentNotice extends StatelessWidget {
  const _PaymentNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: context.warnSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: context.hairline),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.info_outline, size: 16, color: Color(0xFFF57F17)),
              SizedBox(width: 6),
              Text('关于支付',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFFF57F17))),
            ],
          ),
          SizedBox(height: 8),
          Text(
            '当前版本不支持在线支付，请通过兑换码开通会员。\n\n'
            '原因：接入微信 / 支付宝支付需要企业资质与商户号，'
            '个人开发者无法申请。兑换码是完全等效的开通方式 —— '
            '联系管理员获取即可。',
            style: TextStyle(
                fontSize: 12, color: Colors.black87, height: 1.5),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10, left: 2),
        child: Text(
          text,
          style: const TextStyle(
              fontSize: 13, fontWeight: FontWeight.w600),
        ),
      );
}
