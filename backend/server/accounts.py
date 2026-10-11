"""
账号体系：会员等级、额度、兑换码、管理员。

## 为什么这些放在服务端而不是 App 里

App 是**客户端**——任何写进 APK 的东西，反编译就能看到。

    如果把"我是高级会员"写在 App 里
        ↓
    改一个布尔值就白嫖了
    如果把管理员密码写在 App 里
        ↓
    密码等于公开

所以：**会员状态与额度一律由服务端裁定**，App 只显示服务端说的结果。

## 密码处理

管理员密码**不存明文**，只存 `salt$sha256(salt + password)`。

为什么：
  · 服务端代码可能被分享、备份、或传到别处
  · 明文密码一旦泄漏，而很多人习惯复用密码 —— 影响会扩散到别的系统
  · 哈希之后，即使数据泄漏也拿不到原始密码

⚠️ 但要说清楚**这个方案的边界**：
    这是**单机、无数据库**的简化实现，账号存在 JSON 文件里。
    它防的是"密码被直接读到"，**不防**"能读写该文件的人改会员等级"。
    真要上线，需要完整的用户表 + 数据库 + 会话令牌。

## 额度规则

    免费用户  10 次  一次性，用完为止
    普通会员  100 次/月
    高级会员  500 次/月

为什么按月而不是永久：
    视频分析要跑 GPU，是**持续成本**。永久额度会让成本无上限累积。

## 训练计划不在额度体系里

训练计划（日历备注）是**所有人免费**的本地功能，和服务端额度无关。

    它不消耗额度，也不因为等级低而被限制。

所以它**不作为任何等级的权益**：
  · 服务端 tier_has_plan() 恒返回 False
  · App 里它在「我的 → 训练」独立成栏，标着「免费」
  · 会员页面的套餐表里不出现它

这三处必须一致。曾经把它写成高级会员权益，结果免费用户
看到"不含训练计划功能"就以为自己用不了 —— 而其实一直能用。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    sys_stdout = __import__("sys").stdout
    sys_stdout.reconfigure(errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 会员等级
# ---------------------------------------------------------------------------

#: 等级 -> (中文名, 每月额度, 是否含训练计划)
#:
#: 额度用 -1 表示不限。管理员用它。
#:
#: ⚠️ 关于"含训练计划"这一栏：
#:    **训练计划对所有用户免费**，不是会员权益。
#:    所以三个等级的这一栏都是 False —— 这里的含义是
#:    "**这个等级额外解锁了**训练计划"，答案是都没有，
#:    因为它本来就不需要解锁。
#:
#:    这个字段保留是为了接口稳定（App 在读 has_plan），
#:    但**不要**用它做权限判断 —— 判了就会把免费功能锁住。
#:    真要判权限，用 tier_quota() 判额度。
TIERS: dict[str, tuple[str, int, bool]] = {
    "free": ("普通用户", 10, False),
    "basic": ("普通会员", 100, False),
    "premium": ("高级会员", 500, False),
    "admin": ("高级会员", -1, False),
    # ↑ 管理员**对外显示为高级会员** —— 这是刻意的：
    #   让用户看到"管理员"这个身份没有意义，反而会引出
    #   "为什么他能免费用"这类问题。权限在服务端判定，界面照样显示高级会员。
}

#: 界面显示用的等级顺序（用于"升级"提示）
TIER_ORDER = ["free", "basic", "premium"]


def tier_label(tier: str) -> str:
    """等级的中文名。未知等级按最低处理 —— 不认识的等级不该给更多权限。"""
    return TIERS.get(tier, TIERS["free"])[0]


def tier_quota(tier: str) -> int:
    """每月额度。-1 表示不限。"""
    return TIERS.get(tier, TIERS["free"])[1]


def tier_has_plan(tier: str) -> bool:
    """
    该等级是否**额外**解锁了训练计划。

    ⚠️ 现在恒为 False，而且**这是正确的** —— 训练计划对所有用户免费，
    没有任何等级需要"解锁"它。

    保留这个函数是为了接口稳定（客户端在读 has_plan 字段）。
    **不要拿它做权限判断** —— 那会把一个免费功能锁住。
    要判权限请用 tier_quota() 判分析额度。
    """
    return TIERS.get(tier, TIERS["free"])[2]


# ---------------------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: str | None = None) -> str:
    """
    返回 `salt$hash`。salt 为空时随机生成。

    用 sha256 而不是 bcrypt/argon2 的原因：这两个都需要额外依赖，
    而本项目服务端刻意保持零依赖（见 backend/server/app.py 的说明）。
    单机、无网络的账号体系下，加盐 sha256 已经挡住了"直接读密码"。
    """
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码。用 compare_digest 防时序攻击。"""
    if not stored or "$" not in stored:
        return False
    salt, _, _ = stored.partition("$")
    return secrets.compare_digest(stored, hash_password(password, salt))


