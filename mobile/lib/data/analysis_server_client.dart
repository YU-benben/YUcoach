import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// 分析服务端返回的错误。带上是哪一类问题，便于界面给出不同提示。
class ServerException implements Exception {
  ServerException(this.message, {this.statusCode, this.hint});

  final String message;
  final int? statusCode;

  /// 可操作的下一步提示。为空时界面只显示 message。
  final String? hint;

  @override
  String toString() => message;
}

/// 分析服务的连接配置。
class ServerConfig {
  const ServerConfig({required this.baseUrl});

  /// 形如 `http://192.168.1.5:8770`（不带结尾斜杠）。
  final String baseUrl;

  /// 规范化用户输入：补协议、去结尾斜杠。
  ///
  /// 教练会输入 `192.168.1.5:8770` 这类不带协议的地址 ——
  /// 直接拼 URL 会失败，而报错信息对用户毫无意义。
  static String normalize(String input) {
    var s = input.trim();
    if (s.isEmpty) return s;
    if (!s.startsWith('http://') && !s.startsWith('https://')) {
      s = 'http://$s';
    }
    while (s.endsWith('/')) {
      s = s.substring(0, s.length - 1);
    }
    return s;
  }

  /// 把服务端返回的**相对路径**拼成完整 URL。
  ///
  /// 为什么需要它：报告里的图片地址形如
  /// `keyframes/<任务ID>/f000014_touchdown.jpg` —— 是相对路径。
  /// 分析引擎不知道自己被哪个地址访问（见 analyze.py 里
  /// keyframe_url_prefix 的注释），所以拼接只能由客户端做。
  ///
  /// 返回 null 表示拼不出来（地址为空）。**不要返回一个坏 URL** ——
  /// 那样界面只会显示一张破图，看不出是"没配地址"还是"服务没开"。
  ///
  /// 已经带协议的绝对地址原样返回，便于服务端将来改成直传完整 URL。
  static String? resolveUrl(String? baseUrl, String? relativePath) {
    final rel = (relativePath ?? '').trim();
    if (rel.isEmpty) return null;
    if (rel.startsWith('http://') || rel.startsWith('https://')) return rel;

    final base = normalize(baseUrl ?? '');
    if (base.isEmpty) return null;

    // 两侧都可能有斜杠，统一去掉后再拼，避免出现 `//keyframes`
    final r = rel.startsWith('/') ? rel.substring(1) : rel;
    return '$base/$r';
  }
}

/// 服务端状态。
class ServerHealth {
  const ServerHealth({
    required this.ok,
    required this.version,
    required this.cudaAvailable,
    this.gpu,
    this.torchVersion,
    this.jobsRunning = 0,
  });

  final bool ok;
  final String version;
  final bool cudaAvailable;
  final String? gpu;
  final String? torchVersion;
  final int jobsRunning;

  static ServerHealth fromJson(Map<String, dynamic> json) {
    final engine = (json['engine'] as Map?)?.cast<String, dynamic>() ?? {};
    return ServerHealth(
      ok: json['ok'] == true,
      version: json['version'] as String? ?? '未知',
      cudaAvailable: engine['cuda_available'] == true,
      gpu: engine['gpu'] as String?,
      torchVersion: engine['torch'] as String?,
      jobsRunning: (json['jobs_running'] as num?)?.toInt() ?? 0,
    );
  }
}

/// 一个分析任务的进度。
class JobProgress {
  const JobProgress({
    required this.jobId,
    required this.status,
    required this.progress,
    required this.stage,
    this.error,
    this.errorDetail,
    this.report,
    this.elapsedSeconds,
  });

  final String jobId;

  /// queued / running / done / failed
  final String status;
  final double progress;
  final String stage;
  final String? error;
  final String? errorDetail;
  final Map<String, dynamic>? report;
  final double? elapsedSeconds;

  bool get isDone => status == 'done';
  bool get isFailed => status == 'failed';
  bool get isFinished => isDone || isFailed;

  static JobProgress fromJson(Map<String, dynamic> json) => JobProgress(
        jobId: json['job_id'] as String? ?? '',
        status: json['status'] as String? ?? 'unknown',
        progress: ((json['progress'] as num?)?.toDouble() ?? 0).clamp(0, 1),
        stage: json['stage'] as String? ?? '',
        error: json['error'] as String?,
        errorDetail: json['error_detail'] as String?,
        report: (json['report'] as Map?)?.cast<String, dynamic>(),
        elapsedSeconds: (json['elapsed_s'] as num?)?.toDouble(),
      );
}

