"""交易引擎：股票买/卖 + 基金申/赎。

规则：
- 股票：100 股整数倍(清仓可零股)；佣金 0.025% 最低 5 元(双向)；印花税 0.05%(仅卖)；T+1(买入当日冻结不可卖)。
- 基金：申购按金额，申购费 0.15%；赎回按份额，赎回费按持有天数分档；15:00 前按当日估值净值确认；T+1。
全程 Decimal；每个操作单事务。
"""
from datetime import datetime, date, time
from decimal import Decimal, ROUND_DOWN

from .db import (
    get_session, User, Stock, Fund, Holding, Order, INITIAL_CAPITAL,
)

# ---- 费率常量 ----
COMMISSION_RATE = Decimal("0.00025")     # 0.025%
MIN_COMMISSION = Decimal("5")            # 最低 5 元
STAMP_RATE = Decimal("0.0005")           # 0.05%
SUBSCRIBE_FEE_RATE = Decimal("0.0015")   # 0.15%
LOT_SIZE = 100

# 赎回费率分档：(min_days, max_days, rate)
REDEMPTION_TIERS = [
    (0, 6, Decimal("0.015")),      # <7 天 1.5%
    (7, 29, Decimal("0.0075")),    # 7-29 天 0.75%
    (30, 364, Decimal("0.005")),   # 30-364 天 0.5%
    (365, 99999, Decimal("0")),    # >=365 天 0%
]


def _redemption_rate(holding_days):
    for lo, hi, rate in REDEMPTION_TIERS:
        if lo <= holding_days <= hi:
            return rate
    return Decimal("0")


