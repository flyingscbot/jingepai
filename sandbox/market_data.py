"""行情数据层：akshare 实时行情 + 周期刷新 + 近半年历史缓存 + 搜索。

- akshare 不可用或失败时回退到 seed 的 mock 数据（stale=True）。
- 所有 akshare 调用经 ThreadPoolExecutor 15s 超时保护，避免挂起。
- APScheduler 仅在 reloader 主子进程启动，避免 debug 重复启动。
"""
import os
import atexit
import threading
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout

from . import akshare_cols

# akshare 是否可用
try:
    import akshare as ak
    HAVE_AKSHARE = True
except Exception:
    ak = None
    HAVE_AKSHARE = False

# 模块级缓存：股票全量快照（用于搜索），60s 过期重拉
_stock_spot_cache = {"df": None, "ts": 0}
_fund_universe_cache = {"df": None, "ts": 0}
_cache_lock = threading.Lock()

SPOT_CACHE_TTL = 60          # 秒
FUND_UNIVERSE_TTL = 86400    # 24h

MARKET_START = time(9, 25)
MARKET_END = time(15, 5)


def is_trading_hours():
    """是否在 A 股交易时段（平日 09:25-15:05，按本地时间，建议服务器为 Asia/Shanghai）。"""
    now = datetime.now()
    if now.weekday() >= 5:          # 周六日
        return False
    t = now.time()
    return MARKET_START <= t <= MARKET_END


# ---------------------------------------------------------------------- akshare 调用封装
def _call_with_timeout(func, *args, timeout=15, **kwargs):
    """在独立线程执行 akshare 调用，超时返回 None。"""
    if not HAVE_AKSHARE:
        return None
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(func, *args, **kwargs)
        try:
            return fut.result(timeout=timeout)
        except (FTimeout, Exception):
            return None


def refresh_watchlist():
    """刷新自选股票/基金实时行情。失败则保留旧值并置 stale。"""
    from .db import get_session, Stock, Fund, Watchlist

    s = get_session()
    try:
        watch_stocks = {w.code for w in s.query(Watchlist).filter(Watchlist.kind == "stock").all()}
        watch_funds = {w.code for w in s.query(Watchlist).filter(Watchlist.kind == "fund").all()}
    finally:
        s.close()

    now = datetime.now()

    # ---- 股票 ----
    if watch_stocks:
        df = _call_with_timeout(ak.stock_zh_a_spot_em)
        if df is not None:
            df = akshare_cols.normalize_stock_spot(df)
            # 缓存全量快照供搜索用
            with _cache_lock:
                _stock_spot_cache["df"] = df
                _stock_spot_cache["ts"] = datetime.now().timestamp()
            sub = df[df["code"].isin(watch_stocks)] if "code" in df.columns else df.iloc[0:0]
            s = get_session()
            try:
                for _, r in sub.iterrows():
                    code = str(r.get("code", "")).zfill(6)
                    st = s.query(Stock).get(code)
                    if st is None:
                        st = Stock(code=code)
                        s.add(st)
                    _fill_stock(st, r, now, stale=False)
                s.commit()
            except Exception:
                s.rollback()
            finally:
                s.close()
        else:
            _mark_stale("stock", watch_stocks)

    # ---- 基金 ----
    if watch_funds:
        df = _call_with_timeout(ak.fund_value_estimation_em)
        if df is not None:
            df = akshare_cols.normalize_fund_est(df)
            sub = df[df["code"].isin(watch_funds)] if "code" in df.columns else df.iloc[0:0]
            s = get_session()
            try:
                for _, r in sub.iterrows():
                    code = str(r.get("code", "")).zfill(6)
                    fu = s.query(Fund).get(code)
                    if fu is None:
                        fu = Fund(code=code)
                        s.add(fu)
                    _fill_fund(fu, r, now, stale=False)
                s.commit()
            except Exception:
                s.rollback()
            finally:
                s.close()
        else:
            _mark_stale("fund", watch_funds)