/// 分析服务客户端。
///
/// 与后端 backend/server/app.py 的接口一一对应。
/// 界面不直接用这个类 —— 它只依赖 AnalysisRepository 接口，
/// 这样从假数据切到真服务时业务代码不用改。
class AnalysisServerClient {
  AnalysisServerClient({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  /// 单次请求超时。上传大文件时不能太短。
  static const _timeout = Duration(seconds: 30);

  /// 上传超时按"每 MB 给 2 秒 + 30 秒保底"算。
  /// 局域网通常远快于此，但慢速 WiFi 下需要留足余量。
  Duration _uploadTimeout(int bytes) =>
      Duration(seconds: 30 + (bytes ~/ (1024 * 1024)) * 2);

  // -- 健康检查 -----------------------------------------------------------

  /// 探测服务是否可用。失败抛 ServerException。
  Future<ServerHealth> health(String baseUrl) async {
    final uri = Uri.parse('${ServerConfig.normalize(baseUrl)}/api/health');
    try {
      final resp = await _client.get(uri).timeout(const Duration(seconds: 6));
      if (resp.statusCode != 200) {
        throw ServerException(
          '服务返回 ${resp.statusCode}',
          statusCode: resp.statusCode,
        );
      }
      return ServerHealth.fromJson(
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>,
      );
    } on SocketException {
      throw ServerException(
        '连不上这个地址',
        hint: '确认电脑上已启动分析服务，且手机与电脑在同一个 WiFi。',
      );
    } on TimeoutException {
      throw ServerException(
        '连接超时',
        hint: '地址可能不对，或电脑防火墙拦住了。',
      );
    } on FormatException {
      throw ServerException(
        '返回的不是预期的数据',
        hint: '这个地址上可能不是 YUcoach 分析服务。',
      );
    }
  }

  // -- 上传 ---------------------------------------------------------------

  /// 上传视频文件。
  ///
  /// 用**流式**请求体：慢动作素材常有几百 MB，
  /// 一次性读进内存会在手机上触发 OOM。
  /// 流式上传的峰值内存占用与文件大小无关。
  ///
  /// [onProgress] 回调 0–1 的上传进度。
  /// 返回 videoId。
  Future<String> uploadVideo(
    File file, {
    required String baseUrl,
    void Function(double)? onProgress,
  }) async {
    final size = await file.length();
    final uri = Uri.parse('${ServerConfig.normalize(baseUrl)}/api/videos');

    final request = http.StreamedRequest('POST', uri);
    request.headers['Content-Type'] = 'application/octet-stream';
    request.headers['X-Filename'] =
        Uri.encodeComponent(file.uri.pathSegments.last);
    request.contentLength = size;

    // 一边读一边发。用 pipe 而不是先读后发，避免整块驻留内存。
    var sent = 0;
    final stream = file.openRead().map((chunk) {
      sent += chunk.length;
      onProgress?.call(size > 0 ? (sent / size).clamp(0, 1) : 0);
      return chunk;
    });

    // 必须在开始发送前就挂上 pipe
    unawaited(stream.pipe(request.sink));

    http.StreamedResponse resp;
    try {
      resp = await _client.send(request).timeout(_uploadTimeout(size));
    } on SocketException {
      throw ServerException(
        '上传中断，连不上服务',
        hint: '检查 WiFi 是否还连着，以及分析服务是否仍在运行。',
      );
    } on TimeoutException {
      throw ServerException(
        '上传超时',
        hint: '文件较大或网络较慢。可靠近路由器再试，或改用更短的片段。',
      );
    }

    final body = await resp.stream.bytesToString();
    final json = _decode(body, resp.statusCode);

    if (resp.statusCode != 201) {
      throw ServerException(
        json['error'] as String? ?? '上传失败（${resp.statusCode}）',
        statusCode: resp.statusCode,
      );
    }
    return json['video_id'] as String;
  }

  // -- 提交分析 -----------------------------------------------------------

  /// 提交分析任务，返回 jobId。
  Future<String> submitAnalysis({
    required String baseUrl,
    required String videoId,
    required String athleteId,
    required String athleteName,
    String gender = 'male',
    String event = '100m',
    String level = 'college',
    double? heightCm,
    String view = 'side',
    String testType = 'acceleration',
    double? cameraDistanceM,
    double? cameraHeightM,
    bool? hasLaneLine,
    bool? cameraFollowed,
    String? sessionId,
    String teamId = 't_local',
  }) async {
    final uri = Uri.parse('${ServerConfig.normalize(baseUrl)}/api/analyze');
    final payload = <String, dynamic>{
      'video_id': videoId,
      'athlete_id': athleteId,
      'athlete_name': athleteName,
      'gender': gender,
      'event': event,
      'level': level,
      'view': view,
      'test_type': testType,
      'team_id': teamId,
    };
    if (heightCm != null) payload['height_cm'] = heightCm;
    if (cameraDistanceM != null) payload['camera_distance_m'] = cameraDistanceM;
    if (cameraHeightM != null) payload['camera_height_m'] = cameraHeightM;
    if (hasLaneLine != null) payload['has_lane_line'] = hasLaneLine;
    if (cameraFollowed != null) payload['camera_followed'] = cameraFollowed;
    if (sessionId != null) payload['session_id'] = sessionId;

    try {
      final resp = await _client
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(payload),
          )
          .timeout(_timeout);

      final json = _decode(utf8.decode(resp.bodyBytes), resp.statusCode);
      if (resp.statusCode != 202) {
        throw ServerException(
          json['error'] as String? ?? '提交失败（${resp.statusCode}）',
          statusCode: resp.statusCode,
        );
      }
      return json['job_id'] as String;
    } on SocketException {
      throw ServerException('连不上分析服务');
    } on TimeoutException {
      throw ServerException('提交超时');
    }
  }

  // -- 查询任务 -----------------------------------------------------------

  Future<JobProgress> jobStatus({
    required String baseUrl,
    required String jobId,
  }) async {
    final uri =
        Uri.parse('${ServerConfig.normalize(baseUrl)}/api/jobs/$jobId');
    try {
      final resp = await _client.get(uri).timeout(_timeout);
      final json = _decode(utf8.decode(resp.bodyBytes), resp.statusCode);
      if (resp.statusCode == 404) {
        throw ServerException(
          json['error'] as String? ?? '任务不存在',
          statusCode: 404,
          hint: '分析服务可能已重启。请重新提交这次分析。',
        );
      }
      if (resp.statusCode != 200) {
        throw ServerException(
          json['error'] as String? ?? '查询失败（${resp.statusCode}）',
          statusCode: resp.statusCode,
        );
      }
      return JobProgress.fromJson(json);
    } on SocketException {
      throw ServerException('连不上分析服务');
    }
  }

  /// 轮询直到任务结束。
  ///
  /// 用轮询而不是 WebSocket：分析只需几十秒，轮询实现简单、
  /// 断线恢复自然（重连后继续查同一个 jobId），
  /// 而长连接的保活与重连逻辑在移动网络下容易出问题。
  Stream<JobProgress> watchJob({
    required String baseUrl,
    required String jobId,
    Duration interval = const Duration(seconds: 1),
    Duration timeout = const Duration(minutes: 10),
  }) async* {
    final deadline = DateTime.now().add(timeout);
    var errorStreak = 0;

    while (DateTime.now().isBefore(deadline)) {
      try {
        final p = await jobStatus(baseUrl: baseUrl, jobId: jobId);
        errorStreak = 0;
        yield p;
        if (p.isFinished) return;
      } on ServerException catch (e) {
        // 404 说明服务重启了，任务已经不可能有结果 —— 立刻放弃，
        // 不要让用户白等十分钟。
        if (e.statusCode == 404) rethrow;

        // 其它错误（网络抖动）容忍几次连续失败，
        // 超过就放弃并如实报告，而不是无限重试。
        errorStreak++;
        if (errorStreak >= 5) rethrow;
      }
      await Future<void>.delayed(interval);
    }
    throw ServerException(
      '分析超时',
      hint: '素材可能过长或服务负载高。可以试试更短的片段。',
    );
  }

  void close() => _client.close();

  // -- 内部 ---------------------------------------------------------------

  Map<String, dynamic> _decode(String body, int status) {
    if (body.isEmpty) return {};
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) return decoded;
      return {'error': '服务返回了非预期的数据结构'};
    } on FormatException {
      return {
        'error': '服务返回的内容不是 JSON（HTTP $status）',
      };
    }
  }
}
