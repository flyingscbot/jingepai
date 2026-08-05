"""金融 MBTI 前置算法（V2 工程手册 MVP）。

基于 trade_history.csv 计算行为特征 → 四维分数 → 主型 + 副标签 + 置信度。
当前数据源仅有交割单 8 字段（无日行情/问卷/沙盘），依赖行情的特征记缺失，
维度权重按可用特征重新归一。

主型判定走手册路径 A（D1 五档）；结果供 AI 提示词锚定。
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any

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
TAG_D2 = ("K", "G")  # 扛 / 割  （D2 高=纪律好→G 割？手册：D2>P50→G否则K）
# 手册：D2 决策纪律，副标签「割 G / 扛 K」；D2>P50→G 否则 K
# 但维度合成里 D2 越高越纪律（z(-de)），P50 以上应更纪律。
# 手册原文：「D2>P50→G否则K」与两极「割G/扛K」——G=割=情绪？与 D2 正向纪律矛盾。
# 按示例：D2_100=20 → K（扛），即低纪律/情绪扛单 → K；高纪律 → G？
# 示例：D2=20 → K。再看四位码含义「心态值：割G/扛K」。
# 高心态值(纪律)→G(割掉亏损的能力?)，低→K(死扛)。按手册字面实现。

TAG_D3 = ("F", "Y")  # 佛 / 痒
TAG_D4 = ("Q", "D")  # 群 / 独

OBSERVE_DAYS = 90
MIN_SELL_LOTS = 5
MIN_INTERVALS = 5
MIN_BUY_FOR_HOT = 5
MIN_MONTHS_TURNOVER = 6
MIN_POSITION_VALUE = 100.0

# 校准参数占位（手册：≥500 人后用真实 μ/σ；现用示例锚点）
CALIB_MU_SIGMA: dict[str, tuple[float, float]] = {
    "hhi": (0.35, 0.20),
    "top1_share": (0.45, 0.22),
    "duration_ratio": (0.80, 0.60),
    "annual_turnover_asinh": (1.50, 0.90),
    "freq_trades": (8.0, 6.0),
    "hold_med": (15.0, 20.0),
    "cv_interval": (0.80, 0.50),
    "buy_conc": (0.40, 0.25),
    "code_churn": (0.50, 0.25),
    "realized_loss_hold_bias": (0.55, 0.20),
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


def compute_features(records: list[dict[str, str]]) -> FeatureSet:
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

    # 月度换手：月初成本市值、当月买卖金额
    month_buy_amt: dict[str, float] = defaultdict(float)
    month_sell_amt: dict[str, float] = defaultdict(float)
    month_start_v: dict[str, float] = {}
    current_month: str | None = None

    # 日末持仓权重（成本口径）用于 HHI / top1
    daily_hhi: list[float] = []
    daily_top1: list[float] = []

    # 买入集中度 / 标的更换
    buy_amt_by_code: dict[str, float] = defaultdict(float)
    buy_codes: list[str] = []

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
        # 新月：记录月初成本市值
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
                trade_dates.append(r["date"])
        else:
            q = r["qty"]
            px = r["price"]
            if q > pos.qty + 1e-6:
                dirty += 1
                # 手册：脏数据标记，忽略该笔
                continue
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

    # --- D1 代理：集中度（无行情时替代 vol/beta/high_vol）---
    hhi = mean(daily_hhi) if daily_hhi else None
    top1 = mean(daily_top1) if daily_top1 else None
    fs.values["hhi"] = hhi
    fs.values["top1_share"] = top1
    if hhi is None:
        fs.missing.append("hhi")
    if top1 is None:
        fs.missing.append("top1_share")
    fs.missing.extend(["portfolio_vol", "portfolio_beta", "high_vol_share"])
    fs.notes.append("无日行情：portfolio_vol/beta/high_vol_share 记缺失，D1 用 HHI/top1 代理")

    # --- D2：duration_ratio + 亏损久持偏向（无行情无法算 Odean DE）---
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
            # 只有盈利批次
            duration_ratio = 10.0
            loss_hold_bias = 0.0
    fs.values["duration_ratio"] = duration_ratio
    fs.values["realized_loss_hold_bias"] = loss_hold_bias
    fs.missing.append("de")
    fs.missing.append("sandbox_de")
    fs.notes.append("无日行情/沙盘：DE 与 sandbox_de 记缺失")

    # --- D3：换手 / 频率 / 持有天数 / 间隔 CV ---
    month_t: list[float] = []
    for mk, v0 in month_start_v.items():
        # 只统计观察窗内月份
        if window and mk < month_key(window[0]["date"]):
            continue
        if v0 < MIN_POSITION_VALUE:
            # 若月初无仓，用当月买卖推导弱代理：跳过
            continue
        b = month_buy_amt.get(mk, 0.0) / v0
        s = month_sell_amt.get(mk, 0.0) / v0
        month_t.append((b + s) / 2.0)
    if len(month_t) < MIN_MONTHS_TURNOVER:
        fs.missing.append("annual_turnover")
        fs.values["annual_turnover"] = None
        fs.values["annual_turnover_asinh"] = None
        if month_t:
            # 样本不足：参考值仅供提示词展示，不进 D3 合成
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

    # 有交易的自然月
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
        else:
            # 样本标准差（手册示例用 n-1）
            if len(intervals) >= 2:
                var = sum((x - m) ** 2 for x in intervals) / (len(intervals) - 1)
                fs.values["cv_interval"] = math.sqrt(var) / m
            else:
                fs.values["cv_interval"] = 0.0

    # --- D4：无热门/彩票/壳标签 → 买入集中度 + 标的分散度代理 ---
    buy_conc = None
    code_churn = None
    if fs.n_buys < MIN_BUY_FOR_HOT:
        fs.missing.append("buy_conc")
        fs.missing.append("code_churn")
        fs.notes.append(f"买入笔数 < {MIN_BUY_FOR_HOT}，独立–跟风代理缺失")
    else:
        total_buy = sum(buy_amt_by_code.values())
        if total_buy > 0:
            ws = [a / total_buy for a in buy_amt_by_code.values()]
            buy_conc = sum(w * w for w in ws)
        uniq = len(set(buy_codes))
        code_churn = uniq / max(1, len(buy_codes))  # 越高越分散/独立
        fs.values["buy_conc"] = buy_conc
        fs.values["code_churn"] = code_churn
    fs.missing.extend(["lottery_share", "shell_share", "buy_hot_ratio", "herd_z"])
    fs.notes.append("无证券标签/行情：lottery/shell/hot/herd 记缺失，D4 用买入集中度代理")

    return fs


def synthesize_dimensions(fs: FeatureSet) -> dict[str, Any]:
    """维度合成（手册 5.2 MVP 权重，缺失重归一）。"""
    # D1：风险偏好（正向）— 无 vol/beta 时用 hhi + top1
    d1 = _weighted_z(
        [
            (0.5, _z(fs.values.get("hhi"), "hhi")),
            (0.5, _z(fs.values.get("top1_share"), "top1_share")),
        ]
    )

    # D2：决策纪律（正向）— duration_ratio 高越好；loss_hold_bias 高越差
    d2 = _weighted_z(
        [
            (0.7, _z(fs.values.get("duration_ratio"), "duration_ratio")),
            (0.3, _neg_z(fs.values.get("realized_loss_hold_bias"), "realized_loss_hold_bias")),
        ]
    )

    # D3：交易节奏（正向=手痒）
    d3 = _weighted_z(
        [
            (0.4, _z(fs.values.get("annual_turnover_asinh"), "annual_turnover_asinh")),
            (0.3, _z(fs.values.get("freq_trades"), "freq_trades")),
            (0.2, _neg_z(fs.values.get("hold_med"), "hold_med")),
            (0.1, _z(fs.values.get("cv_interval"), "cv_interval")),
        ]
    )

    # D4：独立（正向）— buy_conc 高→跟风；code_churn 高→独立
    d4 = _weighted_z(
        [
            (0.5, _neg_z(fs.values.get("buy_conc"), "buy_conc")),
            (0.5, _z(fs.values.get("code_churn"), "code_churn")),
        ]
    )

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


def run_pre_algorithm(records: list[dict[str, str]]) -> dict[str, Any]:
    """端到端：特征 → 维度 → 分型 → 置信度。"""
    fs = compute_features(records)
    dims = synthesize_dimensions(fs)
    typed = classify_type(dims["score_100"])
    conf = confidence_score(fs, dims["score_100"])

    def fmt(v: float | None, nd: int = 4) -> str | None:
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
        ("hhi", "持仓集中度 HHI"),
        ("top1_share", "第一大持仓占比"),
        ("duration_ratio", "盈亏持仓时长比"),
        ("realized_loss_hold_bias", "亏损久持偏向"),
        ("annual_turnover", "年换手率"),
        ("annual_turnover_ref", "年换手率（参考未入模）"),
        ("freq_trades", "月均交易笔数"),
        ("hold_med", "中位持有天数"),
        ("cv_interval", "交易间隔变异系数"),
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
