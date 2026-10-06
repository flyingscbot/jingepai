"""Download fixed historical OHLC windows for the offline risk education page.

Run from the repository root: python scripts/build_risk_history.py
Yahoo quote OHLC values use the provider's historical corporate-action basis;
we do not use adjusted-close to rescale individual candles.
"""
import datetime as dt
import json
import math
from pathlib import Path
import urllib.request


CASES = [
    {
        "id": "crrc-2015", "symbol": "601766.SS", "name": "中国中车", "label": "2015 · 合并前后的剧烈波动",
        "start": "2015-04-01", "end": "2015-07-11", "currency": "CNY",
        "description": "回放中国南车至中国中车期间的 A 股行情。观察上涨、跳空和急跌中自己的交易冲动。",
        "lesson": "合并题材与市场热度不能保证股价持续上涨。停牌、跳空及连续下跌，会使及时退出变得困难。",
        "eventSource": "https://www.hkexnews.hk/listedco/listconews/sehk/2015/0611/LTN20150611709_C.pdf",
        "eventSourceLabel": "中国中车交易异常波动公告 · 2015-06-11",
    },
    {
        "id": "gme-2021", "symbol": "GME", "name": "GameStop", "label": "2021 · 社交媒体热潮",
        "start": "2021-01-11", "end": "2021-02-13", "currency": "USD",
        "description": "回放 2021 年初的 GameStop 行情。价格快速变化时，关注自己是否会因为害怕错过而追涨。",
        "lesson": "社交媒体的热度不等于安全边际。剧烈波动期间，真实券商可能限制交易，你未必能随时买卖。",
        "eventSource": "https://www.sec.gov/files/staff-report-equity-options-market-struction-conditions-early-2021.pdf",
        "eventSourceLabel": "美国 SEC：2021 年初股票与期权市场结构报告",
    },
    {
        "id": "amc-2021", "symbol": "AMC", "name": "AMC 院线", "label": "2021 · 热门股狂潮",
        "start": "2021-05-17", "end": "2021-07-17", "currency": "USD",
        "description": "回放 AMC 在 2021 年初夏的行情。尝试感受热门股票的快速拉升与反复震荡。",
        "lesson": "热门股票也可能脱离基本面。AMC 当时公开提示极端价格波动风险；别把人气当作本金保障。",
        "eventSource": "https://investor.amctheatres.com/sec-filings/all-sec-filings/content/0001104659-21-074526/tm2117986d2_ex99-1.htm",
        "eventSourceLabel": "AMC 公司公告 · 2021-06-01",
    },
    {
        "id": "tsla-2020", "symbol": "TSLA", "name": "特斯拉", "label": "2020 · 疫情期间的剧烈波动",
        "start": "2020-02-03", "end": "2020-04-10", "currency": "USD",
        "description": "回放 2020 年 2—4 月的特斯拉行情。大幅震荡时，知名公司同样可能带来持仓压力。",
        "lesson": "知名公司也会经历剧烈回撤。反弹不能保证回到买入价，长期看好也不意味着短期风险较低。",
        "eventSource": "https://ir.tesla.com/_flysystem/s3/sec/000156459021004599/tsla-10k_20201231-gen.pdf",
        "eventSourceLabel": "特斯拉 2020 年年度报告",
    },
]


def epoch(date):
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp())


def download(case):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{case['symbol']}"
           f"?period1={epoch(case['start'])}&period2={epoch(case['end'])}&interval=1d")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = json.load(response)["chart"]["result"][0]
    quote = raw["indicators"]["quote"][0]
    candles = []
    for index, timestamp in enumerate(raw["timestamp"]):
        values = [quote[key][index] for key in ("open", "high", "low", "close")]
        volume = quote["volume"][index]
        if volume is None or volume <= 0:
            continue  # Yahoo may pad suspension dates with the last price and zero volume.
        if any(value is None for value in values):
            continue  # No synthetic candles for suspension/non-trading days.
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError(f"Invalid price in {case['symbol']}")
        opening, high, low, close = values
        if not low <= min(opening, close) <= max(opening, close) <= high:
            raise ValueError(f"Invalid OHLC in {case['symbol']}")
        date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()
        candles.append({"date": date, "open": opening, "high": high, "low": low, "close": close, "volume": volume})
    if len(candles) < 10:
        raise ValueError(f"Insufficient data for {case['symbol']}")
    return {**case, "candles": candles, "dataSource": url,
            "historySource": f"https://finance.yahoo.com/quote/{case['symbol']}/history/"}


if __name__ == "__main__":
    cases = [download(case) for case in CASES]
    payload = {"version": 1, "retrievedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
               "provider": "Yahoo Finance", "cases": cases}
    output = Path(__file__).resolve().parents[1] / "static/home/js/risk_history_data.js"
    output.write_text("// Historical daily OHLC snapshot; rebuild with scripts/build_risk_history.py.\n"
                      + "window.RISK_HISTORY = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
                      encoding="utf-8")
    for case in cases:
        print(f"{case['symbol']}: {len(case['candles'])} candles, "
              f"{case['candles'][0]['date']} to {case['candles'][-1]['date']}")
