"""标准值库加载与校验的测试。

这一组测试保护的是**全项目唯一无法通过其他手段发现的错误类型**：
标准值编造。

为什么它对标准值特别重要：
    指标算错可以对比真值，契约写错有 Schema 校验，
    规则写错有用例验证 —— 而标准值编造没有任何自动检测手段。
    这里的三道校验就是补上这个缺口。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.standards.loader import (  # noqa: E402
    load_or_empty,
    load_standards,
)


# ---------------------------------------------------------------------------
# 真实的标准值库
# ---------------------------------------------------------------------------

def test_real_library_loads_without_problems():
    """
    仓库里实际的标准值文件必须**全部通过校验**。

    这条测试的意义：任何人往 data/standards/ 里加条目时写错了字段，
    这里立刻失败。它把"不许编造"从人的自觉变成了机械检查。
    """
    lib = load_standards()
    assert not lib.problems, (
        "标准值库有不合规条目：\n"
        + "\n".join(f"  {p}" for p in lib.problems)
    )


def test_real_library_has_version():
    """标准值库必须有版本号 —— 否则无法回答'为什么这次结论和上次不同'。"""
    lib = load_standards()
    assert lib.version, "标准值库缺少 version"


def test_every_loaded_entry_has_a_locator():
    """
    ⚠️ 铁律的核心：每条标准值都必须能指向具体页码或图表号。

    没有 locator 就无法查证，等同于凭印象编造。
    """
    lib = load_standards()
    for e in lib.entries:
        assert e.source_locator, (
            f"{e.metric_id} 缺少 source.locator —— 违反铁律"
        )
        assert len(e.source_locator) > 3, (
            f"{e.metric_id} 的 locator 太短，不像是真实的页码/图表号"
        )


def test_every_loaded_entry_has_measurement_note():
    """
    测量口径说明必填。

    同一个指标名在不同研究里的定义可能不同（例如"躯干前倾"
    有相对竖直与相对水平两种口径，数值互补）。
    口径不符的标准值比没有更危险。
    """
    lib = load_standards()
    for e in lib.entries:
        assert e.measurement_note, f"{e.metric_id} 缺少 measurement_note"
        assert e.extraction_note, f"{e.metric_id} 缺少 extraction_note"


def test_entries_have_readable_source_for_coaches():
    """
    每条标准值都要有**给教练看**的出处。

    没有的话报告里就无法回答"这个标准哪来的"，
    而教练一旦发现一次说不清来源的数字，就不再相信所有数字。
    """
    lib = load_standards()
    for e in lib.entries:
        shown = e.display_source()
        assert shown, f"{e.metric_id} 没有可展示的出处"
        # 外文作者名不该出现在给用户看的出处里 ——
        # 它们对教练没有信息量，且特殊字符容易触发编码问题
        assert "Š" not in shown


# ---------------------------------------------------------------------------
# 校验逻辑本身
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_standards(tmp_path):
    """在临时目录里造一个标准值文件。"""
    def _write(entries, pending=None, version="test"):
        doc = {"version": version, "verified": entries}
        if pending:
            doc["pending"] = pending
        (tmp_path / "t.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        return tmp_path
    return _write


def _good_entry(**over) -> dict:
    e = {
        "metric_id": "step_frequency",
        "view": "side",
        "phase": "whole_run",
        "population": {"gender": "male", "level": "elite", "event": "100m"},
        "low": 250.0, "high": 290.0, "mean": 270.0, "sd": 10.0,
        "source": {
            "authors": "A", "year": 2020, "title": "T",
            "journal": "J", "doi": "10.1/x", "locator": "Table 1",
        },
        "measurement_note": "口径说明",
        "extraction_note": "提取说明",
        "verified_by": "x", "verified_date": "2026-01-01",
        "std_version": "2026Q1",
        # 测量窗口。**必填** —— 缺了就拒绝加载，因为无法判断
        # 这条数值覆盖的是"一段时期的均值"还是"某一个瞬间"。
        "window": "whole_run",
    }
    e.update(over)
    return e


def test_missing_locator_is_rejected(tmp_standards):
    """缺少 locator 必须被拒绝 —— 这是铁律的机械实现。"""
    d = tmp_standards([_good_entry(source={
        "authors": "A", "year": 2020, "title": "T", "journal": "J",
        "doi": "10.1/x", "locator": "",
    })])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("locator" in p.reason for p in lib.problems)


def test_unknown_metric_id_is_rejected(tmp_standards):
    """拼错或已删除的指标 ID 必须被拒绝，防止残留条目被误用。"""
    d = tmp_standards([_good_entry(metric_id="knee_angle_typo")])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("不在指标清单" in p.reason for p in lib.problems)


def test_view_mismatch_is_rejected(tmp_standards):
    """
    ⚠️ 视角绑定校验。

    trunk_lean 是矢状面指标，只能配 side 视角的标准值。
    用正面视角的数据去判侧面测量，等于拿苹果比橘子。
    """
    d = tmp_standards([_good_entry(metric_id="trunk_lean", view="front")])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("视角" in p.reason for p in lib.problems)


def test_invalid_phase_is_rejected(tmp_standards):
    d = tmp_standards([_good_entry(phase="warmup")])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("phase" in p.reason for p in lib.problems)


def test_missing_measurement_note_is_rejected(tmp_standards):
    d = tmp_standards([_good_entry(measurement_note="")])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("measurement_note" in p.reason for p in lib.problems)


# ---------------------------------------------------------------------------
# 测量窗口 —— 第三次拒绝数据时补上的防线
# ---------------------------------------------------------------------------

def test_missing_window_is_rejected(tmp_standards):
    """
    ⚠️ 缺 window 字段必须被拒绝。

    背景（真实发生过）：
        Walker et al. 2021 报告了世界级短跑选手起跑第一次着地瞬间的
        躯干角（39±3° 相对水平）。数据质量极高 —— 世界锦标赛决赛选手、
        150 Hz 高速摄影、顶刊发表。

        但**没有采用**，因为论文测的是"第 1 步那一瞬间"，
        而我们的 metric_trunk_lean 取的是"阶段所有帧的均值"。

        加速段躯干单调抬起（51° → 28°），所以论文的区间是**峰值区间**。
        照此入库会让每一个正常运动员都被报「躯干抬起过早」。

    这类错误最难发现：来源权威、数值合理、口径也说得清 ——
    错的只是"测的是瞬间，我们比的是均值"。

    所以要求每条标准值显式声明 window，否则拒绝加载。
    """
    d = tmp_standards([_good_entry(window="")])
    lib = load_standards(d)
    assert len(lib.entries) == 0, "缺 window 的条目不该被加载"
    assert any("window" in p.reason for p in lib.problems)


def test_invalid_window_is_rejected(tmp_standards):
    """window 取值必须在合法集合内。"""
    d = tmp_standards([_good_entry(window="sometimes")])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("window" in p.reason for p in lib.problems)


def test_unspecified_window_is_accepted(tmp_standards):
    """
    原文确实没说明窗口时，允许填 unspecified —— 但也仅止于此。

    为什么不直接拒绝：有些老文献确实不写测量窗口。
    宁可让它入库（并保留 unspecified 的痕迹），
    也不要逼着人凭猜测填一个看起来具体、实际是编的值。
    """
    d = tmp_standards([_good_entry(window="unspecified")])
    lib = load_standards(d)
    assert len(lib.entries) == 1, f"应通过：{lib.problems}"
    assert lib.entries[0].window == "unspecified"


def test_all_valid_window_values_are_accepted(tmp_standards):
    """五个合法取值都要能用 —— 否则限制就成了障碍。"""
    for w in ("whole_phase", "single_event", "event_mean",
              "whole_run", "unspecified"):
        d = tmp_standards([_good_entry(window=w)])
        lib = load_standards(d)
        assert len(lib.entries) == 1, f"window={w} 应通过：{lib.problems}"
        assert lib.entries[0].window == w


def test_real_library_declares_window_for_every_entry():
    """
    仓库里真实的标准值必须**每条都声明了测量窗口**。

    这条测试的价值在于：window 是后加的字段，存量条目容易漏补。
    漏了会被 loader 拦下并让门禁失败 —— 这条测试把那个失败提前到这里。
    """
    lib = load_standards()
    for e in lib.entries:
        assert e.window, (
            f"{e.metric_id} 未声明测量窗口。"
            f"无法判断它覆盖的是阶段均值还是单个瞬间 —— "
            f"这正是第三次拒绝数据的原因。"
        )
        assert e.window in (
            "whole_phase", "single_event", "event_mean",
            "whole_run", "unspecified",
        ), f"{e.metric_id} 的 window 取值非法：{e.window}"


def test_event_metrics_use_event_window():
    """
    事件类指标的窗口应当是 single_event 或 event_mean，而不是 whole_phase。

    这是一条**语义合理性**检查：标着"着地时膝角"的标准值，
    如果声明成"整个阶段所有帧的均值"，那它的含义就变了。
    """
    from backend.analysis.metrics_base import METRIC_SPECS

    lib = load_standards()
    for e in lib.entries:
        spec = METRIC_SPECS.get(e.metric_id)
        if spec is None or not spec.is_event_metric:
            continue
        assert e.window in ("single_event", "event_mean", "unspecified"), (
            f"{e.metric_id} 是事件类指标（is_event_metric=True），"
            f"但 window 声明为 {e.window}。"
            f"事件类指标的取值是「某一帧」，不该声明成阶段均值。"
        )


def test_all_null_values_is_rejected(tmp_standards):
    """没有任何数值的条目没有意义，应当拒绝。"""
    d = tmp_standards([_good_entry(low=None, high=None, mean=None)])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("没有可用的标准值" in p.reason for p in lib.problems)


def test_inverted_range_is_rejected(tmp_standards):
    """low > high 显然是填错了。"""
    d = tmp_standards([_good_entry(low=300.0, high=200.0)])
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert any("大于" in p.reason for p in lib.problems)


def test_good_entry_is_accepted(tmp_standards):
    """完全合规的条目必须被接受 —— 否则校验就成了纯粹的阻碍。"""
    d = tmp_standards([_good_entry()])
    lib = load_standards(d)
    assert len(lib.entries) == 1
    assert not lib.problems
    assert lib.entries[0].source_locator == "Table 1"


def test_pending_entries_are_recorded_not_loaded(tmp_standards):
    """
    待补条目只被记录，**不会变成可用的标准值**。

    这是"查不到就留空"的机械实现：
    记录"需要什么数据"是有价值的，但绝不能因此就让
    一个没有数字的条目参与判定。
    """
    d = tmp_standards(
        entries=[],
        pending=[{"metric_id": "trunk_lean", "phase": "acceleration",
                  "needed": "区间", "why_vacant": "没找到"}],
    )
    lib = load_standards(d)
    assert len(lib.entries) == 0
    assert len(lib.pending) == 1


# ---------------------------------------------------------------------------
# 查找
# ---------------------------------------------------------------------------

def test_lookup_requires_matching_view(tmp_standards):
    """视角不匹配时必须查不到 —— 不能退回别的视角的值。"""
    d = tmp_standards([_good_entry()])
    lib = load_standards(d)

    assert lib.lookup("step_frequency", "side", "whole_run") is not None
    assert lib.lookup("step_frequency", "front", "whole_run") is None
    assert lib.lookup("step_frequency", "back", "whole_run") is None


def test_lookup_falls_back_to_whole_run(tmp_standards):
    """
    phase 精确匹配失败时，可以退回 whole_run（全程平均值）。

    但**不是**退回别的具体阶段 —— 加速段和途中跑的标准值
    含义相反，互相替代会造成系统性误报。
    """
    d = tmp_standards([_good_entry(phase="whole_run")])
    lib = load_standards(d)

    # 任意具体阶段都能用全程值
    assert lib.lookup("step_frequency", "side", "max_velocity") is not None
    assert lib.lookup("step_frequency", "side", "acceleration") is not None


def test_lookup_does_not_cross_phases(tmp_standards):
    """
    ⚠️ 关键测试：加速段的标准值**不能**被途中跑使用。

    docs/04 §5.1 明确警告：拿途中跑的标准值去判加速段，
    会对所有正常运动员报出"躯干前倾过大"，而且数字看起来很合理。

    注意这里的取值必须落在 trunk_lean 的生理可信范围内
    （-20–75°），否则会被可信范围检查拦掉，
    测的就不是"相位隔离"而是"范围检查"了。
    """
    d = tmp_standards([_good_entry(
        metric_id="trunk_lean", phase="acceleration",
        low=45.0, high=60.0, mean=52.0, sd=4.0)])
    lib = load_standards(d)
    assert lib.entries, f"测试数据本身应通过校验：{lib.problems}"

    assert lib.lookup("trunk_lean", "side", "acceleration") is not None
    assert lib.lookup("trunk_lean", "side", "max_velocity") is None, (
        "加速段的标准值不该被途中跑使用 —— 两者含义相反"
    )


def test_implausible_value_is_rejected(tmp_standards):
    """
    ⚠️ 生理可信范围检查。

    实际踩过的坑：从 IAAF 报告提取 trunk_lean 标准值时，
    PDF 表格的列标题在提取中丢失，取到的行换算出 61–68° 的前倾角。

    这个值在「0–180° 的合法角度」里毫无问题 ——
    只有对照「人跑起来躯干能摆成什么样」才能发现它错了。

    所以这条测试用一个**格式完全合法但生理上不可能**的值，
    验证它会被拒绝。没有这道检查，这类错误会一路进到报告里。
    """
    # 250° 的躯干前倾角：格式合法（正数、在 0-360 内），
    # 但人做不到 —— 躯干相对竖直最多也就 75° 左右
    d = tmp_standards([_good_entry(
        metric_id="trunk_lean", low=250.0, high=300.0, mean=270.0)])
    lib = load_standards(d)

    assert len(lib.entries) == 0, "生理上不可能的值必须被拒绝"
    assert any("不可信" in p.reason for p in lib.problems)
    # 错误信息要能看出「错在哪」，而不只是「非法」
    assert any("取错了行" in p.reason or "生理" in p.reason
               for p in lib.problems)


def test_implausible_mean_is_rejected(tmp_standards):
    """mean 也要检查 —— 区间合法但均值离谱同样是错的。"""
    d = tmp_standards([_good_entry(
        metric_id="knee_angle_touchdown",
        low=140.0, high=160.0, mean=400.0)])
    lib = load_standards(d)
    assert len(lib.entries) == 0


def test_unconverted_time_value_is_rejected(tmp_standards):
    """
    ⚠️ 未换算的秒值必须被拒绝。

    文献报告时间常用「秒」（如 0.101 s），本项目用「毫秒」（101 ms）。
    0.101 和 101 描述的是同一个事实 ——
    如果把 0.101 直接写进标准值库，规则引擎会拿它去和实测的
    101 ms 比，判出「触地时间比参考值低 100 倍」。

    这类错误无法通过"看数值是否合理"发现：
    0.101 是个完全正常的数字。只能在加载时按指标的可信范围核对。
    """
    d = tmp_standards([_good_entry(
        metric_id="ground_contact_time",
        low=0.088, high=0.116, mean=0.101, sd=0.008)])
    lib = load_standards(d)

    assert len(lib.entries) == 0, (
        "0.101 秒写成毫秒是错的，必须被拒绝而不是照单全收"
    )
    reasons = " ".join(p.reason for p in lib.problems)
    assert "未换算" in reasons or "不可信" in reasons, (
        f"错误信息要说清是单位问题，实得：{reasons}"
    )


def test_correct_millisecond_value_is_accepted(tmp_standards):
    """按毫秒写入的值必须能正常通过 —— 否则校验就成了纯粹的阻碍。"""
    d = tmp_standards([_good_entry(
        metric_id="ground_contact_time",
        low=85.0, high=118.0, mean=101.0, sd=8.0)])
    lib = load_standards(d)

    assert len(lib.entries) == 1, f"应通过校验：{lib.problems}"
    e = lib.entries[0]
    assert e.mean == pytest.approx(101.0, abs=0.5)
    assert e.low == pytest.approx(85.0, abs=0.5)


def test_double_conversion_is_caught(tmp_standards):
    """
    换算两次（85000 ms）也要能被拦下。

    这是"有人手工换算过、加载器又乘了一次"的情形。
    85000 在文件里看着只是个"大数"，不做范围检查发现不了。
    """
    d = tmp_standards([_good_entry(
        metric_id="ground_contact_time",
        low=85000.0, high=118000.0, mean=101000.0)])
    lib = load_standards(d)
    assert len(lib.entries) == 0, "换算两次的值必须被拒绝"


def test_lookup_respects_level(tmp_standards):
    """水平匹配优先：有对应水平就用对应水平的。"""
    d = tmp_standards([
        _good_entry(population={"gender": "male", "level": "elite",
                                "event": "100m"}),
        _good_entry(low=200.0, high=250.0, mean=225.0,
                    population={"gender": "male", "level": "college",
                                "event": "100m"}),
    ])
    lib = load_standards(d)

    elite = lib.lookup("step_frequency", "side", "whole_run", level="elite")
    assert elite is not None and elite.mean == 270.0

    college = lib.lookup("step_frequency", "side", "whole_run",
                         level="college")
    assert college is not None and college.mean == 225.0


def test_unknown_metric_lookup_returns_none(tmp_standards):
    """查不到的指标必须返回 None，由调用方决定不做判定 —— 不给默认值。"""
    d = tmp_standards([_good_entry()])
    lib = load_standards(d)
    assert lib.lookup("nonexistent_metric", "side", "acceleration") is None


# ---------------------------------------------------------------------------
# 健壮性
# ---------------------------------------------------------------------------

def test_broken_yaml_does_not_crash(tmp_path):
    """坏掉的 YAML 只记问题，不该让加载整体失败。"""
    (tmp_path / "bad.yaml").write_text("{{{{ not yaml", encoding="utf-8")
    lib = load_standards(tmp_path)
    assert lib.problems
    assert lib.entries == []


def test_missing_directory_returns_empty(tmp_path):
    """目录不存在时返回空库 —— 服务刚部署就是这个状态。"""
    lib = load_standards(tmp_path / "nope")
    assert lib.entries == []
    assert not lib.problems


def test_load_or_empty_never_raises(tmp_path, monkeypatch):
    """
    load_or_empty 在任何异常下都退回空库。

    运行时不能因为标准值文件的问题让分析整体失败 ——
    少几条标准值只表现为"不做偏离判断"，而分析本身仍然有价值。
    """
    # 指向一个不可读的路径（用一个文件当目录）
    f = tmp_path / "afile"
    f.write_text("x")
    lib = load_or_empty(f)
    assert lib.entries == []
