import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;

import '../models/models.dart';

/// 分析数据来源的抽象接口。
///
/// 界面只依赖这个接口，不认具体实现。
/// 这样从「假数据」切到「真后端」时，业务代码一行都不用改 —— 只换注入的实现。
///
/// 对应 docs/11-Fixture规范.md 的可切换数据源设计。
abstract class AnalysisRepository {
  /// 取一份完整分析结果（报告页需要的全部内容）
  Future<AnalysisResult> getAnalysis(String analysisId);
}

/// 开发用实现：从打包进 App 的 JSON 文件读假数据。
///
/// 假数据不是随手编的，而是**逐字段通过契约校验**的（见 scripts/check_contracts.py）。
/// 这样它就是「符合契约的真实结构」，接后端时行为一致。
class FixtureDataSource implements AnalysisRepository {
  const FixtureDataSource();

  /// 内置的三份 fixture，覆盖三种数据状态。
  ///
  /// 这三种状态都必须能在界面上表达出来，缺一不可：
  ///   normal         —— 指标正常，有结论
  ///   lowConfidence  —— 指标能算但不可用于判断（帧率不足、跟踪过快）
  ///   empty          —— 全部测不出来（教练第一次用普通视频拍就是这个结果）
  ///
  /// empty 最容易在开发时被漏掉，但它是真实场景中最常见的一种。
  ///
  /// 路径说明：这些文件是 samples/fixtures/ 的同步副本，由门禁自动同步
  /// （scripts/check_contracts.py --sync-mobile）。不要手工改这里的内容 ——
  /// 改 samples/fixtures/ 下的源文件，然后跑一次 check_all.py。
  static const Map<String, String> _assets = {
    'normal': 'assets/fixtures/analysis_normal.json',
    'lowConfidence': 'assets/fixtures/analysis_low_confidence.json',
    'empty': 'assets/fixtures/analysis_empty.json',
  };

  static List<String> get availableScenarios => _assets.keys.toList();

  @override
  Future<AnalysisResult> getAnalysis(String analysisId) async {
    final asset = _assets[analysisId];
    if (asset == null) {
      throw ArgumentError(
        '未知的 fixture 场景「$analysisId」，可选：${_assets.keys.join(", ")}',
      );
    }
    return loadScenario(analysisId);
  }

  /// 按场景名直接加载。开发期用它切换三种数据状态。
  static Future<AnalysisResult> loadScenario(String scenario) async {
    final raw = await rootBundle.loadString(_assets[scenario]!);
    final json = jsonDecode(raw) as Map<String, dynamic>;
    return AnalysisResult.fromJson(_stripMeta(json));
  }

  /// 剥掉 fixture 顶层的溯源字段（_comment / _covers 等）。
  ///
  /// 契约用了 additionalProperties: false 来抓拼写错误，而这些元数据字段
  /// 不属于契约；不剥掉会被判为「出现未定义字段」。
  /// 校验脚本里也有同样的处理，两处必须保持一致。
  static Map<String, dynamic> _stripMeta(Map<String, dynamic> json) {
    return Map.fromEntries(
      json.entries.where((e) => !e.key.startsWith('_')),
    );
  }
}
