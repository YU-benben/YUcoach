import 'package:flutter/material.dart';

import '../data/auth_service.dart';
import '../widgets/app_colors.dart';

/// 登录 / 注册页。
///
/// 一个页面承载两种模式：首次安装时默认注册，有账号后默认登录。
/// 不做成两个页面 —— 教练只需要「进去」，不该先理解模式的概念。
class LoginPage extends StatefulWidget {
  const LoginPage({
    super.key,
    required this.auth,
    required this.onLoggedIn,
    this.initialRegisterMode = false,
  });

  final AuthService auth;
  final void Function() onLoggedIn;
  final bool initialRegisterMode;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _formKey = GlobalKey<FormState>();

  /// 登录用：手机号**或**用户名，一个框两种都认。
  final _account = TextEditingController();

  /// 注册用：三个独立字段。见下面 _registerMode 的说明。
  final _regUsername = TextEditingController();
  final _regPhone = TextEditingController();
  final _name = TextEditingController();
  final _password = TextEditingController();
  final _passwordConfirm = TextEditingController();

  late bool _registerMode = widget.initialRegisterMode;
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _account.dispose();
    _regUsername.dispose();
    _regPhone.dispose();
    _name.dispose();
    _password.dispose();
    _passwordConfirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _error = null);
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _busy = true);
    final result = _registerMode
        ? await widget.auth.register(
            // 用户名必填：它是**服务端身份**，提交分析时要用它认账号、
            // 扣额度。以前这里允许"手机号或用户名二选一"，
            // 结果用手机号注册的账号在服务端没有名字 —— 提交分析时
            // 只会收到一句「请先登录」，而用户明明已经登录。
            username: _regUsername.text,
            phone: _regPhone.text,
            name: _name.text,
            password: _password.text,
            passwordConfirm: _passwordConfirm.text,
          )
        : await widget.auth.login(
            loginId: _account.text,
            password: _password.text,
          );

    if (!mounted) return;
    setState(() => _busy = false);

    if (result.ok) {
      widget.onLoggedIn();
    } else {
      setState(() => _error = result.error?.message ?? '操作失败，请重试');
    }
  }

  /// 登录框的校验：**不做格式校验**。
  ///
  /// 因为账号可能是手机号也可能是用户名，两种格式差别很大。
  /// 在这里猜类型只会把合法输入挡在门外（比如用户名 `MazingLIU`
  /// 会被"请输入 11 位手机号"拦住）。
  /// 真正的判定交给 AuthService.login()，它会两种都比对一遍。
  String? _validateLoginId(String? v) {
    if ((v ?? '').trim().isEmpty) return '请输入手机号或用户名';
    return null;
  }

  /// 注册时的用户名。它是**服务端身份**，所以规则与服务端一致（2–24 位）。
  String? _validateUsername(String? v) {
    final s = (v ?? '').trim();
    if (s.isEmpty) return '请填写用户名';
    return AuthService.isValidUsername(s)
        ? null
        : '用户名需 2–24 位，可用字母、数字、下划线';
  }

  /// 注册时的手机号。选填 —— 但填了就必须合法。
  String? _validateOptionalPhone(String? v) {
    final s = (v ?? '').trim();
    if (s.isEmpty) return null;
    return AuthService.isValidPhone(s) ? null : '请输入 11 位手机号';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: 24),
                  // 品牌形象。用图而不是 Material 图标 ——
                  // 这是用户对产品的第一印象，值得用专属视觉。
                  // 图已打包进 App，不依赖网络（训练场信号常常很差）。
                  Center(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(26),
                      child: Image.asset(
                        'assets/branding/logo.png',
                        width: 116,
                        height: 116,
                        filterQuality: FilterQuality.medium,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'YUcoach',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                  SizedBox(height: 4),
                  Text(
                    '短跑跑姿分析',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: context.mutedText),
                  ),
                  const SizedBox(height: 32),

                  // 注册与登录的字段不同，这是刻意的。
                  //
                  // 注册要一次问清「用户名 + 昵称 + 手机号」三项：
                  //   用户名  服务端的身份，提交分析时用来认账号、扣额度
                  //   昵称    界面上显示的名字
                  //   手机号  选填，方便日后找回账号
                  //
                  // ⚠️ 以前这里是个"手机号 / 用户名"二选一的切换。
                  //    结果是：用手机号注册的账号在服务端没有名字，
                  //    提交分析时收到「请先登录」——而用户明明登录了。
                  //    一个身份分两种，是问题的源头。
                  if (_registerMode) ...[
                    TextFormField(
                      controller: _regUsername,
                      decoration: const InputDecoration(
                        labelText: '用户名',
                        helperText: '登录用，也是电脑端记账的依据',
                        prefixIcon: Icon(Icons.badge_outlined),
                        border: OutlineInputBorder(),
                      ),
                      validator: _validateUsername,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _name,
                      decoration: const InputDecoration(
                        labelText: '昵称',
                        helperText: '界面上显示的名字',
                        prefixIcon: Icon(Icons.person_outline),
                        border: OutlineInputBorder(),
                      ),
                      validator: (v) =>
                          (v ?? '').trim().isEmpty ? '请填写昵称' : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _regPhone,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(
                        labelText: '手机号（选填）',
                        helperText: '只用来日后找回账号，不填也能用',
                        prefixIcon: Icon(Icons.phone_outlined),
                        border: OutlineInputBorder(),
                      ),
                      validator: _validateOptionalPhone,
                    ),
                    const SizedBox(height: 16),
                  ] else ...[
                    TextFormField(
                      controller: _account,
                      decoration: const InputDecoration(
                        labelText: '手机号或用户名',
                        prefixIcon: Icon(Icons.account_circle_outlined),
                        border: OutlineInputBorder(),
                      ),
                      validator: _validateLoginId,
                    ),
                    const SizedBox(height: 16),
                  ],

                  TextFormField(
                    controller: _password,
                    obscureText: _obscure,
                    decoration: InputDecoration(
                      labelText: '密码',
                      prefixIcon: const Icon(Icons.lock_outline),
                      border: const OutlineInputBorder(),
                      suffixIcon: IconButton(
                        icon: Icon(_obscure
                            ? Icons.visibility_off_outlined
                            : Icons.visibility_outlined),
                        onPressed: () => setState(() => _obscure = !_obscure),
                      ),
                    ),
                    validator: (v) =>
                        (v ?? '').length < 6 ? '密码至少 6 位' : null,
                  ),

                  if (_registerMode) ...[
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _passwordConfirm,
                      obscureText: true,
                      decoration: const InputDecoration(
                        labelText: '确认密码',
                        prefixIcon: Icon(Icons.lock_outline),
                        border: OutlineInputBorder(),
                      ),
                      validator: (v) =>
                          v != _password.text ? '两次输入的密码不一致' : null,
                    ),
                  ],

                  if (_error != null) ...[
                    const SizedBox(height: 16),
                    Container(
                      width: double.infinity,
                      padding: EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: context.errorSurface,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline,
                              size: 18, color: Color(0xFFC62828)),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _error!,
                              style: const TextStyle(color: Color(0xFFC62828)),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],

                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: _busy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(_registerMode ? '注册并进入' : '登录'),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => setState(() {
                              _registerMode = !_registerMode;
                              _error = null;
                            }),
                    child: Text(_registerMode ? '已有账号？去登录' : '还没有账号？去注册'),
                  ),

                  const SizedBox(height: 24),
                  _LocalAccountNotice(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 必须告诉用户「账号只存在本机」。
///
/// 不说明的话，教练会以为换了手机还能登进去，或者以为这是云端账号。
/// 这类预期落差比功能缺失更伤信任。
class _LocalAccountNotice extends StatelessWidget {
  const _LocalAccountNotice();

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: context.subtleSurface,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.info_outline, size: 16, color: context.faintText),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                '账号仅保存在本机，不会上传。更换设备后需要重新注册。\n'
                '运动员信息与分析记录同样只存在本机。',
                style: TextStyle(
                  fontSize: 12,
                  color: context.mutedText,
                  height: 1.5,
                ),
              ),
            ),
          ],
        ),
      );
}