# ---------------------------------------------------------------------------
# 账号数据
# ---------------------------------------------------------------------------

@dataclass
class Account:
    """一个账号。"""

    username: str
    password_hash: str
    tier: str = "free"
    display_name: str = ""
    role: str = ""              # 身份：家长 / 教练员 / 运动员
    avatar: str = ""            # 头像标识（App 侧存图片，这里只存引用）
    is_admin: bool = False

    #: 本月已用次数
    used_this_month: int = 0

    #: 当前额度周期（YYYY-MM）。跨月自动重置 ——
    #: 存的是"上一次计费是哪个周期"，而不是靠定时任务去清零。
    #: 定时任务在单机服务里不可靠（服务没开就不跑）。
    period: str = ""

    created_at: float = field(default_factory=time.time)

    def ensure_period(self, now: str) -> bool:
        """跨月则重置用量。返回是否发生了重置。"""
        if self.period != now:
            self.period = now
            self.used_this_month = 0
            return True
        return False

    def quota(self) -> int:
        return tier_quota(self.tier)

    def remaining(self) -> int:
        """剩余次数。-1 表示不限。"""
        q = self.quota()
        if q < 0:
            return -1
        return max(0, q - self.used_this_month)

    def can_analyze(self) -> bool:
        return self.quota() < 0 or self.used_this_month < self.quota()

    def public(self) -> dict[str, Any]:
        """给 App 看的字段。**绝不包含 password_hash**。"""
        return {
            "username": self.username,
            "display_name": self.display_name or self.username,
            "tier": self.tier,
            "tier_label": tier_label(self.tier),
            "role": self.role,
            "avatar": self.avatar,
            "quota": self.quota(),
            "used": self.used_this_month,
            "remaining": self.remaining(),
            "period": self.period,
            "has_plan": tier_has_plan(self.tier),
            "is_admin": self.is_admin,
        }


@dataclass
class RedeemCode:
    """一张兑换码。"""

    code: str
    tier: str
    used: bool = False
    used_by: str = ""
    used_at: float | None = None
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "tier": self.tier,
            "tier_label": tier_label(self.tier),
            "used": self.used,
        }


# ---------------------------------------------------------------------------
# 账号库
# ---------------------------------------------------------------------------