def _fill_stock(st, r, now, stale):
    def g(key, default=None):
        v = r.get(key, default)
        return v if v is not None and str(v) != "nan" else default
    st.name = g("name", st.name)
    st.price = _to_dec(g("price"))
    st.pct_chg = _to_dec(g("pct_chg"))
    st.chg = _to_dec(g("chg"))
    st.open = _to_dec(g("open"))
    st.high = _to_dec(g("high"))
    st.low = _to_dec(g("low"))
    st.pre_close = _to_dec(g("pre_close"))
    st.volume = _to_dec(g("volume"))
    st.amount = _to_dec(g("amount"))
    st.turnover = _to_dec(g("turnover"))
    st.pe = _to_dec(g("pe"))
    st.pb = _to_dec(g("pb"))
    st.total_mv = _to_dec(g("total_mv"))
    st.circ_mv = _to_dec(g("circ_mv"))
    st.updated_at = now
    st.stale = stale


def _fill_fund(fu, r, now, stale):
    def g(key, default=None):
        v = r.get(key, default)
        return v if v is not None and str(v) != "nan" else default
    fu.name = g("name", fu.name)
    fu.unit_nav = _to_dec(g("unit_nav"), fu.unit_nav)
    fu.acc_nav = _to_dec(g("acc_nav"), fu.acc_nav)
    fu.est_nav = _to_dec(g("est_nav"), fu.unit_nav)
    fu.est_pct = _to_dec(g("est_pct"))
    fu.updated_at = now
    fu.stale = stale


def _to_dec(v, default=None):
    if v is None:
        return default
    try:
        return Decimal(str(v))
    except Exception:
        return default


def _mark_stale(kind, codes):
    """刷新失败时把对应缓存行标记 stale。"""
    from .db import get_session, Stock, Fund
    s = get_session()
    try:
        Model = Stock if kind == "stock" else Fund
        for code in codes:
            row = s.query(Model).get(code)
            if row:
                row.stale = True
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


# ---------------------------------------------------------------------- 近半年历史
def get_stock_history(code, force_refresh=False):
    """返回某股票近半年日线历史（缓存于 price_history）。"""
    from .db import get_session, PriceHistory
    _refresh_history_if_needed("stock", code, force_refresh)
    s = get_session()
    try:
        rows = s.query(PriceHistory).filter(
            PriceHistory.kind == "stock", PriceHistory.code == code
        ).order_by(PriceHistory.date.asc()).all()
        return [{"date": r.date.isoformat(), "close": float(r.close or 0),
                 "open": float(r.open or 0), "high": float(r.high or 0),
                 "low": float(r.low or 0), "volume": float(r.volume or 0)}
                for r in rows]
    finally:
        s.close()


def get_fund_history(code, force_refresh=False):
    """返回某基金近半年净值历史（缓存于 price_history）。"""
    from .db import get_session, PriceHistory
    _refresh_history_if_needed("fund", code, force_refresh)
    s = get_session()
    try:
        rows = s.query(PriceHistory).filter(
            PriceHistory.kind == "fund", PriceHistory.code == code
        ).order_by(PriceHistory.date.asc()).all()
        return [{"date": r.date.isoformat(), "unit_nav": float(r.close or 0),
                 "pct_chg": float(r.pct_chg or 0)} for r in rows]
    finally:
        s.close()


