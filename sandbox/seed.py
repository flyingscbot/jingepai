"""精选自选 + 真实/合成 mock 数据，保证断网/akshare 失败时仍有 1000+ 标的可浏览。

init_db 时若 watchlist 为空则灌入。
若 _real_stocks.csv / _real_funds.csv 存在则使用真实 akshare 数据，否则合成。
"""
import os
import random
from datetime import datetime, date, timedelta
from decimal import Decimal

from .db import (
    get_session, Stock, Fund, PriceHistory, Watchlist,
)

_REAL_STOCKS_CSV = os.path.join(os.path.dirname(__file__), "_real_stocks.csv")
_REAL_FUNDS_CSV = os.path.join(os.path.dirname(__file__), "_real_funds.csv")

# 目标标的数量
TARGET_STOCKS = 1000
TARGET_FUNDS = 1000

# ---------------------------------------------------------------------- 名称生成组件
_STOCK_PRE = ["中国","华","新","大","东方","中","天","海","金","万","百","恒","隆","创","宏","泰","安","信","德","正",
              "明","光","远","通","达","联","同","汇","聚","嘉","瑞","威","朗","昌","盛","兴","宝","福","利","盈"]
_STOCK_IND = ["科技","电子","医药","能源","环保","通讯","电气","机械","化工","材料","信息","生物","新材","智能",
              "光电","半导体","新能源","电力","重工","轻工","自动化","软件","网络","数据","通信","航天","航空","装备","矿业"]
_STOCK_SUF = ["股份","集团","控股","实业","发展","科技","电子","医药","能源","环保","信息","新材","智能","装备"]

_FUND_CO = ["华夏","易方达","南方","广发","招商","嘉实","博时","富国","汇添富","鹏华","工银","建信","兴全","银银",
            "交银","华安","国泰","华宝","长信","中欧","景顺","诺安","前海","长安","浦银","万家","中信","平安","大成",
            "银华","东方红","国寿","中加","安信","财通","华泰","申万","长城","融通"]
_FUND_KW = ["优势","精选","成长","价值","稳健","策略","蓝筹","红利","消费","医药","科技","新能源","信息","制造",
            "创新","主题","行业","配置","平衡","回报","机遇","动力","前沿","核心","优质","国企","ESG","养老","量化"]
_FUND_TYPE_POOL = ["混合型","混合型","混合型","混合型","股票型","股票型","股票型",
                   "指数型","指数型","指数型","指数型","债券型","债券型","QDII","FOF"]

# 代码范围
_STOCK_RANGES = [(600000,603999),(1,999),(2001,2999),(300001,300999),(688001,688999)]


def _gen_stock_codes(existing, count):
    """生成不与 existing 冲突的股票代码列表。"""
    codes = []
    tried = set(existing)
    for start, end in _STOCK_RANGES:
        for code in range(start, end + 1):
            s = str(code).zfill(6)
            if s not in tried:
                tried.add(s)
                codes.append(s)
                if len(codes) >= count:
                    return codes
    return codes


def _gen_fund_codes(existing, count):
    """生成不与 existing 冲突的基金代码列表（6 位，000001-999999 区间随机抽取）。"""
    codes = []
    tried = set(existing)
    rng = random.Random(137)
    # 从大区间随机采样，避免遍历全部
    while len(codes) < count:
        code = rng.randint(1, 999999)
        s = str(code).zfill(6)
        if s not in tried:
            tried.add(s)
            codes.append(s)
    return codes


def _gen_stock_name(rng):
    return rng.choice(_STOCK_PRE) + rng.choice(_STOCK_IND) + rng.choice(_STOCK_SUF)


def _gen_fund_name(rng):
    name = rng.choice(_FUND_CO) + rng.choice(_FUND_KW)
    # 50% 概率加 A/C 后缀
    if rng.random() < 0.4:
        name += rng.choice(["A", "C"])
    elif rng.random() < 0.2:
        name += "ETF"
    return name

