import 'package:flutter/material.dart';

import '../data/auth_service.dart';
import '../domain/local_user.dart';
import '../widgets/user_avatar.dart';
import '../widgets/app_colors.dart';

/// 资料编辑页：改昵称、头像、身份。
///
/// ## 为什么昵称和身份不做成"点一下就改"
///
/// 这两项会出现在报告和运动员记录上。误触改掉之后，
/// 用户未必立刻发现，而历史记录上的署名已经变了。
/// 所以走一个明确的"保存"动作。
///
/// 头像相反 —— 它是纯视觉的，选错了看一眼就知道，
/// 所以点一下立即生效，符合直觉。
class ProfileEditPage extends StatefulWidget {
  const ProfileEditPage({
    super.key,
    required this.user,
    required this.auth,
  });

  final LocalUser user;
  final AuthService auth;

  @override
  State<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends State<ProfileEditPage> {
  late final TextEditingController _name;
  late String _avatarId;
  late String _role;

  bool _saving = false;
  bool _dirty = false;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.user.name);
    _avatarId = widget.user.avatarId;
    _role = widget.user.role;
    _name.addListener(_markDirty);
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _markDirty() {
    final changed = _name.text.trim() != widget.user.name ||
        _avatarId != widget.user.avatarId ||
        _role != widget.user.role;
    if (changed != _dirty) setState(() => _dirty = changed);
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      // 空昵称在报告和记录里会显示成一片空白，教练分不清是谁 ——
      // 所以在入口就拦住，而不是让它存进去再想办法显示。
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('昵称不能为空')),
      );
      return;
    }

    setState(() => _saving = true);
    final updated = await widget.auth.updateProfile(
      userId: widget.user.userId,
      name: name,
      avatarId: _avatarId,
      role: _role,
    );
    if (!mounted) return;
    setState(() => _saving = false);

    if (updated == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('保存失败：账号不存在')),
      );
      return;
    }
    Navigator.of(context).pop(updated);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('编辑资料'),
        actions: [
          TextButton(
            onPressed: (_saving || !_dirty) ? null : _save,
            child: _saving
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('保存'),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          // ---- 预览 ----
          Center(
            child: Column(
              children: [
                UserAvatar(avatarId: _avatarId, radius: 40),
                const SizedBox(height: 10),
                Text(
                  _name.text.trim().isEmpty ? '未命名' : _name.text.trim(),
                  style: const TextStyle(
                      fontSize: 17, fontWeight: FontWeight.w600),
                ),
                if (_role.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Container(
                    padding: EdgeInsets.symmetric(
                        horizontal: 10, vertical: 2),
                    decoration: BoxDecoration(
                      color: context.okSurface,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      _role,
                      style: const TextStyle(
                          fontSize: 11.5, color: Color(0xFF2E7D32)),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 28),

          // ---- 昵称 ----
          const _FieldLabel('昵称'),
          TextField(
            controller: _name,
            maxLength: 24,
            decoration: const InputDecoration(
              hintText: '例如：笨笨鱼',
              border: OutlineInputBorder(),
              isDense: true,
              counterText: '',
            ),
          ),
          Padding(
            padding: EdgeInsets.only(top: 6, left: 2),
            child: Text(
              '昵称会显示在开机欢迎语和报告署名上。',
              style: TextStyle(fontSize: 11.5, color: context.faintText),
            ),
          ),
          const SizedBox(height: 24),

          // ---- 头像 ----
          const _FieldLabel('头像'),
          AvatarPicker(
            selectedId: _avatarId,
            onSelected: (id) => setState(() {
              _avatarId = id;
              _markDirty();
            }),
          ),
          const SizedBox(height: 24),

          // ---- 身份 ----
          const _FieldLabel('身份'),
          Padding(
            padding: EdgeInsets.only(bottom: 8, left: 2),
            child: Text(
              '不同身份关注的重点不同，将来会据此调整默认展示内容。',
              style: TextStyle(fontSize: 11.5, color: context.faintText),
            ),
          ),
          Wrap(
            spacing: 10,
            children: [
              for (final r in LocalUser.roleOptions)
                ChoiceChip(
                  label: Text(r),
                  selected: _role == r,
                  onSelected: (sel) => setState(() {
                    // 再点一次取消选择 —— 允许"不填"，
                    // 而不是选了就再也去不掉。
                    _role = sel ? r : '';
                    _markDirty();
                  }),
                ),
            ],
          ),
          const SizedBox(height: 36),

          FilledButton(
            onPressed: (_saving || !_dirty) ? null : _save,
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
            ),
            child: Text(_saving ? '保存中…' : '保存修改'),
          ),
          const SizedBox(height: 12),
          Text(
            '手机号是账号标识，暂不支持修改。',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11.5, color: context.faintText),
          ),
        ],
      ),
    );
  }
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8, left: 2),
        child: Text(
          text,
          style: const TextStyle(
              fontSize: 13, fontWeight: FontWeight.w600),
        ),
      );
}