def _refresh_history_if_needed(kind, code, force_refresh=False):
    """按需拉取近半年历史。7 天内已刷新则跳过（除非 force）。"""
    from .db import get_session, PriceHistory
    s = get_session()
    try:
        # 取该 code 最新 refreshed_at
        any_row = s.query(PriceHistory).filter(
            PriceHistory.kind == kind, PriceHistory.code == code
        ).order_by(PriceHistory.refreshed_at.desc()).first()
        if any_row and not force_refresh:
            age = datetime.now() - (any_row.refreshed_at or datetime.min)
            if age < timedelta(days=7):
                return
        if not HAVE_AKSHARE:
            return  # 用 seed 数据
    finally:
        s.close()

    # 拉取
    if kind == "stock":
        df = _call_with_timeout(ak.stock_zh_a_hist, symbol=code, period="daily",
                                start_date=(date.today() - timedelta(days=190)).strftime("%Y%m%d"),
                                end_date=date.today().strftime("%Y%m%d"), adjust="qfq")
        if df is None or df.empty:
            return
        df = akshare_cols.normalize_stock_hist(df)
        _upsert_history("stock", code, df, is_fund=False)
    else:
        df = _call_with_timeout(ak.fund_open_fund_info_em, symbol=code, indicator="单位净值走势")
        if df is None or df.empty:
            return
        df = akshare_cols.normalize_fund_hist(df)
        _upsert_history("fund", code, df, is_fund=True)


def _upsert_history(kind, code, df, is_fund):
    """把 DataFrame 写入 price_history（覆盖该 code）。"""
    from .db import get_session, PriceHistory
    s = get_session()
    try:
        s.query(PriceHistory).filter(
            PriceHistory.kind == kind, PriceHistory.code == code
        ).delete()
        now = datetime.now()
        for _, r in df.iterrows():
            d = r.get("date")
            if hasattr(d, "date"):
                d = d.date()
            elif isinstance(d, str):
                try:
                    d = datetime.strptime(d, "%Y-%m-%d").date()
                except Exception:
                    continue
            if d is None:
                continue
            # 只保留近半年
            if (date.today() - d).days > 185:
                continue
            if is_fund:
                nav = r.get("unit_nav")
                pct = r.get("pct_chg")
                s.add(PriceHistory(kind=kind, code=code, date=d,
                                   open=_to_dec(nav), close=_to_dec(nav),
                                   high=_to_dec(nav), low=_to_dec(nav),
                                   volume=None, pct_chg=_to_dec(pct),
                                   refreshed_at=now))
            else:
                s.add(PriceHistory(kind=kind, code=code, date=d,
                                   open=_to_dec(r.get("open")), close=_to_dec(r.get("close")),
                                   high=_to_dec(r.get("high")), low=_to_dec(r.get("low")),
                                   volume=_to_dec(r.get("volume")), pct_chg=_to_dec(r.get("pct_chg")),
                                   refreshed_at=now))
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


# ---------------------------------------------------------------------- 搜索
def _refresh_stock_spot_async():
    """后台线程刷新全量股票快照缓存（非阻塞）。"""
    if not HAVE_AKSHARE:
        return
    with _cache_lock:
        age = datetime.now().timestamp() - _stock_spot_cache["ts"]
        if _stock_spot_cache["df"] is not None and age <= SPOT_CACHE_TTL:
            return  # 缓存仍有效
    fresh = _call_with_timeout(ak.stock_zh_a_spot_em, timeout=30)
    if fresh is not None:
        fresh = akshare_cols.normalize_stock_spot(fresh)
        with _cache_lock:
            _stock_spot_cache["df"] = fresh
            _stock_spot_cache["ts"] = datetime.now().timestamp()


def _refresh_fund_universe_async():
    """后台线程刷新基金名册缓存（非阻塞）。"""
    if not HAVE_AKSHARE:
        return
    with _cache_lock:
        age = datetime.now().timestamp() - _fund_universe_cache["ts"]
        if _fund_universe_cache["df"] is not None and age <= FUND_UNIVERSE_TTL:
            return
    fresh = _call_with_timeout(ak.fund_name_em, timeout=30)
    if fresh is not None:
        fresh = akshare_cols.normalize_fund_name(fresh)
        with _cache_lock:
            _fund_universe_cache["df"] = fresh
            _fund_universe_cache["ts"] = datetime.now().timestamp()


