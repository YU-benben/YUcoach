import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 本地 JSON 存储。
///
/// 为什么是 JSON 而不是 SQLite：
///   现阶段是单教练、几十到几百条记录的量级，JSON 完全够用，
///   且不需要 build_runner 代码生成与原生库编译，构建链路最短。
///   数据量上来后换成 SQLite，只改这一层，上层不动。
///
/// 关键设计：**原子写入**。
/// 直接覆写原文件的话，写到一半断电/崩溃会留下半个 JSON，
/// 下次启动直接解析失败 —— 用户的数据就没了。
/// 因此先写临时文件再 rename，rename 在同一文件系统内是原子的。
class LocalStore {
  LocalStore({required this.fileName, Directory? baseDir})
      : _baseDirOverride = baseDir;

  /// 存储文件名，如 users.json / athletes.json
  final String fileName;

  /// 仅测试使用：注入临时目录，避免污染真实用户数据
  final Directory? _baseDirOverride;

  Map<String, dynamic>? _cache;
  Directory? _dir;

  Future<Directory> _resolveDir() async {
    if (_dir != null) return _dir!;
    final dir = _baseDirOverride ?? await getApplicationSupportDirectory();
    if (!dir.existsSync()) {
      dir.createSync(recursive: true);
    }
    _dir = dir;
    return dir;
  }

  Future<File> _file() async => File('${(await _resolveDir()).path}/$fileName');

  /// 读取整个文档。文件不存在时返回空文档（首次使用是正常情况，不是错误）。
  Future<Map<String, dynamic>> read() async {
    if (_cache != null) return _cache!;

    final f = await _file();
    if (!f.existsSync()) {
      return _cache = <String, dynamic>{};
    }

    final text = await f.readAsString();
    if (text.trim().isEmpty) {
      return _cache = <String, dynamic>{};
    }

    try {
      final decoded = jsonDecode(text);
      if (decoded is! Map<String, dynamic>) {
        // 顶层结构不对，说明文件被外部改坏了。不静默丢弃，留证据。
        await _quarantine(f, '顶层不是 JSON 对象');
        return _cache = <String, dynamic>{};
      }
      return _cache = decoded;
    } on FormatException catch (e) {
      // JSON 损坏：改名备份后从空开始，避免用户连 App 都进不去。
      // 不删除原文件 —— 万一是可修复的，还留有机会。
      await _quarantine(f, 'JSON 解析失败: ${e.message}');
      return _cache = <String, dynamic>{};
    }
  }

  /// 把损坏的文件改名备份，让 App 能继续启动。
  Future<void> _quarantine(File f, String reason) async {
    try {
      final stamp = DateTime.now().millisecondsSinceEpoch;
      final backup = File('${f.path}.corrupt-$stamp');
      await f.rename(backup.path);
      // 不做弹窗打断启动流程，但必须留下痕迹便于排查
      stderr.writeln('[LocalStore] $fileName 已损坏（$reason），'
          '原文件备份为 ${backup.path}');
    } catch (_) {
      // 备份失败也不能让 App 起不来
    }
  }

  /// 原子写入整个文档。
  Future<void> write(Map<String, dynamic> data) async {
    _cache = data;
    final f = await _file();
    final tmp = File('${f.path}.tmp');

    await tmp.writeAsString(
      const JsonEncoder.withIndent('  ').convert(data),
      flush: true,
    );
    // rename 在同一文件系统内是原子操作：要么是旧内容，要么是新内容，
    // 不会出现「写了一半」的中间态。
    await tmp.rename(f.path);
  }

  /// 清空内存缓存。测试里切换目录时需要。
  void invalidate() => _cache = null;
}

/// 以 id 为键的集合存储，避免每个仓库都重写一遍增删改查。
mixin IdKeyedStore {
  LocalStore get store;

  /// 集合所在的字段名，如 'users' / 'athletes'
  String get collectionKey;

  Future<List<Map<String, dynamic>>> loadAll() async {
    final doc = await store.read();
    final raw = doc[collectionKey];
    if (raw is! List) return [];
    return raw.whereType<Map<String, dynamic>>().toList();
  }

  Future<void> saveAll(List<Map<String, dynamic>> items) async {
    final doc = await store.read();
    doc[collectionKey] = items;
    await store.write(doc);
  }

  Future<void> upsert(Map<String, dynamic> item, String idField) async {
    final items = await loadAll();
    final idx = items.indexWhere((e) => e[idField] == item[idField]);
    if (idx >= 0) {
      items[idx] = item;
    } else {
      items.add(item);
    }
    await saveAll(items);
  }

  Future<void> deleteById(String id, String idField) async {
    final items = await loadAll();
    items.removeWhere((e) => e[idField] == id);
    await saveAll(items);
  }
}