# 精选股票（代码, 名称, 基准价, 行业）
SEED_STOCKS = [
    # ---- 白酒/消费 ----
    ("600519", "贵州茅台", 1680.00),
    ("000858", "五粮液", 152.30),
    ("000568", "泸州老窖", 218.50),
    ("600809", "山西汾酒", 285.60),
    ("000596", "古井贡酒", 268.40),
    ("600887", "伊利股份", 28.90),
    ("603288", "海天味业", 82.30),
    ("600690", "海尔智家", 25.60),
    # ---- 银行/金融 ----
    ("000001", "平安银行", 11.20),
    ("600036", "招商银行", 35.80),
    ("601398", "工商银行", 5.20),
    ("601288", "农业银行", 3.65),
    ("601939", "建设银行", 7.80),
    ("600000", "浦发银行", 8.45),
    ("601318", "中国平安", 48.50),
    ("601628", "中国人寿", 38.20),
    # ---- 科技/半导体 ----
    ("002594", "比亚迪", 245.00),
    ("000333", "美的集团", 62.40),
    ("600745", "闻泰科技", 68.50),
    ("603501", "韦尔股份", 128.30),
    ("002475", "立讯精密", 38.60),
    ("300750", "宁德时代", 218.40),
    ("300059", "东方财富", 15.80),
    ("002230", "科大讯飞", 52.30),
    # ---- 医药/医疗 ----
    ("600276", "恒瑞医药", 45.60),
    ("300015", "爱尔眼科", 28.50),
    ("600196", "复星医药", 32.80),
    ("000538", "云南白药", 58.40),
    ("603259", "药明康德", 68.90),
    # ---- 能源/资源 ----
    ("600900", "长江电力", 25.30),
    ("601857", "中国石油", 8.35),
    ("600028", "中国石化", 6.80),
    ("601088", "中国神华", 32.50),
    ("601899", "紫金矿业", 15.60),
    ("600547", "山东黄金", 28.40),
    # ---- 地产/基建 ----
    ("000002", "万科A", 10.80),
    ("600048", "保利发展", 12.50),
    ("601668", "中国建筑", 5.60),
    ("600585", "海螺水泥", 28.90),
    # ---- 汽车/新能源 ----
    ("600104", "上汽集团", 15.80),
    ("601127", "赛力斯", 85.60),
    ("002460", "赣锋锂业", 42.30),
    ("002466", "天齐锂业", 38.50),
    # ---- 通信/互联网 ----
    ("600050", "中国联通", 5.20),
    ("600941", "中国移动", 98.50),
    ("000063", "中兴通讯", 32.40),
    # ---- 化工/材料 ----
    ("600309", "万华化学", 78.50),
    ("600346", "恒力石化", 28.60),
    # ---- 传媒/游戏 ----
    ("002415", "海康威视", 32.80),
    ("300027", "华谊兄弟", 2.85),
]

# 精选基金（代码, 名称, 基准净值, 类型）
SEED_FUNDS = [
    # ---- 混合型 ----
    ("000001", "华夏成长", 1.0210, "混合型"),
    ("110011", "易方达中小盘", 3.8520, "混合型"),
    ("005827", "易方达蓝筹精选", 2.0150, "混合型"),
    ("001102", "前海开源国家比较优势", 1.4320, "混合型"),
    ("519674", "银河创新成长", 1.8760, "混合型"),
    ("000478", "华安策略优选", 2.3450, "混合型"),
    ("001838", "国泰金鑫", 1.6780, "混合型"),
    ("519066", "汇添富蓝筹稳健", 1.4560, "混合型"),
    ("001513", "易方达信息产业", 1.8920, "混合型"),
    # ---- 股票型 ----
    ("000209", "信澳新能源产业", 2.3450, "股票型"),
    ("000577", "安信价值精选", 2.1230, "股票型"),
    ("008888", "华夏国证半导体芯片", 1.2310, "股票型"),
    # ---- 指数型 ----
    ("161725", "招商中证白酒", 1.0820, "指数型"),
    ("110003", "易方达50指数", 1.5230, "指数型"),
    ("001180", "广发医药卫生", 1.3450, "指数型"),
    ("160706", "嘉实沪深300", 1.2340, "指数型"),
    ("510300", "华泰柏瑞沪深300ETF", 4.0120, "指数型"),
    ("159915", "易方达创业板ETF", 2.5670, "指数型"),
    ("512880", "证券ETF", 1.0890, "指数型"),
    ("512760", "半导体50ETF", 1.4560, "指数型"),
    ("515030", "新能源车ETF", 1.2340, "指数型"),
    ("159992", "医疗ETF", 0.9870, "指数型"),
    ("161031", "富国中证红利", 1.3450, "指数型"),
    # ---- 债券型 ----
    ("000032", "易方达稳健收益A", 1.2890, "债券型"),
    ("003838", "广发安泽短债A", 1.0560, "债券型"),
    ("000914", "中加纯债一年A", 1.0340, "债券型"),
    ("006327", "鹏华尊享一年", 1.0450, "债券型"),
    # ---- QDII ----
    ("270042", "广发纳斯达克100", 1.9540, "QDII"),
    ("000834", "富国中国中小盘", 1.6780, "QDII"),
    ("164906", "交银中证海外中国互联网", 1.2340, "QDII"),
    ("006282", "华夏港股通精选", 1.1230, "QDII"),
    # ---- FOF ----
    ("005156", "南方全天候策略", 1.0670, "FOF"),
    ("006281", "华夏聚惠稳健", 1.0450, "FOF"),
]