def search_stocks(q):
    """搜索股票：优先走全量快照缓存；缓存缺失时先返回本地结果并后台刷新。"""
    if not q:
        return []
    with _cache_lock:
        df = _stock_spot_cache["df"]
        age = datetime.now().timestamp() - _stock_spot_cache["ts"]
    if df is not None and age <= SPOT_CACHE_TTL:
        sub = df[df["name"].astype(str).str.contains(q, na=False) | df["code"].astype(str).str.contains(q, na=False)]
        out = []
        for _, r in sub.head(20).iterrows():
            out.append({"code": str(r.get("code", "")).zfill(6), "name": str(r.get("name", "")),
                        "price": float(r.get("price") or 0), "pct_chg": float(r.get("pct_chg") or 0)})
        return out
    # 缓存缺失：先返回本地自选结果，再后台异步刷新
    if df is None and HAVE_AKSHARE:
        threading.Thread(target=_refresh_stock_spot_async, daemon=True).start()
    return _search_local("stock", q)


def search_funds(q):
    """搜索基金：优先走基金名册缓存；缓存缺失时先返回本地结果并后台刷新。"""
    if not q:
        return []
    with _cache_lock:
        df = _fund_universe_cache["df"]
        age = datetime.now().timestamp() - _fund_universe_cache["ts"]
    if df is not None and age <= FUND_UNIVERSE_TTL:
        sub = df[df["name"].astype(str).str.contains(q, na=False) | df["code"].astype(str).str.contains(q, na=False)]
        out = []
        for _, r in sub.head(20).iterrows():
            out.append({"code": str(r.get("code", "")).zfill(6), "name": str(r.get("name", "")),
                        "type": str(r.get("type", ""))})
        return out
    # 缓存缺失：先返回本地结果，再后台异步刷新
    if df is None and HAVE_AKSHARE:
        threading.Thread(target=_refresh_fund_universe_async, daemon=True).start()
    return _search_local("fund", q)


def _search_local(kind, q):
    """akshare 不可用时，从本地自选缓存搜索。"""
    from .db import get_session, Stock, Fund
    s = get_session()
    try:
        if kind == "stock":
            rows = s.query(Stock).filter(
                Stock.name.like(f"%{q}%") | Stock.code.like(f"%{q}%")
            ).limit(20).all()
            return [{"code": r.code, "name": r.name,
                     "price": float(r.price or 0), "pct_chg": float(r.pct_chg or 0)} for r in rows]
        else:
            rows = s.query(Fund).filter(
                Fund.name.like(f"%{q}%") | Fund.code.like(f"%{q}%") | Fund.fund_type.like(f"%{q}%")
            ).limit(20).all()
            return [{"code": r.code, "name": r.name, "type": r.fund_type or ""} for r in rows]
    finally:
        s.close()


# ---------------------------------------------------------------------- 调度器
_scheduler = None


def refresh_watchlist_job():
    """APScheduler 周期任务：交易时段才刷新。"""
    try:
        if is_trading_hours():
            refresh_watchlist()
    except Exception as e:
        print(f"[sandbox] refresh_watchlist_job error: {e}")


def unfreeze_t1_job():
    """每日 15:05 解冻所有用户 T+1 冻结份额，并把基金赎回到账。"""
    from .db import get_session, Holding, Order
    s = get_session()
    try:
        for h in s.query(Holding).filter(Holding.frozen_shares > 0).all():
            h.available_shares += h.frozen_shares
            h.frozen_shares = 0
        # 把 pending/settling 的赎回单标 settled（现金已在下单时入账）
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def start_scheduler(app):
    """启动后台调度器（仅 reloader 主子进程）。"""
    global _scheduler
    if not (not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(refresh_watchlist_job, IntervalTrigger(minutes=1), id="refresh", max_instances=1)
    _scheduler.add_job(unfreeze_t1_job, CronTrigger(hour=15, minute=5), id="unfreeze", max_instances=1)
    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False) if _scheduler else None)
    app.logger.info("[sandbox] APScheduler 已启动")
