import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/analysis_server_client.dart';

/// 关键帧图片 URL 的拼装。
///
/// ## 为什么要单独测这个
///
/// 报告里的图片地址是**相对路径**（`keyframes/<任务ID>/f000014_touchdown.jpg`），
/// 要由客户端拼上服务地址才能取图。这段拼接有个特点：
///
///     拼错了不会抛异常，只会显示一张破图。
///
/// `http://10.0.0.1:8770//keyframes/...`（多一道斜杠）或者漏掉任务 ID，
/// 错误表现都只是"图没出来"—— 而界面同时还要区分另外两种情况
/// （没配地址 / 服务没开）。三者混在一起，光看界面根本分不清。
///
/// 所以把判定逻辑抽成纯函数 `ServerConfig.resolveUrl` 并在这里钉死。
void main() {
  group('resolveUrl 正常拼装', () {
    test('拼接服务地址与相对路径', () {
      expect(
        ServerConfig.resolveUrl(
          'http://192.168.1.5:8770',
          'keyframes/job123/f000014_touchdown.jpg',
        ),
        'http://192.168.1.5:8770/keyframes/job123/f000014_touchdown.jpg',
      );
    });

    test('两侧都有斜杠时不会拼出双斜杠', () {
      // 服务地址带结尾斜杠 + 相对路径带开头斜杠。
      // 用户手输或经代理时很常见。
      final got = ServerConfig.resolveUrl(
        'http://192.168.1.5:8770/',
        '/keyframes/job123/f000014_touchdown.jpg',
      );
      expect(got, isNot(contains('8770//keyframes')));
      expect(
        got,
        'http://192.168.1.5:8770/keyframes/job123/f000014_touchdown.jpg',
      );
    });

    test('只填 IP:端口 时自动补 http://', () {
      expect(
        ServerConfig.resolveUrl('192.168.1.5:8770', 'keyframes/j1/a.jpg'),
        'http://192.168.1.5:8770/keyframes/j1/a.jpg',
      );
    });

    test('相对路径本身是绝对 URL 时原样返回', () {
      // 便于服务端将来改成直传完整 URL，客户端不用改。
      expect(
        ServerConfig.resolveUrl(
          'http://192.168.1.5:8770',
          'http://cdn.example.com/a.jpg',
        ),
        'http://cdn.example.com/a.jpg',
      );
    });
  });

  group('resolveUrl 必须返回 null 的情况', () {
    // 返回 null 而不是一个坏 URL，界面才能区分「没配地址」和「服务没开」。
    // 若返回 `http:///keyframes/...` 这类坏地址，界面只会显示破图，
    // 用户不知道该去配地址还是去开服务。

    test('服务地址为空', () {
      expect(ServerConfig.resolveUrl(null, 'keyframes/j1/a.jpg'), isNull);
      expect(ServerConfig.resolveUrl('', 'keyframes/j1/a.jpg'), isNull);
      expect(ServerConfig.resolveUrl('   ', 'keyframes/j1/a.jpg'), isNull);
    });

    test('相对路径为空', () {
      expect(ServerConfig.resolveUrl('http://192.168.1.5:8770', null), isNull);
      expect(ServerConfig.resolveUrl('http://192.168.1.5:8770', ''), isNull);
      expect(ServerConfig.resolveUrl('http://192.168.1.5:8770', '  '), isNull);
    });

    test('两者都为空', () {
      expect(ServerConfig.resolveUrl(null, null), isNull);
    });

    test('任何输入都不产出没有主机的坏地址', () {
      for (final base in [null, '', '   ', '192.168.1.5:8770']) {
        final got = ServerConfig.resolveUrl(base, 'keyframes/j1/a.jpg');
        if (got != null) {
          expect(got.startsWith('http:///'), isFalse,
              reason: 'base=$base 拼出了没有主机的地址：$got');
          expect(got, contains('://'));
        }
      }
    });
  });

  group('normalize 未被改坏', () {
    // resolveUrl 复用了 normalize，改动它要一并确认这里。
    test('补协议与去结尾斜杠', () {
      expect(ServerConfig.normalize('192.168.1.5:8770'),
          'http://192.168.1.5:8770');
      expect(ServerConfig.normalize('http://a.b/'), 'http://a.b');
      expect(ServerConfig.normalize('  http://a.b  '), 'http://a.b');
      expect(ServerConfig.normalize('https://a.b'), 'https://a.b');
      expect(ServerConfig.normalize(''), '');
    });
  });
}