def _to_dec2(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _q4(v):
    return Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


# ====================================================================== 股票
def buy_stock(user_id, code, shares):
    """买入股票。shares 须为 100 整数倍。"""
    code = str(code).zfill(6)
    shares = int(shares)
    if shares <= 0 or shares % LOT_SIZE != 0:
        return {"success": False, "message": f"买入数量须为 {LOT_SIZE} 的整数倍"}
    s = get_session()
    try:
        user = s.query(User).get(user_id)
        if not user or user.disabled:
            return {"success": False, "message": "用户无效"}
        stock = s.query(Stock).get(code)
        if not stock or stock.price is None or stock.price <= 0:
            return {"success": False, "message": "行情数据暂不可用，请稍后再试"}
        price = stock.price
        cost = _q4(price * shares)
        commission = max(cost * COMMISSION_RATE, MIN_COMMISSION)
        commission = _to_dec2(commission)
        total = _to_dec2(cost + commission)
        if user.cash < total:
            return {"success": False, "message": f"资金不足：需 {total} 元，可用 {user.cash} 元"}

        user.cash = _to_dec2(user.cash - total)

        # 更新持仓
        h = s.query(Holding).filter(
            Holding.user_id == user_id, Holding.kind == "stock", Holding.code == code
        ).first()
        if h is None:
            h = Holding(user_id=user_id, kind="stock", code=code, name=stock.name,
                        total_shares=0, available_shares=0, frozen_shares=0, avg_cost=0,
                        first_buy_at=datetime.now())
            s.add(h)
        new_total = h.total_shares + Decimal(shares)
        # 加权平均成本（含佣金）
        h.avg_cost = _q4((h.avg_cost * h.total_shares + cost + commission) / new_total) if new_total else 0
        h.total_shares = new_total
        h.frozen_shares = h.frozen_shares + Decimal(shares)   # T+1 冻结
        if h.name != stock.name:
            h.name = stock.name

        order = Order(user_id=user_id, kind="stock", side="buy", code=code, name=stock.name,
                      shares=Decimal(shares), price=price, amount=cost, fee=commission,
                      stamp_duty=0, status="filled", submit_at=datetime.now(),
                      confirm_at=datetime.now(), note=f"佣金{commission}")
        s.add(order)
        s.commit()
        return {"success": True, "message": "买入成功",
                "order": {"price": float(price), "shares": shares, "cost": float(cost),
                          "fee": float(commission), "total": float(total)},
                "cash": float(user.cash)}
    except Exception as e:
        s.rollback()
        return {"success": False, "message": f"买入失败：{e}"}
    finally:
        s.close()


def sell_stock(user_id, code, shares):
    """卖出股票。仅可卖 available_shares（T+1 冻结不可卖）；清仓可零股全卖。"""
    code = str(code).zfill(6)
    shares = int(shares)
    if shares <= 0:
        return {"success": False, "message": "卖出数量须大于 0"}
    s = get_session()
    try:
        user = s.query(User).get(user_id)
        if not user or user.disabled:
            return {"success": False, "message": "用户无效"}
        stock = s.query(Stock).get(code)
        if not stock or stock.price is None or stock.price <= 0:
            return {"success": False, "message": "行情数据暂不可用，请稍后再试"}
        h = s.query(Holding).filter(
            Holding.user_id == user_id, Holding.kind == "stock", Holding.code == code
        ).first()
        if h is None or h.available_shares < shares:
            avail = float(h.available_shares) if h else 0
            frozen = float(h.frozen_shares) if h else 0
            if frozen > 0 and (h is None or h.available_shares < shares):
                return {"success": False, "message": f"可用不足(可用 {avail})，今日买入需 T+1 后方可卖出(冻结 {frozen})"}
            return {"success": False, "message": f"可用持仓不足，可用 {avail} 股"}
        # 手数校验：非清仓须 100 整数倍
        is_clear = shares == h.available_shares
        if not is_clear and shares % LOT_SIZE != 0:
            return {"success": False, "message": f"卖出数量须为 {LOT_SIZE} 的整数倍(清仓除外)"}

        price = stock.price
        amount = _q4(price * shares)
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        commission = _to_dec2(commission)
        stamp = _to_dec2(amount * STAMP_RATE)
        proceeds = _to_dec2(amount - commission - stamp)

        h.available_shares = h.available_shares - Decimal(shares)
        h.total_shares = h.total_shares - Decimal(shares)
        user.cash = _to_dec2(user.cash + proceeds)

        order = Order(user_id=user_id, kind="stock", side="sell", code=code, name=stock.name,
                      shares=Decimal(shares), price=price, amount=amount, fee=commission,
                      stamp_duty=stamp, status="filled", submit_at=datetime.now(),
                      confirm_at=datetime.now(), note=f"佣金{commission} 印花{stamp}")
        s.add(order)
        s.commit()
        return {"success": True, "message": "卖出成功",
                "order": {"price": float(price), "shares": shares, "amount": float(amount),
                          "fee": float(commission), "stamp": float(stamp), "proceeds": float(proceeds)},
                "cash": float(user.cash)}
    except Exception as e:
        s.rollback()
        return {"success": False, "message": f"卖出失败：{e}"}
    finally:
        s.close()


# ====================================================================== 基金
def _fund_confirm_nav(fund):
    """取基金确认净值：15:00 前用估算净值 est_nav，否则用最新公布 unit_nav。"""
    now = datetime.now()
    t = now.time()
    if time(0, 0) <= t < time(15, 0) and now.weekday() < 5:
        # 交易日 15:00 前：按当日估值
        if fund.est_nav and fund.est_nav > 0:
            return fund.est_nav, "按当日估值净值确认(15:00前)"
        if fund.unit_nav and fund.unit_nav > 0:
            return fund.unit_nav, "按最新公布净值确认"
    # 非交易时段：按最新公布净值
    if fund.unit_nav and fund.unit_nav > 0:
        return fund.unit_nav, "按最新公布净值确认"
    if fund.est_nav and fund.est_nav > 0:
        return fund.est_nav, "按估算净值确认"
    return None, "净值数据暂不可用"


def subscribe_fund(user_id, code, amount):
    """申购基金（按金额）。申购费 0.15%，份额=净额/确认净值，T+1 冻结。"""
    code = str(code).zfill(6)
    amount = Decimal(str(amount))
    if amount < 100:
        return {"success": False, "message": "申购金额须不少于 100 元"}
    s = get_session()
    try:
        user = s.query(User).get(user_id)
        if not user or user.disabled:
            return {"success": False, "message": "用户无效"}
        fund = s.query(Fund).get(code)
        if not fund:
            return {"success": False, "message": "基金数据暂不可用"}
        nav, note = _fund_confirm_nav(fund)
        if nav is None or nav <= 0:
            return {"success": False, "message": note}
        if user.cash < amount:
            return {"success": False, "message": f"资金不足：需 {amount} 元，可用 {user.cash} 元"}

        # 申购费（真实公式：fee = amount * rate / (1+rate)）
        fee = _to_dec2(amount * SUBSCRIBE_FEE_RATE / (1 + SUBSCRIBE_FEE_RATE))
        net = _to_dec2(amount - fee)
        shares = _q4(net / nav)

        user.cash = _to_dec2(user.cash - amount)
        h = s.query(Holding).filter(
            Holding.user_id == user_id, Holding.kind == "fund", Holding.code == code
        ).first()
        if h is None:
            h = Holding(user_id=user_id, kind="fund", code=code, name=fund.name,
                        total_shares=0, available_shares=0, frozen_shares=0, avg_cost=0,
                        first_buy_at=datetime.now())
            s.add(h)
        new_total = h.total_shares + shares
        h.avg_cost = _q4((h.avg_cost * h.total_shares + amount) / new_total) if new_total else 0
        h.total_shares = new_total
        h.frozen_shares = h.frozen_shares + shares   # T+1 冻结
        if h.name != fund.name:
            h.name = fund.name

        order = Order(user_id=user_id, kind="fund", side="subscribe", code=code, name=fund.name,
                      shares=shares, price=nav, amount=amount, fee=fee, stamp_duty=0,
                      status="filled", submit_at=datetime.now(), confirm_at=datetime.now(),
                      note=f"确认净值{nav} 申购费{fee} {note}")
        s.add(order)
        s.commit()
        return {"success": True, "message": "申购成功",
                "order": {"nav": float(nav), "amount": float(amount), "fee": float(fee),
                          "shares": float(shares)},
                "cash": float(user.cash)}
    except Exception as e:
        s.rollback()
        return {"success": False, "message": f"申购失败：{e}"}
    finally:
        s.close()


def redeem_fund(user_id, code, shares):
    """赎回基金（按份额）。赎回费按持有天数分档，T+1 到账。"""
    code = str(code).zfill(6)
    shares = Decimal(str(shares))
    if shares <= 0:
        return {"success": False, "message": "赎回份额须大于 0"}
    s = get_session()
    try:
        user = s.query(User).get(user_id)
        if not user or user.disabled:
            return {"success": False, "message": "用户无效"}
        fund = s.query(Fund).get(code)
        if not fund:
            return {"success": False, "message": "基金数据暂不可用"}
        nav, note = _fund_confirm_nav(fund)
        if nav is None or nav <= 0:
            return {"success": False, "message": note}
        h = s.query(Holding).filter(
            Holding.user_id == user_id, Holding.kind == "fund", Holding.code == code
        ).first()
        if h is None or h.available_shares < shares:
            avail = float(h.available_shares) if h else 0
            frozen = float(h.frozen_shares) if h else 0
            if frozen > 0:
                return {"success": False, "message": f"可用份额不足(可用 {avail})，今日申购需 T+1 后方可赎回(冻结 {frozen})"}
            return {"success": False, "message": f"可用份额不足，可用 {avail} 份"}

        # 持有天数（简化：按最早建仓时间）
        holding_days = (datetime.now() - (h.first_buy_at or datetime.now())).days
        rate = _redemption_rate(holding_days)
        gross = _q4(nav * shares)
        fee = _to_dec2(gross * rate)
        proceeds = _to_dec2(gross - fee)

        h.available_shares = h.available_shares - shares
        h.total_shares = h.total_shares - shares
        user.cash = _to_dec2(user.cash + proceeds)

        order = Order(user_id=user_id, kind="fund", side="redeem", code=code, name=fund.name,
                      shares=shares, price=nav, amount=gross, fee=fee, stamp_duty=0,
                      status="settled", submit_at=datetime.now(), confirm_at=datetime.now(),
                      note=f"持有{holding_days}天 费率{rate*100}% 赎回费{fee} {note}")
        s.add(order)
        s.commit()
        return {"success": True, "message": "赎回成功",
                "order": {"nav": float(nav), "shares": float(shares), "gross": float(gross),
                          "fee": float(fee), "proceeds": float(proceeds), "holding_days": holding_days},
                "cash": float(user.cash)}
    except Exception as e:
        s.rollback()
        return {"success": False, "message": f"赎回失败：{e}"}
    finally:
        s.close()


# ====================================================================== 查询辅助
def portfolio_summary(user_id):
    """计算用户持仓市值、总资产、累计盈亏。"""
    s = get_session()
    try:
        user = s.query(User).get(user_id)
        if not user:
            return None
        holdings = s.query(Holding).filter(Holding.user_id == user_id).all()
        market_value = Decimal("0")
        rows = []
        for h in holdings:
            if h.total_shares <= 0:
                continue
            price = _current_price(s, h.kind, h.code)
            mv = (price or 0) * h.total_shares
            market_value += mv
            cost = h.avg_cost * h.total_shares
            profit = mv - cost
            profit_pct = (profit / cost * 100) if cost and cost > 0 else Decimal("0")
            rows.append({
                "kind": h.kind, "code": h.code, "name": h.name,
                "total_shares": float(h.total_shares),
                "available_shares": float(h.available_shares),
                "frozen_shares": float(h.frozen_shares),
                "avg_cost": float(h.avg_cost), "price": float(price or 0),
                "market_value": float(_to_dec2(mv)),
                "profit": float(_to_dec2(profit)),
                "profit_pct": float(round(profit_pct, 2)),
            })
        total_asset = user.cash + market_value
        profit_total = total_asset - user.initial_capital
        profit_pct_total = (profit_total / user.initial_capital * 100) if user.initial_capital else Decimal("0")
        orders = s.query(Order).filter(Order.user_id == user_id).order_by(
            Order.submit_at.desc()).limit(50).all()
        order_rows = [{
            "id": o.id, "time": (o.submit_at or datetime.now()).strftime("%Y-%m-%d %H:%M"),
            "kind": o.kind, "side": o.side, "code": o.code, "name": o.name,
            "shares": float(o.shares), "price": float(o.price), "amount": float(o.amount),
            "fee": float(o.fee), "stamp": float(o.stamp_duty), "status": o.status,
            "note": o.note or "",
        } for o in orders]
        return {
            "cash": float(user.cash), "initial_capital": float(user.initial_capital),
            "market_value": float(_to_dec2(market_value)),
            "total_asset": float(_to_dec2(total_asset)),
            "profit": float(_to_dec2(profit_total)),
            "profit_pct": float(round(profit_pct_total, 2)),
            "holdings": rows, "orders": order_rows, "role": user.role,
        }
    finally:
        s.close()


def _current_price(s, kind, code):
    if kind == "stock":
        st = s.query(Stock).get(code)
        return st.price if st else None
    fu = s.query(Fund).get(code)
    # 基金市值用估算净值或单位净值
    if fu:
        return fu.est_nav or fu.unit_nav
    return None
