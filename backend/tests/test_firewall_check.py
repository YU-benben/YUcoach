"""
防火墙自检的三态行为测试。

## 这一段锁定一个真实误报（2026-10-11）

读取防火墙规则的 `netsh advfirewall firewall show rule` **需要管理员权限**。
服务以普通用户启动时，它返回：

    returncode = 1
    stdout     = "Access is denied.\n\n\n"

旧实现把这段输出当"规则列表"解析，当然一条也解析不出来，
于是报「防火墙没有放行 TCP 8770」—— **而规则好好地在那儿**。

代价很大：用户被引去跑一条 `New-NetFirewallRule`，
而真正的原因是**手机热点的 AP 隔离**。误报把排查方向带偏了。

所以现在用**三态返回值**：

    "allowed"  —— 确认有规则放行
    "blocked"  —— 确认没有规则放行（此时才该提示用户去修）
    "unknown"  —— 查不了（权限不足等），**不下结论**

这就是 P10「宁可不说，不可说错」在启动自检上的应用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import app as server_app  # noqa: E402


#: 一条真正放行 8770 的规则，字段格式照抄 netsh 的真实输出
_RULE_OK = """Rule Name:                            YUcoach (TCP 8770)
----------------------------------------------------------------------
Enabled:                              Yes
Direction:                            In
Profiles:                             Domain,Private,Public
Grouping:
LocalIP:                              Any
RemoteIP:                             Any
Protocol:                             TCP
LocalPort:                            8770
RemotePort:                           Any
Edge traversal:                       No
Action:                               Allow
"""

#: 同样格式，但放行的是别的端口 —— 能解析出规则，只是不匹配
_RULE_OTHER_PORT = _RULE_OK.replace("8770", "9999")

#: 权限不足时 netsh 的真实输出
_ACCESS_DENIED = "Access is denied.\n\n\n"


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture()
def mock_netsh(monkeypatch):
    """替换掉 subprocess.run，返回构造好的 netsh 输出。"""
    def _apply(stdout: str, returncode: int = 0):
        monkeypatch.setattr(
            server_app.subprocess, "run",
            lambda *a, **k: _FakeProc(stdout, returncode),
        )
    return _apply


# ---------------------------------------------------------------------------
# check_firewall 的三态
# ---------------------------------------------------------------------------

def test_rule_allowing_port_is_allowed(mock_netsh):
    mock_netsh(_RULE_OK)
    assert server_app.check_firewall(8770) == "allowed"


def test_rule_for_other_port_is_blocked(mock_netsh):
    """解析到规则、但没有放行本端口 —— 这个结论可信。"""
    mock_netsh(_RULE_OTHER_PORT)
    assert server_app.check_firewall(8770) == "blocked"


def test_access_denied_is_unknown_not_blocked(mock_netsh):
    """
    权限不足 -> unknown，**绝不能报 blocked**。

    这是本次修复的核心。旧实现会把 "Access is denied." 解析成
    「没有规则」，于是误报防火墙没放行。
    """
    mock_netsh(_ACCESS_DENIED, returncode=1)
    assert server_app.check_firewall(8770) == "unknown"


def test_nonzero_returncode_is_unknown(mock_netsh):
    """非零返回码 -> 输出不可信 -> unknown。"""
    mock_netsh(_RULE_OK, returncode=1)
    assert server_app.check_firewall(8770) == "unknown"


def test_empty_output_is_unknown(mock_netsh):
    """一条规则都没解析出来 -> 格式变了或被截断 -> unknown。"""
    mock_netsh("")
    assert server_app.check_firewall(8770) == "unknown"


def test_exception_is_unknown(mock_netsh, monkeypatch):
    """subprocess 抛异常时也不该让启动失败。"""
    def boom(*a, **k):
        raise OSError("netsh 不见了")
    monkeypatch.setattr(server_app.subprocess, "run", boom)
    assert server_app.check_firewall(8770) == "unknown"


# ---------------------------------------------------------------------------
# firewall_hint 只在确认被拦时才给建议
# ---------------------------------------------------------------------------

def test_hint_empty_when_allowed(mock_netsh):
    mock_netsh(_RULE_OK)
    assert server_app.firewall_hint(8770) == []


def test_hint_empty_when_unknown(mock_netsh):
    """
    unknown 时给修复提示，等于又犯了同一个错：把用户引向错误方向。
    """
    mock_netsh(_ACCESS_DENIED, returncode=1)
    assert server_app.firewall_hint(8770) == []


def test_hint_present_when_blocked(mock_netsh):
    mock_netsh(_RULE_OTHER_PORT)
    hint = server_app.firewall_hint(8770)
    assert hint, "确认被拦时必须给出修复提示"
    joined = " ".join(hint)
    assert "New-NetFirewallRule" in joined
    assert "8770" in joined


# ---------------------------------------------------------------------------
# _allows_port 的字段校验
# ---------------------------------------------------------------------------

def test_allows_port_requires_every_field():
    """端口匹配还不够 —— 启用/方向/动作/协议全都要对。"""
    ok = {"Enabled": "Yes", "Direction": "In", "Action": "Allow",
          "Protocol": "TCP", "LocalPort": "8770"}
    assert server_app._allows_port(ok, 8770) is True

    for field, bad in (("Enabled", "No"), ("Direction", "Out"),
                       ("Action", "Block"), ("Protocol", "UDP")):
        assert server_app._allows_port({**ok, field: bad}, 8770) is False, field

    # 端口不匹配
    assert server_app._allows_port({**ok, "LocalPort": "9999"}, 8770) is False


def test_allows_port_accepts_protocol_any():
    """Protocol=Any 的规则同样放行 TCP。"""
    rule = {"Enabled": "Yes", "Direction": "In", "Action": "Allow",
            "Protocol": "Any", "LocalPort": "8770"}
    assert server_app._allows_port(rule, 8770) is True