def _random_walk(start_price, days, volatility=0.02, drift=0.0005):
    """生成 days 天的随机游走收盘价序列，返回 [(date, open, close, high, low), ...]。"""
    rng = random.Random(hash_seed(start_price))
    rows = []
    price = float(start_price)
    today = date.today()
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        # 跳过周末，使走势更连续
        if d.weekday() >= 5:
            continue
        change = rng.gauss(drift, volatility)
        new_price = max(0.01, price * (1 + change))
        open_ = price
        close = new_price
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.005)))
        rows.append((d, round(open_, 4), round(close, 4), round(high, 4), round(low, 4)))
        price = new_price
    return rows


def hash_seed(start_price):
    """根据基准价生成稳定随机种子，使每次 seed 数据可复现。"""
    return int(str(start_price).replace(".", "")) % 100000 + 7


def _seed_one_stock(s, code, name, base_price):
    # 6 个月约 120 个交易日
    rows = _random_walk(base_price, 180, volatility=0.018, drift=0.0004)
    last_close = rows[-1][2] if rows else base_price
    prev_close = rows[-2][2] if len(rows) >= 2 else last_close
    pct = round((last_close - prev_close) / prev_close * 100, 4) if prev_close else 0
    stock = Stock(
        code=code, name=name, price=Decimal(str(last_close)),
        pct_chg=Decimal(str(pct)), chg=Decimal(str(round(last_close - prev_close, 4))),
        open=Decimal(str(rows[-1][1])), high=Decimal(str(rows[-1][3])),
        low=Decimal(str(rows[-1][4])), pre_close=Decimal(str(prev_close)),
        volume=Decimal(str(random.randint(50000, 5000000))),
        amount=Decimal(str(random.randint(10000000, 500000000))),
        turnover=Decimal(str(round(random.uniform(0.2, 5.0), 4))),
        pe=Decimal(str(round(random.uniform(8, 60), 4))),
        pb=Decimal(str(round(random.uniform(0.5, 8), 4))),
        total_mv=Decimal(str(round(last_close * random.uniform(1e8, 1e10), 2))),
        circ_mv=Decimal(str(round(last_close * random.uniform(1e8, 8e9), 2))),
        updated_at=datetime.now(), stale=True,
    )
    s.add(stock)
    for d, o, c, h, l in rows:
        s.add(PriceHistory(kind="stock", code=code, date=d,
                           open=Decimal(str(o)), close=Decimal(str(c)),
                           high=Decimal(str(h)), low=Decimal(str(l)),
                           volume=Decimal(str(random.randint(50000, 5000000))),
                           pct_chg=Decimal("0")))
    s.add(Watchlist(kind="stock", code=code, name=name, added_by="system"))


def _seed_one_fund(s, code, name, base_nav, fund_type="混合型"):
    rows = _random_walk(base_nav, 180, volatility=0.012, drift=0.0003)
    last_nav = rows[-1][2] if rows else base_nav
    prev_nav = rows[-2][2] if len(rows) >= 2 else last_nav
    pct = round((last_nav - prev_nav) / prev_nav * 100, 4) if prev_nav else 0
    acc_nav = round(last_nav * 1.2, 4)  # 累计净值示意
    fund = Fund(
        code=code, name=name, unit_nav=Decimal(str(last_nav)),
        acc_nav=Decimal(str(acc_nav)), est_nav=Decimal(str(last_nav)),
        est_pct=Decimal(str(pct)), fund_type=fund_type,
        nav_date=date.today(), updated_at=datetime.now(), stale=True,
    )
    s.add(fund)
    for d, o, c, h, l in rows:
        s.add(PriceHistory(kind="fund", code=code, date=d,
                           open=Decimal(str(c)), close=Decimal(str(c)),
                           high=Decimal(str(c)), low=Decimal(str(c)),
                           volume=None, pct_chg=Decimal("0")))
    s.add(Watchlist(kind="fund", code=code, name=name, added_by="system"))