class AccountStore:
    """
    账号存储。JSON 文件 + 内存缓存 + 锁。

    为什么不用数据库：见模块开头。当前规模（单机、少量账号）
    JSON 完全够用，且不需要任何依赖。
    并发用一把锁保护 —— 服务端是 ThreadingHTTPServer，
    多个请求线程会同时读写。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._accounts: dict[str, Account] = {}
        self._codes: dict[str, RedeemCode] = {}
        self._loaded = False

    # ---- 读写 ----

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self.path.exists():
                try:
                    doc = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    # 文件损坏时**不静默丢弃** —— 改名留证据，
                    # 然后从空开始，保证服务还能起来。
                    bad = self.path.with_suffix(".corrupt")
                    try:
                        self.path.rename(bad)
                    except OSError:
                        pass
                    doc = {}
            else:
                doc = {}

            for raw in doc.get("accounts") or []:
                try:
                    a = Account(**raw)
                    self._accounts[a.username] = a
                except TypeError:
                    continue
            for raw in doc.get("codes") or []:
                try:
                    c = RedeemCode(**raw)
                    self._codes[c.code] = c
                except TypeError:
                    continue
            self._loaded = True

    def _save(self) -> None:
        """原子写：先写临时文件再 rename，防止写一半损坏。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "accounts": [asdict(a) for a in self._accounts.values()],
            "codes": [asdict(c) for c in self._codes.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---- 账号 ----

    def get(self, username: str) -> Account | None:
        self._load()
        with self._lock:
            return self._accounts.get(username)

    def upsert(self, account: Account) -> None:
        self._load()
        with self._lock:
            self._accounts[account.username] = account
            self._save()

    def all(self) -> list[Account]:
        self._load()
        with self._lock:
            return list(self._accounts.values())

    def consume_quota(self, username: str, now: str) -> tuple[bool, str]:
        """
        扣一次额度。返回 (是否成功, 说明)。

        跨月自动重置 —— 不依赖定时任务。
        """
        self._load()
        with self._lock:
            a = self._accounts.get(username)
            if a is None:
                return False, "账号不存在"
            if a.ensure_period(now):
                self._save()
            if not a.can_analyze():
                return False, (
                    f"{tier_label(a.tier)}的额度已用完"
                    f"（{a.used_this_month}/{a.quota()} 次，{a.period}）"
                )
            a.used_this_month += 1
            self._save()
            return True, "已扣一次额度"

    # ---- 兑换码 ----

    def add_codes(self, tier: str, count: int) -> list[str]:
        """生成一批兑换码。返回码列表。"""
        self._load()
        if tier not in TIERS or tier in ("free", "admin"):
            raise ValueError(f"不能为 {tier} 生成兑换码")
        out: list[str] = []
        with self._lock:
            for _ in range(count):
                while True:
                    # 格式 YU-XXXX-XXXX，去掉易混字符（0/O、1/I/L）
                    alphabet = "ACDEFGHJKMNPQRTUVWXY34679"
                    body = "".join(secrets.choice(alphabet)
                                   for _ in range(8))
                    code = f"YU-{body[:4]}-{body[4:]}"
                    if code not in self._codes:
                        break
                self._codes[code] = RedeemCode(code=code, tier=tier)
                out.append(code)
            self._save()
        return out

    def list_codes(self) -> list[RedeemCode]:
        self._load()
        with self._lock:
            return sorted(self._codes.values(), key=lambda c: c.created_at)

    def redeem(self, code: str, username: str) -> tuple[bool, str]:
        """使用兑换码。返回 (是否成功, 说明)。"""
        self._load()
        code = (code or "").strip().upper()
        with self._lock:
            c = self._codes.get(code)
            if c is None:
                return False, "兑换码不存在，请检查是否输错"
            if c.used:
                return False, "这张兑换码已经被使用过了"

            a = self._accounts.get(username)
            if a is None:
                return False, "账号不存在"

            c.used = True
            c.used_by = username
            c.used_at = time.time()
            a.tier = c.tier
            # 升级后重置本月用量 —— 否则用户刚升完级就发现额度还是满的
            a.used_this_month = 0
            self._save()
            return True, f"已升级为{tier_label(c.tier)}"


# ---------------------------------------------------------------------------
# 兑换码的演示数据
# ---------------------------------------------------------------------------

def seed_demo_codes(store: AccountStore, n_basic: int = 4,
                    n_premium: int = 4) -> list[str]:
    """
    首次启动时生成几张演示兑换码。

    ⚠️ 这是**给你自己测试和演示用的**，不是给用户发卡。
       正式发放要用管理员接口按需生成。
    """
    existing = store.list_codes()
    if existing:
        return []
    codes = store.add_codes("basic", n_basic) + store.add_codes("premium",
                                                               n_premium)
    return codes
