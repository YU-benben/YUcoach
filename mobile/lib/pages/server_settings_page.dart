import 'package:flutter/material.dart';

import '../data/analysis_server_client.dart';
import '../data/local_store.dart';
import '../widgets/app_colors.dart';

/// 分析服务的连接设置。
///
/// 为什么需要用户手动配：分析引擎跑在电脑上（手机算不动），
/// 而 App 需要知道那台电脑在局域网里的地址。
/// 自动发现（mDNS）在训练场的网络环境下不可靠 ——
/// 很多场所的 WiFi 关闭了组播，所以手动填一个地址最可控。
class ServerSettings {
  ServerSettings({LocalStore? store})
      : _store = store ?? LocalStore(fileName: 'settings.json');

  final LocalStore _store;

  static const _urlKey = 'server_base_url';

  Future<String?> baseUrl() async {
    final doc = await _store.read();
    final v = doc[_urlKey] as String?;
    return (v == null || v.isEmpty) ? null : v;
  }

  Future<void> setBaseUrl(String url) async {
    final doc = await _store.read();
    doc[_urlKey] = ServerConfig.normalize(url);
    await _store.write(doc);
  }
}

/// 分析服务的连接与状态检测页。
class ServerSettingsPage extends StatefulWidget {
  const ServerSettingsPage({super.key, required this.settings});

  final ServerSettings settings;

  @override
  State<ServerSettingsPage> createState() => _ServerSettingsPageState();
}

class _ServerSettingsPageState extends State<ServerSettingsPage> {
  final _controller = TextEditingController();
  final _client = AnalysisServerClient();

  bool _testing = false;
  ServerHealth? _health;
  String? _error;
  String? _hint;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    _client.close();
    super.dispose();
  }

  Future<void> _load() async {
    final url = await widget.settings.baseUrl();
    if (!mounted) return;
    setState(() {
      _controller.text = url ?? '';
    });
    if (url != null) _test();
  }

  Future<void> _test() async {
    final raw = _controller.text.trim();
    if (raw.isEmpty) {
      setState(() {
        _error = '请先填写分析服务的地址';
        _hint = '在运行分析服务的电脑上，启动时会打印「手机访问」的地址。';
        _health = null;
      });
      return;
    }

    setState(() {
      _testing = true;
      _error = null;
      _hint = null;
      _health = null;
    });

    final url = ServerConfig.normalize(raw);
    try {
      final h = await _client.health(url);
      await widget.settings.setBaseUrl(url);
      if (!mounted) return;
      setState(() {
        _testing = false;
        _health = h;
        _controller.text = url;
      });
    } on ServerException catch (e) {
      if (!mounted) return;
      setState(() {
        _testing = false;
        _error = e.message;
        _hint = e.hint;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _testing = false;
        _error = '$e';
      });
    }
  }

  Future<void> _clear() async {
    await widget.settings.setBaseUrl('');
    if (!mounted) return;
    setState(() {
      _controller.clear();
      _health = null;
      _error = null;
      _hint = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('分析服务')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const _Explainer(),
          const SizedBox(height: 20),

          TextField(
            controller: _controller,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '服务地址',
              hintText: '例如 192.168.1.5:8770',
              helperText: '可以只填 IP 和端口，会自动补上 http://',
            ),
            onSubmitted: (_) => _test(),
          ),
          const SizedBox(height: 12),

          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _testing ? null : _test,
                  icon: _testing
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.wifi_tethering),
                  label: Text(_testing ? '正在连接…' : '连接并保存'),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                onPressed: _testing ? null : _clear,
                child: const Text('清除'),
              ),
            ],
          ),

          if (_error != null) ...[
            const SizedBox(height: 16),
            _StatusCard(
              ok: false,
              title: _error!,
              detail: _hint,
            ),
          ],

          if (_health != null) ...[
            const SizedBox(height: 16),
            _HealthCard(health: _health!),
          ],
        ],
      ),
    );
  }
}

class _Explainer extends StatelessWidget {
  const _Explainer();

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: context.okSurface,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.info_outline, size: 18, color: Color(0xFF2E7D32)),
                SizedBox(width: 6),
                Text('为什么需要一个地址',
                    style: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF2E7D32))),
              ],
            ),
            SizedBox(height: 8),
            Text(
              '跑姿分析的计算量很大 —— 一段 5 秒的慢动作视频有上千帧，'
              '手机跑不动。所以分析在电脑上完成，手机负责拍摄、上传和看结果。',
              style: TextStyle(fontSize: 13, color: Colors.black87, height: 1.6),
            ),
            SizedBox(height: 8),
            Text(
              '在电脑上启动分析服务时，它会打印一行「手机访问」的地址，'
              '把它填到这里即可。\n'
              '手机和电脑需要在同一个 WiFi 下。',
              style: TextStyle(fontSize: 12, color: context.mutedText, height: 1.6),
            ),
          ],
        ),
      );
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.ok, required this.title, this.detail});

  final bool ok;
  final String title;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final color = ok ? context.okText : context.errorText;
    final bg = ok ? context.okSurface : context.errorSurface;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(ok ? Icons.check_circle_outline : Icons.error_outline,
                  size: 18, color: color),
              const SizedBox(width: 6),
              Expanded(
                child: Text(title,
                    style: TextStyle(
                        color: color, fontWeight: FontWeight.w600)),
              ),
            ],
          ),
          if (detail != null) ...[
            const SizedBox(height: 6),
            Text(detail!,
                style: TextStyle(
                    fontSize: 13, color: context.mutedText, height: 1.5)),
          ],
        ],
      ),
    );
  }
}

class _HealthCard extends StatelessWidget {
  const _HealthCard({required this.health});

  final ServerHealth health;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _StatusCard(ok: true, title: '已连接（服务版本 ${health.version}）'),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Color(0xFFFAFAFA),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: context.hairline),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _row(context, '计算设备',
                  health.cudaAvailable ? (health.gpu ?? 'GPU') : 'CPU'),
              if (health.torchVersion != null)
                _row(context, '引擎', 'PyTorch ${health.torchVersion}'),
              _row(context, '进行中的任务', '${health.jobsRunning}'),
            ],
          ),
        ),
        if (!health.cudaAvailable) ...[
          const SizedBox(height: 12),
          _StatusCard(
            ok: false,
            title: '这台电脑没有可用的 GPU',
            detail: '没有 GPU 时分析会慢很多（可能十几分钟）。'
                '建议在有独立显卡的电脑上运行分析服务。',
          ),
        ],
      ],
    );
  }

  Widget _row(BuildContext context, String k, String v) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 88,
              child: Text(k,
                  style: TextStyle(fontSize: 12, color: context.faintText)),
            ),
            Expanded(
              child: Text(v, style: const TextStyle(fontSize: 13)),
            ),
          ],
        ),
      );
}