def _generate_bulk_stocks(s, existing_codes, target):
    """批量灌入股票至 target 总数：优先用真实 CSV，否则合成。"""
    need = target - len(existing_codes)
    if need <= 0:
        return
    rng = random.Random(2024)
    now = datetime.now()

    # 尝试读取真实数据
    real_rows = []
    if os.path.exists(_REAL_STOCKS_CSV):
        import csv as _csv
        with open(_REAL_STOCKS_CSV, encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                raw_code = row.get("代码", "")
                # 去掉交易所前缀：sh600519 → 600519, sz000001 → 000001
                code = raw_code[2:] if len(raw_code) == 8 else raw_code
                if code in existing_codes:
                    continue
                try:
                    price = float(row.get("最新价") or 0)
                except (ValueError, TypeError):
                    continue
                if price <= 0:
                    continue
                real_rows.append({
                    "code": code, "name": row.get("名称", code),
                    "price": price,
                    "pct_chg": float(row.get("涨跌幅") or 0),
                    "chg": float(row.get("涨跌额") or 0),
                    "open": float(row.get("今开") or price),
                    "high": float(row.get("最高") or price),
                    "low": float(row.get("最低") or price),
                    "pre_close": float(row.get("昨收") or price),
                    "volume": float(row.get("成交量") or 0),
                    "amount": float(row.get("成交额") or 0),
                })
                existing_codes.add(code)
                if len(real_rows) >= need:
                    break
        print(f"[seed] 从真实 CSV 加载 {len(real_rows)} 只股票")

    # 不足部分用合成数据补
    if len(real_rows) < need:
        synth_codes = _gen_stock_codes(existing_codes, need - len(real_rows))
        for code in synth_codes:
            base = round(rng.uniform(2, 300), 2)
            real_rows.append({
                "code": code, "name": _gen_stock_name(rng),
                "price": base, "pct_chg": round(rng.uniform(-5, 5), 4),
                "chg": 0, "open": base, "high": base * 1.02, "low": base * 0.98,
                "pre_close": base, "volume": rng.randint(50000, 5000000),
                "amount": rng.randint(10000000, 500000000),
            })
        print(f"[seed] 合成补充 {len(synth_codes)} 只股票")

    stock_maps = []
    history_maps = []
    watchlist_maps = []

    for r in real_rows:
        code = r["code"]
        price = r["price"]
        # 用真实价格作为基准，生成半年随机走势
        rows = _random_walk(price, 180, volatility=0.018, drift=0.0004)
        # 确保最后一天 = 真实现价
        if rows:
            rows[-1] = (rows[-1][0], rows[-1][1], price, rows[-1][3], rows[-1][4])

        stock_maps.append({
            "code": code, "name": r["name"],
            "price": Decimal(str(price)),
            "pct_chg": Decimal(str(r["pct_chg"])),
            "chg": Decimal(str(r["chg"])),
            "open": Decimal(str(r["open"])),
            "high": Decimal(str(r["high"])),
            "low": Decimal(str(r["low"])),
            "pre_close": Decimal(str(r["pre_close"])),
            "volume": Decimal(str(r["volume"])),
            "amount": Decimal(str(r["amount"])),
            "turnover": Decimal(str(round(rng.uniform(0.2, 5.0), 4))),
            "pe": Decimal(str(round(rng.uniform(8, 60), 4))),
            "pb": Decimal(str(round(rng.uniform(0.5, 8), 4))),
            "total_mv": Decimal(str(round(price * rng.uniform(1e8, 1e10), 2))),
            "circ_mv": Decimal(str(round(price * rng.uniform(1e8, 8e9), 2))),
            "updated_at": now, "stale": False,
        })
        for d, o, c, h, l in rows:
            history_maps.append({
                "kind": "stock", "code": code, "date": d,
                "open": Decimal(str(o)), "close": Decimal(str(c)),
                "high": Decimal(str(h)), "low": Decimal(str(l)),
                "volume": Decimal(str(rng.randint(50000, 5000000))),
                "pct_chg": Decimal("0"), "refreshed_at": now,
            })
        watchlist_maps.append({"kind": "stock", "code": code, "name": r["name"], "added_by": "system"})

    BATCH = 500
    for i in range(0, len(stock_maps), BATCH):
        s.bulk_insert_mappings(Stock, stock_maps[i:i + BATCH])
        s.bulk_insert_mappings(Watchlist, watchlist_maps[i:i + BATCH])
    for i in range(0, len(history_maps), BATCH):
        s.bulk_insert_mappings(PriceHistory, history_maps[i:i + BATCH])
    print(f"[seed] 已写入 {len(real_rows)} 只股票（含 {len(history_maps)} 条历史）")


def _generate_bulk_funds(s, existing_codes, target):
    """批量灌入基金至 target 总数：优先用真实 CSV，否则合成。"""
    need = target - len(existing_codes)
    if need <= 0:
        return
    rng = random.Random(5678)
    now = datetime.now()
    today = date.today()

    # 尝试读取真实基金名册
    real_rows = []
    if os.path.exists(_REAL_FUNDS_CSV):
        import csv as _csv
        with open(_REAL_FUNDS_CSV, encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                code = row.get("基金代码", "").strip()
                if not code or code in existing_codes:
                    continue
                name = row.get("基金简称", code)
                # 简化基金类型：混合型-灵活 → 混合型
                raw_type = row.get("基金类型", "")
                ftype = raw_type.split("-")[0].strip() if raw_type else "混合型"
                real_rows.append({"code": code, "name": name, "fund_type": ftype})
                existing_codes.add(code)
                if len(real_rows) >= need:
                    break
        print(f"[seed] 从真实 CSV 加载 {len(real_rows)} 只基金")

    # 不足部分用合成数据补
    if len(real_rows) < need:
        synth_codes = _gen_fund_codes(existing_codes, need - len(real_rows))
        for code in synth_codes:
            real_rows.append({
                "code": code, "name": _gen_fund_name(rng),
                "fund_type": rng.choice(_FUND_TYPE_POOL),
            })
        print(f"[seed] 合成补充 {len(synth_codes)} 只基金")

    fund_maps = []
    history_maps = []
    watchlist_maps = []

    for r in real_rows:
        code = r["code"]
        base = round(rng.uniform(0.5, 6.0), 4)
        rows = _random_walk(base, 180, volatility=0.012, drift=0.0003)
        last_nav = rows[-1][2] if rows else base
        prev_nav = rows[-2][2] if len(rows) >= 2 else last_nav
        pct = round((last_nav - prev_nav) / prev_nav * 100, 4) if prev_nav else 0
        acc_nav = round(last_nav * 1.2, 4)

        fund_maps.append({
            "code": code, "name": r["name"],
            "unit_nav": Decimal(str(last_nav)),
            "acc_nav": Decimal(str(acc_nav)),
            "est_nav": Decimal(str(last_nav)),
            "est_pct": Decimal(str(pct)),
            "fund_type": r["fund_type"], "nav_date": today,
            "updated_at": now, "stale": False,
        })
        for d, o, c, h, l in rows:
            history_maps.append({
                "kind": "fund", "code": code, "date": d,
                "open": Decimal(str(c)), "close": Decimal(str(c)),
                "high": Decimal(str(c)), "low": Decimal(str(c)),
                "volume": None, "pct_chg": Decimal("0"),
                "refreshed_at": now,
            })
        watchlist_maps.append({"kind": "fund", "code": code, "name": r["name"], "added_by": "system"})

    BATCH = 500
    for i in range(0, len(fund_maps), BATCH):
        s.bulk_insert_mappings(Fund, fund_maps[i:i + BATCH])
        s.bulk_insert_mappings(Watchlist, watchlist_maps[i:i + BATCH])
    for i in range(0, len(history_maps), BATCH):
        s.bulk_insert_mappings(PriceHistory, history_maps[i:i + BATCH])
    print(f"[seed] 已写入 {len(real_rows)} 只基金（含 {len(history_maps)} 条历史）")


def ensure_seed(force=False):
    """灌入种子数据：先精选(完整历史)，再批量合成至 1000+。force=True 时强制重灌。"""
    s = get_session()
    try:
        if not force and s.query(Watchlist).count() > 0:
            return
        if force:
            s.query(Watchlist).delete()
            s.query(Stock).delete()
            s.query(Fund).delete()
            s.query(PriceHistory).delete()
            s.commit()

        # 1) 精选股票/基金（ORM 逐条，含完整半年历史）
        existing_stock_codes = set()
        existing_fund_codes = set()
        for code, name, base in SEED_STOCKS:
            _seed_one_stock(s, code, name, base)
            existing_stock_codes.add(code)
        for code, name, base, ftype in SEED_FUNDS:
            _seed_one_fund(s, code, name, base, ftype)
            existing_fund_codes.add(code)
        s.flush()

        # 2) 批量合成至 1000+
        _generate_bulk_stocks(s, existing_stock_codes, TARGET_STOCKS)
        _generate_bulk_funds(s, existing_fund_codes, TARGET_FUNDS)

        s.commit()
        real_tag = "真实" if (os.path.exists(_REAL_STOCKS_CSV) or os.path.exists(_REAL_FUNDS_CSV)) else "合成"
        print(f"[seed] 播种完成（{real_tag}数据）：{s.query(Stock).count()} 股票 + {s.query(Fund).count()} 基金")
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
