"""akshare 返回的 DataFrame 列名归一化映射。

akshare 版本间列名（中文）会漂移，统一按小写键映射到英文内部字段。
所有映射函数：传入 DataFrame，返回列名归一化后的 DataFrame（原地重命名）。
"""

# 股票实时行情 stock_zh_a_spot_em -> 内部字段
STOCK_SPOT_MAP = {
    "代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "pct_chg",
    "涨跌额": "chg", "成交量": "volume", "成交额": "amount", "最高": "high",
    "最低": "low", "今开": "open", "昨收": "pre_close", "换手率": "turnover",
    "市盈率-动态": "pe", "市净率": "pb", "总市值": "total_mv", "流通市值": "circ_mv",
}

# 股票日线 stock_zh_a_hist -> 内部字段
STOCK_HIST_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
    "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_chg", "涨跌额": "chg",
    "换手率": "turnover", "股票代码": "code",
}

# 基金全宇宙 fund_name_em -> 内部字段
FUND_NAME_MAP = {
    "基金代码": "code", "拼音缩写": "abbr", "基金简称": "name",
    "基金类型": "type", "拼音全称": "pinyin",
}

# 基金净值历史 fund_open_fund_info_em -> 内部字段
FUND_HIST_MAP = {
    "净值日期": "date", "单位净值": "unit_nav", "日增长率": "pct_chg",
    "累计净值": "acc_nav",
}

# 盘中基金估值 fund_value_estimation_em -> 内部字段
FUND_EST_MAP = {
    "基金代码": "code", "基金简称": "name", "日期": "date",
    "估算值": "est_nav", "估算净值": "est_nav", "估算增长率": "est_pct",
    "累计净值": "acc_nav", "单位净值": "unit_nav",
}


def _normalize(df, mapping):
    """按映射把中文列名重命名为英文（不区分大小写匹配中文键）。"""
    if df is None or df.empty:
        return df
    rename = {}
    cols_lower = {str(c): c for c in df.columns}
    for cn, en in mapping.items():
        if cn in cols_lower:
            rename[cn] = en
    df = df.rename(columns=rename)
    return df


def normalize_stock_spot(df):
    return _normalize(df, STOCK_SPOT_MAP)


def normalize_stock_hist(df):
    return _normalize(df, STOCK_HIST_MAP)


def normalize_fund_name(df):
    return _normalize(df, FUND_NAME_MAP)


def normalize_fund_hist(df):
    return _normalize(df, FUND_HIST_MAP)


def normalize_fund_est(df):
    return _normalize(df, FUND_EST_MAP)
