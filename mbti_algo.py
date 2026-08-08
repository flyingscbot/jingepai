"""金融 MBTI 前置算法（V2 工程手册 MVP）。

基于 trade_history.csv 计算行为特征 → 四维分数 → 主型 + 副标签 + 置信度。
有 MarketSession（akshare 日行情）时计算 DE / vol / beta / hot 等正式特征；
否则记缺失并按可用特征重归一权重。

主型判定走手册路径 A（D1 五档）；结果供 AI 提示词锚定。
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from market_data import MarketSession

# 与 mbti_log / UI 展示名一致（手册 C1–C5）
TYPE_BY_CODE = {
    "C1": "苟住型",
    "C2": "稳字型",
    "C3": "端水型",
    "C4": "操作型",
    "C5": "梭哈型",
}
CODE_BY_TYPE = {v: k for k, v in TYPE_BY_CODE.items()}

TAG_D1 = ("W", "M")  # 稳 / 莽
TAG_D2 = ("K", "G")  # 扛 / 割
TAG_D3 = ("F", "Y")  # 佛 / 痒
TAG_D4 = ("Q", "D")  # 群 / 独
DIM_KEYS = ("D1", "D2", "D3", "D4")


def split_tags(tags: str) -> dict[str, str]:
    """将四位副标签串（如 MGYD）拆为 D1–D4 单列字典。"""
    t = (tags or "").strip()
    return {k: (t[i] if i < len(t) else "") for i, k in enumerate(DIM_KEYS)}

OBSERVE_DAYS = 90
MIN_SELL_LOTS = 5
MIN_INTERVALS = 5
MIN_BUY_FOR_HOT = 5
MIN_MONTHS_TURNOVER = 6
MIN_POSITION_VALUE = 100.0
MIN_DE_REALIZED = 10  # RG+RL

# 校准参数占位（手册：≥500 人后用真实 μ/σ；现用示例锚点）
CALIB_MU_SIGMA: dict[str, tuple[float, float]] = {
    "hhi": (0.35, 0.20),
    "top1_share": (0.45, 0.22),
    "portfolio_vol": (0.025, 0.012),
    "portfolio_beta": (1.0, 0.35),
    "high_vol_share": (0.25, 0.20),
    "de": (0.05, 0.20),
    "duration_ratio": (0.80, 0.60),
    "annual_turnover_asinh": (1.50, 0.90),
    "freq_trades": (8.0, 6.0),
    "hold_med": (15.0, 20.0),
    "cv_interval": (0.80, 0.50),
    "buy_conc": (0.40, 0.25),
    "code_churn": (0.50, 0.25),
    "realized_loss_hold_bias": (0.55, 0.20),
    "buy_hot_ratio": (0.25, 0.20),
    "lottery_share": (0.15, 0.15),
    "shell_share": (0.10, 0.12),
    "herd_z": (0.0, 1.0),
}


@dataclass
class Lot:
    buy_date: date
    price: float
    qty: float


@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0


@dataclass
class FeatureSet:
    values: dict[str, float | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    n_trades: int = 0
    n_sells: int = 0
    n_buys: int = 0
    dirty: int = 0
    window_start: str = ""
    window_end: str = ""


def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_float(v: Any) -> float | None:
    try:
        x = float(str(v).strip().replace(",", ""))
        if math.isfinite(x):
            return x
    except (TypeError, ValueError):
        pass
    return None


def _is_buy(action: str) -> bool:
    a = (action or "").strip()
    return a in ("买入", "买", "B", "buy", "Buy")


def _is_sell(action: str) -> bool:
    a = (action or "").strip()
    return a in ("卖出", "卖", "S", "sell", "Sell")


def _asinh(x: float) -> float:
    return math.asinh(x)


def _z(x: float | None, key: str) -> float | None:
    if x is None:
        return None
    mu, sigma = CALIB_MU_SIGMA.get(key, (0.0, 1.0))
    if sigma <= 1e-9:
        return 0.0
    return (x - mu) / sigma


def _percentile_100(z: float | None) -> float | None:
    """标准正态 CDF × 100，把维度 z 映射到 0–100。"""
    if z is None:
        return None
    # 近似 Φ(z)
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989423 * math.exp(-0.5 * z * z)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    cdf = 1.0 - p if z > 0 else p
    return max(0.0, min(100.0, cdf * 100.0))


def _weighted_z(parts: list[tuple[float, float | None]]) -> float | None:
    """parts: (weight, z_or_None)；缺失项跳过并重新归一权重。"""
    usable = [(w, z) for w, z in parts if z is not None and w > 0]
    if not usable:
        return None
    tw = sum(w for w, _ in usable)
    if tw <= 0:
        return None
    return sum((w / tw) * z for w, z in usable)


def _normalize_trades(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in records:
        d = _parse_date(r.get("成交日期", ""))
        if d is None:
            continue
        qty = _to_float(r.get("成交数量"))
        price = _to_float(r.get("成交均价"))
        amount = _to_float(r.get("成交金额"))
        if qty is None or price is None or qty <= 0 or price < 0:
            continue
        if amount is None or amount <= 0:
            amount = qty * price
        action = (r.get("操作") or "").strip()
        if not (_is_buy(action) or _is_sell(action)):
            continue
        code = (r.get("证券代码") or "").strip()
        if not code:
            continue
        time_s = (r.get("时间") or "00:00:00").strip() or "00:00:00"
        rows.append(
            {
                "date": d,
                "time": time_s,
                "code": code,
                "name": (r.get("证券名称") or "").strip(),
                "buy": _is_buy(action),
                "qty": qty,
                "price": price,
                "amount": amount,
            }
        )
    # 同日先买后卖
    rows.sort(key=lambda x: (x["date"], x["time"], 0 if x["buy"] else 1, x["code"]))
    return rows


def _filter_window(rows: list[dict[str, Any]], days: int = OBSERVE_DAYS) -> list[dict[str, Any]]:
    if not rows:
        return []
    end = rows[-1]["date"]
    start = end - timedelta(days=days)
    return [r for r in rows if r["date"] >= start]


def compute_features(
    records: list[dict[str, str]],
    market: MarketSession | None = None,
) -> FeatureSet:
    """从成交记录计算手册中可落地的行为特征。"""
    fs = FeatureSet()
    all_rows = _normalize_trades(records)
    if not all_rows:
        fs.notes.append("无有效成交记录")
        return fs

    # WAC / FIFO 需要完整历史重建，特征统计落在观察窗
    window = _filter_window(all_rows)
    fs.n_trades = len(window)
    fs.n_buys = sum(1 for r in window if r["buy"])
    fs.n_sells = sum(1 for r in window if not r["buy"])
    fs.window_start = window[0]["date"].isoformat() if window else ""
    fs.window_end = window[-1]["date"].isoformat() if window else ""

    positions: dict[str, Position] = defaultdict(Position)
    lots: dict[str, deque[Lot]] = defaultdict(deque)
    closed_hold_days: list[float] = []
    win_days: list[float] = []
    loss_days: list[float] = []
    dirty = 0

    # 月度换手：月初成本市值、当月买卖金额（无行情时的兜底）
    month_buy_amt: dict[str, float] = defaultdict(float)
    month_sell_amt: dict[str, float] = defaultdict(float)
    month_start_v: dict[str, float] = {}
    current_month: str | None = None

    # 日末持仓权重（成本口径）用于 HHI / top1 兜底
    daily_hhi: list[float] = []
    daily_top1: list[float] = []

    # 买入集中度 / 标的更换
    buy_amt_by_code: dict[str, float] = defaultdict(float)
    buy_codes: list[str] = []
    window_buys: list[tuple[date, str]] = []  # (date, code) 供 buy_hot
    # 卖出日成本（卖出前 WAC），供 DE 已实现计数
    sell_cost_before: dict[tuple[date, str], float] = {}

    trade_dates: list[date] = []

    def snapshot_weights() -> None:
        total = sum(max(0.0, p.qty) * p.avg_cost for p in positions.values())
        if total < MIN_POSITION_VALUE:
            return
        weights = []
        for p in positions.values():
            if p.qty <= 0:
                continue
            weights.append((p.qty * p.avg_cost) / total)
        if not weights:
            return
        daily_hhi.append(sum(w * w for w in weights))
        daily_top1.append(max(weights))

    def month_key(d: date) -> str:
        return f"{d.year:04d}-{d.month:02d}"

    def ensure_month(d: date) -> None:
        nonlocal current_month
        mk = month_key(d)
        if current_month == mk:
            return
        v = sum(max(0.0, p.qty) * p.avg_cost for p in positions.values())
        month_start_v[mk] = v
        current_month = mk

    for r in all_rows:
        in_window = bool(window) and r["date"] >= window[0]["date"]
        ensure_month(r["date"])
        code = r["code"]
        pos = positions[code]
        mk = month_key(r["date"])

        if r["buy"]:
            q = r["qty"]
            px = r["price"]
            new_qty = pos.qty + q
            if new_qty > 0:
                pos.avg_cost = (pos.qty * pos.avg_cost + q * px) / new_qty
            pos.qty = new_qty
            lots[code].append(Lot(r["date"], px, q))
            if in_window:
                month_buy_amt[mk] += r["amount"]
                buy_amt_by_code[code] += r["amount"]
                buy_codes.append(code)
                window_buys.append((r["date"], code))
                trade_dates.append(r["date"])
        else:
            q = r["qty"]
            px = r["price"]
            if q > pos.qty + 1e-6:
                dirty += 1
                continue
            if in_window and pos.avg_cost > 0:
                sell_cost_before[(r["date"], code)] = pos.avg_cost
            remain = q
            while remain > 1e-9 and lots[code]:
                lot = lots[code][0]
                take = min(lot.qty, remain)
                hold = (r["date"] - lot.buy_date).days
                pnl = (px - lot.price) * take
                if in_window:
                    closed_hold_days.append(float(hold))
                    if pnl > 0:
                        win_days.append(float(hold))
                    elif pnl < 0:
                        loss_days.append(float(hold))
                lot.qty -= take
                remain -= take
                if lot.qty <= 1e-9:
                    lots[code].popleft()
            pos.qty -= q
            if pos.qty <= 1e-9:
                pos.qty = 0.0
                pos.avg_cost = 0.0
            if in_window:
                month_sell_amt[mk] += r["amount"]
                trade_dates.append(r["date"])

        if in_window:
            snapshot_weights()

    fs.dirty = dirty
    if dirty:
        fs.notes.append(f"脏数据卖出超持仓 {dirty} 笔已忽略")

    # --- D1 兜底：成本口径集中度 ---
    hhi = mean(daily_hhi) if daily_hhi else None
    top1 = mean(daily_top1) if daily_top1 else None
    fs.values["hhi"] = hhi
    fs.values["top1_share"] = top1
    if hhi is None:
        fs.missing.append("hhi")
    if top1 is None:
        fs.missing.append("top1_share")
    fs.values["portfolio_vol"] = None
    fs.values["portfolio_beta"] = None
    fs.values["high_vol_share"] = None
    fs.missing.extend(["portfolio_vol", "portfolio_beta", "high_vol_share"])

    # --- D2：duration_ratio + 亏损久持偏向 ---
    duration_ratio = None
    loss_hold_bias = None
    if len(closed_hold_days) < MIN_SELL_LOTS:
        fs.missing.append("duration_ratio")
        fs.missing.append("realized_loss_hold_bias")
        fs.notes.append(f"卖出批次 < {MIN_SELL_LOTS}，纪律类特征缺失")
    else:
        if win_days and loss_days:
            win_dur = mean(win_days)
            loss_dur = mean(loss_days)
            if loss_dur <= 0:
                duration_ratio = 10.0
            else:
                duration_ratio = min(10.0, win_dur / loss_dur)
            loss_hold_bias = loss_dur / (win_dur + loss_dur)
        elif not win_days:
            fs.missing.append("duration_ratio")
            fs.notes.append("无盈利卖出批次，duration_ratio 缺失")
            if loss_days:
                loss_hold_bias = 1.0
        else:
            duration_ratio = 10.0
            loss_hold_bias = 0.0
    fs.values["duration_ratio"] = duration_ratio
    fs.values["realized_loss_hold_bias"] = loss_hold_bias
    fs.values["de"] = None
    fs.missing.append("de")
    fs.missing.append("sandbox_de")

    # --- D3：换手 / 频率 / 持有天数 / 间隔 CV ---
    month_t: list[float] = []
    for mk, v0 in month_start_v.items():
        if window and mk < month_key(window[0]["date"]):
            continue
        if v0 < MIN_POSITION_VALUE:
            continue
        b = month_buy_amt.get(mk, 0.0) / v0
        s = month_sell_amt.get(mk, 0.0) / v0
        month_t.append((b + s) / 2.0)
    if len(month_t) < MIN_MONTHS_TURNOVER:
        fs.missing.append("annual_turnover")
        fs.values["annual_turnover"] = None
        fs.values["annual_turnover_asinh"] = None
        if month_t:
            ref = mean(month_t) * 12.0
            fs.values["annual_turnover_ref"] = ref
            fs.notes.append(
                f"有效换手月仅 {len(month_t)}（<{MIN_MONTHS_TURNOVER}），"
                f"年换手参考≈{ref:.2f}，不参与维度合成"
            )
        else:
            fs.notes.append("无法计算年换手率（月初持仓市值不足）")
    else:
        annual_turnover = mean(month_t) * 12.0
        fs.values["annual_turnover"] = annual_turnover
        fs.values["annual_turnover_asinh"] = _asinh(annual_turnover)

    months_with_trade = {month_key(d) for d in trade_dates}
    if not months_with_trade:
        fs.values["freq_trades"] = None
        fs.missing.append("freq_trades")
    else:
        fs.values["freq_trades"] = fs.n_trades / max(1, len(months_with_trade))

    if len(closed_hold_days) < MIN_SELL_LOTS:
        fs.values["hold_med"] = None
        fs.missing.append("hold_med")
    else:
        fs.values["hold_med"] = float(median(closed_hold_days))

    intervals: list[float] = []
    if len(trade_dates) >= 2:
        ordered = sorted(trade_dates)
        for i in range(1, len(ordered)):
            intervals.append(float((ordered[i] - ordered[i - 1]).days))
    if len(intervals) < MIN_INTERVALS:
        fs.values["cv_interval"] = None
        fs.missing.append("cv_interval")
    else:
        m = mean(intervals)
        if m <= 0:
            fs.values["cv_interval"] = 0.0
        elif len(intervals) >= 2:
            var = sum((x - m) ** 2 for x in intervals) / (len(intervals) - 1)
            fs.values["cv_interval"] = math.sqrt(var) / m
        else:
            fs.values["cv_interval"] = 0.0

    # --- D4 兜底 ---
    if fs.n_buys < MIN_BUY_FOR_HOT:
        fs.missing.append("buy_conc")
        fs.missing.append("code_churn")
        fs.notes.append(f"买入笔数 < {MIN_BUY_FOR_HOT}，独立–跟风代理缺失")
        fs.values["buy_conc"] = None
        fs.values["code_churn"] = None
    else:
        total_buy = sum(buy_amt_by_code.values())
        if total_buy > 0:
            ws = [a / total_buy for a in buy_amt_by_code.values()]
            fs.values["buy_conc"] = sum(w * w for w in ws)
        else:
            fs.values["buy_conc"] = None
        uniq = len(set(buy_codes))
        fs.values["code_churn"] = uniq / max(1, len(buy_codes))
    fs.values["lottery_share"] = None
    fs.values["shell_share"] = None
    fs.values["buy_hot_ratio"] = None
    fs.values["herd_z"] = None
    fs.missing.extend(["lottery_share", "shell_share", "buy_hot_ratio", "herd_z"])

    if market is not None and window:
        _enrich_with_market(
            fs,
            market,
            all_rows=all_rows,
            window=window,
            window_buys=window_buys,
            sell_cost_before=sell_cost_before,
            month_buy_amt=month_buy_amt,
            month_sell_amt=month_sell_amt,
        )
    else:
        fs.notes.append("无日行情会话：DE/vol/beta/hot 等记缺失，用成本代理")

    return fs


def _enrich_with_market(
    fs: FeatureSet,
    market: MarketSession,
    *,
    all_rows: list[dict[str, Any]],
    window: list[dict[str, Any]],
    window_buys: list[tuple[date, str]],
    sell_cost_before: dict[tuple[date, str], float],
    month_buy_amt: dict[str, float],
    month_sell_amt: dict[str, float],
) -> None:
    """用日行情补全 DE / 市值加权风险 / 热门跟风等特征。"""
    import market_data as mkt_mod

    if not mkt_mod.akshare_available():
        fs.notes.append("未安装 akshare，跳过日行情增强")
        return

    w_start = window[0]["date"]
    w_end = window[-1]["date"]
    codes = sorted({r["code"] for r in all_rows})
    try:
        market.prefetch(codes, w_start, w_end, lookback_days=120)
        market.ensure_spot_tags(codes)
    except Exception as e:  # noqa: BLE001
        fs.notes.append(f"行情预取失败：{e}")
        return

    if market.fetch_errors:
        fs.notes.append("行情部分失败：" + "；".join(market.fetch_errors[:3]))

    # 重建持仓轨迹（含窗前），按交易日做 DE / 市值权重
    positions: dict[str, Position] = defaultdict(Position)
    trade_i = 0
    rg = rl = pg = pl = 0
    sell_days_in_window = {r["date"] for r in window if not r["buy"]}

    days = market.trading_days(all_rows[0]["date"], w_end)
    if not days:
        fs.notes.append("无交易日行情，跳过 DE/vol 增强")
        return

    vol_series: list[float] = []
    beta_series: list[float] = []
    hhi_mkt: list[float] = []
    top1_mkt: list[float] = []
    high_vol_series: list[float] = []
    lottery_series: list[float] = []
    shell_series: list[float] = []
    hot_hold_series: list[float] = []

    month_start_mv: dict[str, float] = {}
    last_month: str | None = None

    def month_key(d: date) -> str:
        return f"{d.year:04d}-{d.month:02d}"

    vol_p75 = market.market_vol_p75() or 0.03

    for d in days:
        while trade_i < len(all_rows) and all_rows[trade_i]["date"] <= d:
            tr = all_rows[trade_i]
            code = tr["code"]
            pos = positions[code]
            if tr["buy"]:
                q, px = tr["qty"], tr["price"]
                new_qty = pos.qty + q
                if new_qty > 0:
                    pos.avg_cost = (pos.qty * pos.avg_cost + q * px) / new_qty
                pos.qty = new_qty
            else:
                q = tr["qty"]
                if q <= pos.qty + 1e-6:
                    pos.qty -= q
                    if pos.qty <= 1e-9:
                        pos.qty = 0.0
                        pos.avg_cost = 0.0
            trade_i += 1

        mk = month_key(d)
        if last_month != mk:
            mv = 0.0
            for c, p in positions.items():
                if p.qty <= 0:
                    continue
                px = market.close_px(c, d)
                if px is None:
                    px = p.avg_cost
                mv += p.qty * px
            month_start_mv[mk] = mv
            last_month = mk

        if d < w_start:
            continue

        holdings: list[tuple[str, float, float, float]] = []
        total_mv = 0.0
        for c, p in positions.items():
            if p.qty <= 0:
                continue
            px = market.close_px(c, d)
            if px is None or px <= 0:
                px = p.avg_cost
            if px <= 0:
                continue
            total_mv += p.qty * px
            holdings.append((c, p.qty, p.avg_cost, px))

        if total_mv >= MIN_POSITION_VALUE and holdings:
            weights: list[float] = []
            pvol = 0.0
            pbeta = 0.0
            high_w = 0.0
            lot_w = 0.0
            shell_w = 0.0
            hot_w = 0.0
            have_vol = False
            have_beta = False
            for c, q, _cost, px in holdings:
                w = (q * px) / total_mv
                weights.append(w)
                sig = market.sigma_60d(c, d)
                if sig is not None:
                    pvol += w * sig
                    have_vol = True
                    if sig > vol_p75:
                        high_w += w
                bet = market.beta_60d(c, d)
                if bet is not None:
                    pbeta += w * bet
                    have_beta = True
                if market.is_lottery(c):
                    lot_w += w
                if market.is_shell(c):
                    shell_w += w
                if market.is_hot(c, d):
                    hot_w += w
            hhi_mkt.append(sum(w * w for w in weights))
            top1_mkt.append(max(weights))
            if have_vol:
                vol_series.append(pvol)
                high_vol_series.append(high_w)
            if have_beta:
                beta_series.append(pbeta)
            lottery_series.append(lot_w)
            shell_series.append(shell_w)
            hot_hold_series.append(hot_w)

        if d in sell_days_in_window:
            sold_codes = {r["code"] for r in window if (not r["buy"]) and r["date"] == d}
            for code in sold_codes:
                sells = [
                    r
                    for r in window
                    if (not r["buy"]) and r["date"] == d and r["code"] == code
                ]
                if not sells:
                    continue
                avg_sell = sum(r["price"] * r["qty"] for r in sells) / sum(
                    r["qty"] for r in sells
                )
                cost = sell_cost_before.get((d, code))
                if cost is None or cost <= 0:
                    continue
                if avg_sell > cost:
                    rg += 1
                elif avg_sell < cost:
                    rl += 1

            for c, p in positions.items():
                if p.qty <= 0 or c in sold_codes:
                    continue
                bar = market.bar(c, d)
                if not bar or p.avg_cost <= 0:
                    continue
                if bar.high > p.avg_cost:
                    pg += 1
                if bar.low < p.avg_cost:
                    pl += 1

    # 写入 DE
    if rg + rl >= MIN_DE_REALIZED:
        pgr = rg / (rg + pg) if (rg + pg) > 0 else None
        plr = rl / (rl + pl) if (rl + pl) > 0 else None
        if pgr is not None and plr is not None:
            de = pgr - plr
            fs.values["de"] = de
            if "de" in fs.missing:
                fs.missing.remove("de")
            fs.notes.append(f"DE=PGR−PLR={de:.3f}（RG{rg}/RL{rl}/PG{pg}/PL{pl}）")
        else:
            fs.notes.append("DE 分母为 0，记缺失")
    else:
        fs.notes.append(f"已实现盈亏样本 RG+RL={rg + rl}<{MIN_DE_REALIZED}，DE 缺失")

    # D1 市值口径
    if len(vol_series) >= 20:
        fs.values["portfolio_vol"] = mean(vol_series)
        if "portfolio_vol" in fs.missing:
            fs.missing.remove("portfolio_vol")
    if len(beta_series) >= 20:
        fs.values["portfolio_beta"] = mean(beta_series)
        if "portfolio_beta" in fs.missing:
            fs.missing.remove("portfolio_beta")
    if len(high_vol_series) >= 20:
        fs.values["high_vol_share"] = mean(high_vol_series)
        if "high_vol_share" in fs.missing:
            fs.missing.remove("high_vol_share")
    if hhi_mkt:
        fs.values["hhi"] = mean(hhi_mkt)
        if "hhi" in fs.missing:
            fs.missing.remove("hhi")
    if top1_mkt:
        fs.values["top1_share"] = mean(top1_mkt)
        if "top1_share" in fs.missing:
            fs.missing.remove("top1_share")

    # 市值口径年换手（可覆盖成本口径）
    month_t_mkt: list[float] = []
    for mk, v0 in month_start_mv.items():
        if mk < month_key(w_start):
            continue
        if v0 < MIN_POSITION_VALUE:
            continue
        b = month_buy_amt.get(mk, 0.0) / v0
        s = month_sell_amt.get(mk, 0.0) / v0
        month_t_mkt.append((b + s) / 2.0)
    if len(month_t_mkt) >= MIN_MONTHS_TURNOVER:
        annual = mean(month_t_mkt) * 12.0
        fs.values["annual_turnover"] = annual
        fs.values["annual_turnover_asinh"] = _asinh(annual)
        if "annual_turnover" in fs.missing:
            fs.missing.remove("annual_turnover")
        fs.values.pop("annual_turnover_ref", None)

    # D4：热门买入比 / 彩票 / 壳 / 跟风
    if len(window_buys) >= MIN_BUY_FOR_HOT:
        hot_n = sum(1 for d, c in window_buys if market.is_hot(c, d))
        ratio = hot_n / len(window_buys)
        fs.values["buy_hot_ratio"] = ratio
        if "buy_hot_ratio" in fs.missing:
            fs.missing.remove("buy_hot_ratio")
        mkt_hot = market.hot_share_market()
        # herd_z ≈ (用户热门持仓占比 − 市场) / 0.10
        user_hot = mean(hot_hold_series) if hot_hold_series else ratio
        fs.values["herd_z"] = (user_hot - mkt_hot) / 0.10
        if "herd_z" in fs.missing:
            fs.missing.remove("herd_z")
    if lottery_series:
        fs.values["lottery_share"] = mean(lottery_series)
        if "lottery_share" in fs.missing:
            fs.missing.remove("lottery_share")
    if shell_series:
        fs.values["shell_share"] = mean(shell_series)
        if "shell_share" in fs.missing:
            fs.missing.remove("shell_share")

    fs.notes.append("已接入 akshare 日行情增强")


def synthesize_dimensions(fs: FeatureSet) -> dict[str, Any]:
    """维度合成（手册 5.2 MVP 权重，缺失重归一）。"""
    # D1 = 0.4×z(vol) + 0.2×z(beta) + 0.2×z(HHI) + 0.2×z(high_vol)
    d1_parts: list[tuple[float, float | None]] = [
        (0.4, _z(fs.values.get("portfolio_vol"), "portfolio_vol")),
        (0.2, _z(fs.values.get("portfolio_beta"), "portfolio_beta")),
        (0.2, _z(fs.values.get("hhi"), "hhi")),
        (0.2, _z(fs.values.get("high_vol_share"), "high_vol_share")),
    ]
    # 无行情风险特征时，用 top1 集中度代理补位
    if fs.values.get("portfolio_vol") is None and fs.values.get("high_vol_share") is None:
        d1_parts.append((0.2, _z(fs.values.get("top1_share"), "top1_share")))
    d1 = _weighted_z(d1_parts)

    # D2 = 0.6×z(−de) + 0.2×z(duration_ratio) + 0.2×亏损久持代理（无 sandbox_de）
    d2 = _weighted_z(
        [
            (0.6, _neg_z(fs.values.get("de"), "de")),
            (0.2, _z(fs.values.get("duration_ratio"), "duration_ratio")),
            (0.2, _neg_z(fs.values.get("realized_loss_hold_bias"), "realized_loss_hold_bias")),
        ]
    )

    # D3 = 0.4×换手 + 0.3×频率 + 0.2×(−持有) + 0.1×间隔CV
    d3 = _weighted_z(
        [
            (0.4, _z(fs.values.get("annual_turnover_asinh"), "annual_turnover_asinh")),
            (0.3, _z(fs.values.get("freq_trades"), "freq_trades")),
            (0.2, _neg_z(fs.values.get("hold_med"), "hold_med")),
            (0.1, _z(fs.values.get("cv_interval"), "cv_interval")),
        ]
    )

    # D4 = 0.4×(−herd) + 0.2×(−hot) + 0.2×(−lottery) + 0.2×(−shell)
    d4_parts: list[tuple[float, float | None]] = [
        (0.4, _neg_z(fs.values.get("herd_z"), "herd_z")),
        (0.2, _neg_z(fs.values.get("buy_hot_ratio"), "buy_hot_ratio")),
        (0.2, _neg_z(fs.values.get("lottery_share"), "lottery_share")),
        (0.2, _neg_z(fs.values.get("shell_share"), "shell_share")),
    ]
    if (
        fs.values.get("herd_z") is None
        and fs.values.get("buy_hot_ratio") is None
        and fs.values.get("lottery_share") is None
    ):
        d4_parts.extend(
            [
                (0.5, _neg_z(fs.values.get("buy_conc"), "buy_conc")),
                (0.5, _z(fs.values.get("code_churn"), "code_churn")),
            ]
        )
    d4 = _weighted_z(d4_parts)

    dims_z = {"D1": d1, "D2": d2, "D3": d3, "D4": d4}
    dims_100 = {k: _percentile_100(v) for k, v in dims_z.items()}
    return {"z": dims_z, "score_100": dims_100}


def _neg_z(x: float | None, key: str) -> float | None:
    z = _z(x, key)
    return None if z is None else -z


def classify_type(dims_100: dict[str, float | None]) -> dict[str, Any]:
    """路径 A：按 D1 分位五档；副标签按各维是否 >50。"""
    d1 = dims_100.get("D1")
    if d1 is None:
        # 无法定主型时给中性端水，置信度会很低
        code = "C3"
        reason = "D1 缺失，暂定端水型"
    elif d1 < 20:
        code = "C1"
        reason = f"D1={d1:.1f}<P20"
    elif d1 < 40:
        code = "C2"
        reason = f"D1={d1:.1f}∈[P20,P40)"
    elif d1 < 60:
        code = "C3"
        reason = f"D1={d1:.1f}∈[P40,P60)"
    elif d1 < 80:
        code = "C4"
        reason = f"D1={d1:.1f}∈[P60,P80)"
    else:
        code = "C5"
        reason = f"D1={d1:.1f}≥P80"

    def bit(score: float | None, low: str, high: str) -> str:
        if score is None:
            return "?"
        return high if score > 50 else low

    tags = (
        bit(dims_100.get("D1"), *TAG_D1)
        + bit(dims_100.get("D2"), *TAG_D2)
        + bit(dims_100.get("D3"), *TAG_D3)
        + bit(dims_100.get("D4"), *TAG_D4)
    )
    return {
        "code": code,
        "mbti": TYPE_BY_CODE[code],
        "tags": tags,
        "reason": reason,
    }


def confidence_score(
    fs: FeatureSet,
    dims_100: dict[str, float | None],
    *,
    survey_consistent: float | None = None,
) -> float:
    """手册 5.5 启发式置信度。"""
    n = fs.n_trades
    base = 0.5 + 0.3 * min(1.0, n / 50.0)
    # 无问卷时一致性项给中性 0.5×0.2
    cons = 0.5 if survey_consistent is None else max(0.0, min(1.0, survey_consistent))
    base += 0.2 * cons

    # 边界惩罚：D1 靠近 20/40/60/80
    d1 = dims_100.get("D1")
    penalty = 0.0
    if d1 is not None:
        for edge in (20.0, 40.0, 60.0, 80.0):
            if abs(d1 - edge) < 5.0:
                penalty = max(penalty, 0.08)
                break
    # 特征大量缺失再罚
    miss_ratio = len(set(fs.missing)) / 14.0
    penalty += 0.15 * min(1.0, miss_ratio)

    return max(0.05, min(1.0, base - penalty))


def run_pre_algorithm(
    records: list[dict[str, str]],
    market: MarketSession | None = None,
) -> dict[str, Any]:
    """端到端：特征 → 维度 → 分型 → 置信度。

    market 由调用方提供（分析会话）；分析结束后由调用方 close 清理缓存。
    """
    fs = compute_features(records, market=market)
    dims = synthesize_dimensions(fs)
    typed = classify_type(dims["score_100"])
    conf = confidence_score(fs, dims["score_100"])

    def fmt(v: float | None, nd: int = 4) -> Any:
        if v is None:
            return None
        return round(v, nd)

    features_out = {k: fmt(v) for k, v in fs.values.items()}
    score_100 = {k: fmt(v, 1) for k, v in dims["score_100"].items()}
    score_z = {k: fmt(v, 3) for k, v in dims["z"].items()}

    return {
        "mbti": typed["mbti"],
        "code": typed["code"],
        "tags": typed["tags"],
        "confidence": round(conf, 3),
        "classify_reason": typed["reason"],
        "dimensions": {
            "莽值_D1": score_100.get("D1"),
            "心态值_D2": score_100.get("D2"),
            "手痒值_D3": score_100.get("D3"),
            "主见值_D4": score_100.get("D4"),
        },
        "dimensions_z": score_z,
        "features": features_out,
        "missing_features": sorted(set(fs.missing)),
        "notes": fs.notes,
        "stats": {
            "n_trades": fs.n_trades,
            "n_buys": fs.n_buys,
            "n_sells": fs.n_sells,
            "dirty_sells": fs.dirty,
            "window_start": fs.window_start,
            "window_end": fs.window_end,
            "observe_days": OBSERVE_DAYS,
            "market_used": market is not None,
        },
        "display": f"{typed['mbti']}（{typed['code']}）· {typed['tags']} · 置信度 {conf:.2f}",
    }


def format_algo_for_prompt(algo: dict[str, Any]) -> str:
    """格式化为写入 AI 用户提示词的文本块。"""
    lines = [
        "【前置算法分析结果｜金融 MBTI V2】",
        f"建议主型：{algo.get('display') or algo.get('mbti')}",
        f"判定依据：{algo.get('classify_reason') or ''}",
        "四维百分位（0–100）：",
    ]
    dims = algo.get("dimensions") or {}
    for label, key in (
        ("莽值 D1（风险偏好）", "莽值_D1"),
        ("心态值 D2（决策纪律）", "心态值_D2"),
        ("手痒值 D3（交易节奏）", "手痒值_D3"),
        ("主见值 D4（独立–跟风）", "主见值_D4"),
    ):
        v = dims.get(key)
        lines.append(f"  - {label}：{v if v is not None else '缺失'}")

    lines.append("关键行为特征（原始/代理）：")
    feats = algo.get("features") or {}
    feature_labels = [
        ("portfolio_vol", "组合加权波动率"),
        ("portfolio_beta", "组合贝塔"),
        ("high_vol_share", "高波动股票占比"),
        ("hhi", "持仓集中度 HHI"),
        ("top1_share", "第一大持仓占比"),
        ("de", "处置效应 DE"),
        ("duration_ratio", "盈亏持仓时长比"),
        ("realized_loss_hold_bias", "亏损久持偏向"),
        ("annual_turnover", "年换手率"),
        ("annual_turnover_ref", "年换手率（参考未入模）"),
        ("freq_trades", "月均交易笔数"),
        ("hold_med", "中位持有天数"),
        ("cv_interval", "交易间隔变异系数"),
        ("buy_hot_ratio", "买入热门股比例"),
        ("herd_z", "跟风度 herd_z"),
        ("lottery_share", "彩票股占比"),
        ("shell_share", "壳股占比"),
        ("buy_conc", "买入金额集中度"),
        ("code_churn", "买入标的分散度"),
    ]
    for key, label in feature_labels:
        v = feats.get(key)
        if v is None:
            continue
        lines.append(f"  - {label}：{v}")

    miss = algo.get("missing_features") or []
    if miss:
        lines.append("缺失特征（未参与合成）：" + "、".join(miss))

    stats = algo.get("stats") or {}
    lines.append(
        "样本："
        f"窗内成交 {stats.get('n_trades', 0)} 笔"
        f"（买 {stats.get('n_buys', 0)} / 卖 {stats.get('n_sells', 0)}），"
        f"窗口 {stats.get('window_start') or '?'} ~ {stats.get('window_end') or '?'}"
        f"（最近 {stats.get('observe_days', OBSERVE_DAYS)} 天）"
    )
    notes = algo.get("notes") or []
    if notes:
        lines.append("备注：" + "；".join(notes[:6]))
    return "\n".join(lines)
