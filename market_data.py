"""日行情临时缓存（akshare）。

分析会话内拉取并落盘缓存；会话结束（分析完成）后整目录删除。
未安装 akshare 或拉取失败时返回空，算法侧按「特征缺失」降级。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

# 限速：两次远端请求最小间隔（秒）
_REQUEST_GAP_SEC = float(os.environ.get("MBTI_MKT_GAP", "0.35"))
_MAX_RETRIES = int(os.environ.get("MBTI_MKT_RETRIES", "3"))


def akshare_available() -> bool:
    try:
        import akshare  # noqa: F401

        return True
    except ImportError:
        return False


def _norm_code(code: str) -> str:
    c = (code or "").strip()
    if "." in c:
        c = c.split(".", 1)[0]
    # 去掉市场前缀 sh/sz/bj
    if len(c) > 6 and c[:2].lower() in ("sh", "sz", "bj"):
        c = c[2:]
    return c.zfill(6) if c.isdigit() else c


def _parse_ymd(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Bar:
    d: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    turnover: float = 0.0  # 换手率 %
    pct_chg: float = 0.0  # 涨跌幅 %


@dataclass
class MarketSession:
    """单次 MBTI 分析的行情会话：磁盘缓存 + 内存索引，close() 后清空。"""

    root: str = field(default="")
    _last_req: float = field(default=0.0, repr=False)
    _daily: dict[str, dict[date, Bar]] = field(default_factory=dict, repr=False)
    _index: dict[date, Bar] = field(default_factory=dict, repr=False)
    _spot_tags: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _sigma_cache: dict[str, dict[date, float]] = field(default_factory=dict, repr=False)
    _beta_cache: dict[str, dict[date, float]] = field(default_factory=dict, repr=False)
    _market_vol_p75: float | None = field(default=None, repr=False)
    _hot_codes: set[str] = field(default_factory=set, repr=False)
    _closed: bool = field(default=False, repr=False)
    fetch_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.root:
            self.root = tempfile.mkdtemp(prefix="mbti_mkt_")

    def __enter__(self) -> MarketSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._daily.clear()
        self._index.clear()
        self._spot_tags.clear()
        self._sigma_cache.clear()
        self._beta_cache.clear()
        root = self.root
        self.root = ""
        if root and os.path.isdir(root):
            shutil.rmtree(root, ignore_errors=True)

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = _REQUEST_GAP_SEC - (now - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.monotonic()

    def _cache_path(self, name: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
        return os.path.join(self.root, safe)

    def _load_json(self, path: str) -> Any | None:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _save_json(self, path: str, data: Any) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass

    def _bars_from_rows(self, rows: list[dict[str, Any]]) -> dict[date, Bar]:
        out: dict[date, Bar] = {}
        for r in rows:
            d = _parse_ymd(r.get("date") or r.get("日期"))
            if d is None:
                continue
            try:
                high = float(r.get("high") if r.get("high") is not None else r.get("最高"))
                low = float(r.get("low") if r.get("low") is not None else r.get("最低"))
                close = float(r.get("close") if r.get("close") is not None else r.get("收盘"))
                open_p = float(r.get("open") if r.get("open") is not None else r.get("开盘", close))
            except (TypeError, ValueError):
                continue
            vol = 0.0
            amt = 0.0
            turn = 0.0
            pct = 0.0
            try:
                vol = float(r.get("volume") or r.get("成交量") or 0)
            except (TypeError, ValueError):
                pass
            try:
                amt = float(r.get("amount") or r.get("成交额") or 0)
            except (TypeError, ValueError):
                pass
            try:
                turn = float(r.get("turnover") or r.get("换手率") or 0)
            except (TypeError, ValueError):
                pass
            try:
                pct = float(r.get("pct_chg") or r.get("涨跌幅") or 0)
            except (TypeError, ValueError):
                pass
            out[d] = Bar(
                d=d,
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=vol,
                amount=amt,
                turnover=turn,
                pct_chg=pct,
            )
        return out

    def _fetch_stock_hist(self, code: str, start: date, end: date) -> list[dict[str, Any]]:
        if not akshare_available():
            return []
        import akshare as ak

        symbol = _norm_code(code)
        start_s = start.strftime("%Y%m%d")
        end_s = end.strftime("%Y%m%d")
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                self._throttle()
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_s,
                    end_date=end_s,
                    adjust="qfq",
                )
                if df is None or getattr(df, "empty", True):
                    return []
                rows: list[dict[str, Any]] = []
                for _, row in df.iterrows():
                    rows.append(
                        {
                            "date": str(row.get("日期", "")),
                            "open": row.get("开盘"),
                            "high": row.get("最高"),
                            "low": row.get("最低"),
                            "close": row.get("收盘"),
                            "volume": row.get("成交量"),
                            "amount": row.get("成交额"),
                            "turnover": row.get("换手率"),
                            "pct_chg": row.get("涨跌幅"),
                        }
                    )
                return rows
            except Exception as e:  # noqa: BLE001 — 远端源不稳定，重试后记错
                last_err = e
                time.sleep(0.6 * (attempt + 1))
        self.fetch_errors.append(f"{symbol}: {last_err}")
        return []

    def _fetch_index_hist(self, start: date, end: date) -> list[dict[str, Any]]:
        if not akshare_available():
            return []
        import akshare as ak

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                self._throttle()
                df = ak.stock_zh_index_daily(symbol="sh000001")
                if df is None or getattr(df, "empty", True):
                    return []
                rows: list[dict[str, Any]] = []
                for _, row in df.iterrows():
                    d = _parse_ymd(row.get("date") or row.get("日期"))
                    if d is None or d < start or d > end:
                        continue
                    rows.append(
                        {
                            "date": d.isoformat(),
                            "open": row.get("open") or row.get("开盘"),
                            "high": row.get("high") or row.get("最高"),
                            "low": row.get("low") or row.get("最低"),
                            "close": row.get("close") or row.get("收盘"),
                            "volume": row.get("volume") or row.get("成交量") or 0,
                        }
                    )
                return rows
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.6 * (attempt + 1))
        self.fetch_errors.append(f"index: {last_err}")
        return []

    def ensure_daily(self, code: str, start: date, end: date) -> dict[date, Bar]:
        """确保个股日线已缓存；返回 date→Bar。"""
        if self._closed:
            return {}
        key = _norm_code(code)
        # 若已有且覆盖区间则直接返回；简单策略：同 code 合并扩展
        cached = self._daily.get(key)
        path = self._cache_path(f"daily_{key}_{start.isoformat()}_{end.isoformat()}.json")
        if cached is not None and cached:
            return cached
        disk = self._load_json(path)
        if isinstance(disk, list) and disk:
            bars = self._bars_from_rows(disk)
            self._daily[key] = bars
            return bars
        rows = self._fetch_stock_hist(key, start, end)
        if rows:
            self._save_json(path, rows)
        bars = self._bars_from_rows(rows)
        self._daily[key] = bars
        return bars

    def ensure_index(self, start: date, end: date) -> dict[date, Bar]:
        if self._closed:
            return {}
        if self._index:
            return self._index
        path = self._cache_path(f"index_sh000001_{start.isoformat()}_{end.isoformat()}.json")
        disk = self._load_json(path)
        if isinstance(disk, list) and disk:
            self._index = self._bars_from_rows(disk)
            return self._index
        # 指数接口常返回全历史，多拉一点再裁剪
        rows = self._fetch_index_hist(start - timedelta(days=5), end + timedelta(days=5))
        if rows:
            self._save_json(path, rows)
        self._index = self._bars_from_rows(rows)
        return self._index

    def prefetch(
        self,
        codes: list[str],
        start: date,
        end: date,
        *,
        lookback_days: int = 120,
    ) -> None:
        """批量预取：个股 + 指数。lookback 用于 60 日波动/贝塔。"""
        if not akshare_available():
            self.fetch_errors.append("未安装 akshare，跳过日行情")
            return
        fetch_start = start - timedelta(days=lookback_days)
        uniq = sorted({_norm_code(c) for c in codes if c})
        self.ensure_index(fetch_start, end)
        for code in uniq:
            self.ensure_daily(code, fetch_start, end)

    def bar(self, code: str, d: date) -> Bar | None:
        return self._daily.get(_norm_code(code), {}).get(d)

    def close_px(self, code: str, d: date) -> float | None:
        b = self.bar(code, d)
        return b.close if b else None

    def trading_days(self, start: date, end: date) -> list[date]:
        """优先用指数交易日；否则合并个股日期。"""
        days = sorted(d for d in self._index if start <= d <= end)
        if days:
            return days
        all_d: set[date] = set()
        for bars in self._daily.values():
            all_d.update(d for d in bars if start <= d <= end)
        return sorted(all_d)

    def _returns(self, bars: dict[date, Bar], days: list[date]) -> list[float]:
        rets: list[float] = []
        for i in range(1, len(days)):
            b0 = bars.get(days[i - 1])
            b1 = bars.get(days[i])
            if not b0 or not b1 or b0.close <= 0:
                continue
            rets.append((b1.close - b0.close) / b0.close)
        return rets

    def sigma_60d(self, code: str, asof: date) -> float | None:
        """截至 asof（含）的约 60 个交易日收益标准差。"""
        key = _norm_code(code)
        cache = self._sigma_cache.setdefault(key, {})
        if asof in cache:
            return cache[asof]
        bars = self._daily.get(key) or {}
        days = sorted(d for d in bars if d <= asof)
        if len(days) < 21:
            return None
        window = days[-61:]  # ~60 段收益
        rets = self._returns(bars, window)
        if len(rets) < 20:
            return None
        mu = sum(rets) / len(rets)
        var = sum((x - mu) ** 2 for x in rets) / len(rets)
        val = var**0.5
        cache[asof] = val
        return val

    def beta_60d(self, code: str, asof: date) -> float | None:
        key = _norm_code(code)
        cache = self._beta_cache.setdefault(key, {})
        if asof in cache:
            return cache[asof]
        bars = self._daily.get(key) or {}
        idx = self._index
        if not bars or not idx:
            return None
        days = sorted(d for d in bars if d <= asof and d in idx)
        if len(days) < 21:
            return None
        window = days[-61:]
        stock_rets: list[float] = []
        idx_rets: list[float] = []
        for i in range(1, len(window)):
            d0, d1 = window[i - 1], window[i]
            s0, s1 = bars.get(d0), bars.get(d1)
            i0, i1 = idx.get(d0), idx.get(d1)
            if not s0 or not s1 or not i0 or not i1:
                continue
            if s0.close <= 0 or i0.close <= 0:
                continue
            stock_rets.append((s1.close - s0.close) / s0.close)
            idx_rets.append((i1.close - i0.close) / i0.close)
        n = len(stock_rets)
        if n < 20:
            return None
        mean_s = sum(stock_rets) / n
        mean_i = sum(idx_rets) / n
        cov = sum((stock_rets[j] - mean_s) * (idx_rets[j] - mean_i) for j in range(n)) / n
        var_i = sum((x - mean_i) ** 2 for x in idx_rets) / n
        if var_i <= 1e-18:
            return None
        val = cov / var_i
        cache[asof] = val
        return val

    def ensure_spot_tags(self, codes: list[str]) -> None:
        """拉取全市场快照，打 is_hot / is_lottery / is_shell，并估波动 P75。"""
        if self._spot_tags or self._closed or not akshare_available():
            return
        import akshare as ak

        path = self._cache_path("spot_em.json")
        disk = self._load_json(path)
        rows: list[dict[str, Any]]
        if isinstance(disk, list) and disk:
            rows = disk
        else:
            rows = []
            try:
                self._throttle()
                df = ak.stock_zh_a_spot_em()
                if df is not None and not getattr(df, "empty", True):
                    for _, row in df.iterrows():
                        code = _norm_code(str(row.get("代码", "")))
                        if not code:
                            continue
                        try:
                            price = float(row.get("最新价") or 0)
                        except (TypeError, ValueError):
                            price = 0.0
                        try:
                            turn = float(row.get("换手率") or 0)
                        except (TypeError, ValueError):
                            turn = 0.0
                        try:
                            pct = float(row.get("涨跌幅") or 0)
                        except (TypeError, ValueError):
                            pct = 0.0
                        name = str(row.get("名称") or "")
                        mcap = 0.0
                        for col in ("总市值", "流通市值"):
                            try:
                                mcap = float(row.get(col) or 0)
                                if mcap:
                                    break
                            except (TypeError, ValueError):
                                pass
                        rows.append(
                            {
                                "code": code,
                                "name": name,
                                "price": price,
                                "turnover": turn,
                                "pct": pct,
                                "mcap": mcap,
                            }
                        )
                    self._save_json(path, rows)
            except Exception as e:  # noqa: BLE001
                self.fetch_errors.append(f"spot: {e}")
                return

        if not rows:
            return

        prices = sorted(r["price"] for r in rows if r.get("price", 0) > 0)
        turns = sorted(r["turnover"] for r in rows if r.get("turnover", 0) >= 0)
        mcaps = sorted(r["mcap"] for r in rows if r.get("mcap", 0) > 0)

        def pctile(sorted_vals: list[float], p: float) -> float | None:
            if not sorted_vals:
                return None
            idx = int(round((len(sorted_vals) - 1) * p))
            return sorted_vals[max(0, min(len(sorted_vals) - 1, idx))]

        p25_price = pctile(prices, 0.25)
        p75_turn = pctile(turns, 0.75)
        p10_turn = pctile(turns, 0.90)  # 换手前 10% 阈值 ≈ P90
        p10_mcap = pctile(mcaps, 0.10)

        # 用用户持仓股的 60 日波动估算市场 P75（全市场逐只算太重）
        today = date.today()
        sigmas: list[float] = []
        for c in {_norm_code(x) for x in codes}:
            s = self.sigma_60d(c, today)
            if s is not None:
                sigmas.append(s)
        if sigmas:
            sigmas.sort()
            self._market_vol_p75 = sigmas[int(round((len(sigmas) - 1) * 0.75))]
        else:
            self._market_vol_p75 = 0.03  # 兜底

        vol_p75 = self._market_vol_p75 or 0.03
        needed = {_norm_code(c) for c in codes}

        for r in rows:
            code = r["code"]
            price = float(r.get("price") or 0)
            turn = float(r.get("turnover") or 0)
            pct = float(r.get("pct") or 0)
            name = str(r.get("name") or "")
            mcap = float(r.get("mcap") or 0)
            is_st = "ST" in name.upper()
            is_hot = False
            if p10_turn is not None and turn >= p10_turn:
                is_hot = True
            if pct >= 9.5:  # 近涨停近似
                is_hot = True
            if is_hot:
                self._hot_codes.add(code)

            is_lottery = False
            if (
                p25_price is not None
                and p75_turn is not None
                and price > 0
                and price < p25_price
                and turn > p75_turn
            ):
                # 波动用持仓口径：仅对 needed 股用 sigma；其它用 turn 高作为弱代理
                sig = self.sigma_60d(code, today) if code in needed else None
                if sig is not None and sig > vol_p75:
                    is_lottery = True
                elif code not in needed and turn > (p75_turn or 0):
                    is_lottery = price < (p25_price or 0) and turn > (p75_turn or 0)

            is_shell = is_st or (
                p10_mcap is not None and mcap > 0 and mcap < p10_mcap and ("亏" in name or is_st)
            )
            # 手册：ST 或（市值<P10 且盈利为负）；盈利字段 spot 不稳定，ST + 微盘近似
            if p10_mcap is not None and mcap > 0 and mcap < p10_mcap and is_st:
                is_shell = True

            if code in needed or is_hot:
                self._spot_tags[code] = {
                    "is_hot": is_hot,
                    "is_lottery": is_lottery,
                    "is_shell": is_shell,
                    "price": price,
                    "turnover": turn,
                }

        # 补齐 needed 中未出现在快照的代码
        for code in needed:
            self._spot_tags.setdefault(
                code,
                {"is_hot": False, "is_lottery": False, "is_shell": False},
            )

    def is_hot(self, code: str, d: date | None = None) -> bool:
        """热门：快照标签，或当日涨停/高换手。"""
        key = _norm_code(code)
        if key in self._hot_codes:
            return True
        tag = self._spot_tags.get(key) or {}
        if tag.get("is_hot"):
            return True
        if d is not None:
            b = self.bar(key, d)
            if b and (b.pct_chg >= 9.5 or b.turnover >= 15.0):
                return True
        return False

    def is_lottery(self, code: str) -> bool:
        return bool((self._spot_tags.get(_norm_code(code)) or {}).get("is_lottery"))

    def is_shell(self, code: str) -> bool:
        return bool((self._spot_tags.get(_norm_code(code)) or {}).get("is_shell"))

    def market_vol_p75(self) -> float | None:
        return self._market_vol_p75

    def hot_share_market(self) -> float:
        """全市场热门占比粗估（有快照时）。"""
        if not self._spot_tags:
            return 0.2
        # 仅用已标记样本不准确；返回手册示例基准
        return 0.20
