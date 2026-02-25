"""
股票代码解析器 - 支持公司名(中英文) → 标准代码
用法:
  resolve_symbol("美团")     -> "3690.HK"
  resolve_symbol("Meituan")  -> "3690.HK"
  resolve_symbol("NVDA")     -> "NVDA"  (已经是代码，直接返回)
  resolve_symbol("英伟达")   -> "NVDA"
"""

import logging
import re
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ================================================================
# 公司名 → 代码 映射表 (中英文别名)
# 覆盖 config.yaml 里的所有股票 + 常见别名
# ================================================================
ALIAS_MAP: dict[str, str] = {
    # ---- 美股 AI/芯片 ----
    "nvidia": "NVDA", "英伟达": "NVDA", "老黄": "NVDA",
    "amd": "AMD", "超微": "AMD",
    "intel": "INTC", "英特尔": "INTC",
    "broadcom": "AVGO", "博通": "AVGO",
    "qualcomm": "QCOM", "高通": "QCOM",
    "marvell": "MRVL",
    "asml": "ASML", "阿斯麦": "ASML",
    "tsmc": "TSM", "台积电": "TSM",
    "arm": "ARM",
    "micron": "MU", "美光": "MU",

    # ---- 美股 云/软件 ----
    "microsoft": "MSFT", "微软": "MSFT",
    "amazon": "AMZN", "亚马逊": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "谷歌": "GOOGL",
    "oracle": "ORCL", "甲骨文": "ORCL",
    "ibm": "IBM",
    "salesforce": "CRM",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "c3.ai": "AI", "c3ai": "AI",
    "uipath": "PATH",
    "mongodb": "MDB",
    "datadog": "DDOG",
    "cloudflare": "NET",

    # ---- 美股 社交/广告 ----
    "meta": "META", "facebook": "META", "脸书": "META",
    "snap": "SNAP", "snapchat": "SNAP",
    "pinterest": "PINS",
    "reddit": "RDDT",

    # ---- 美股 EV ----
    "tesla": "TSLA", "特斯拉": "TSLA",
    "rivian": "RIVN",
    "lucid": "LCID",
    "nio": "NIO", "蔚来": "NIO",
    "xpeng": "XPEV", "小鹏": "XPEV",
    "li auto": "LI", "理想": "LI", "理想汽车": "LI", "lixiang": "LI",

    # ---- 美股 半导体设备 ----
    "lam research": "LRCX", "拉姆研究": "LRCX",
    "applied materials": "AMAT", "应用材料": "AMAT",
    "kla": "KLAC",
    "teradyne": "TER",
    "synopsys": "SNPS", "新思科技": "SNPS",
    "cadence": "CDNS",

    # ---- 美股 金融科技 ----
    "visa": "V",
    "mastercard": "MA", "万事达": "MA",
    "paypal": "PYPL", "贝宝": "PYPL",
    "block": "SQ", "square": "SQ",
    "affirm": "AFRM",
    "sofi": "SOFI",
    "coinbase": "COIN",

    # ---- 美股 生物医药 ----
    "eli lilly": "LLY", "礼来": "LLY",
    "novo nordisk": "NVO", "诺和诺德": "NVO",
    "abbvie": "ABBV", "艾伯维": "ABBV",
    "merck": "MRK", "默沙东": "MRK",
    "pfizer": "PFE", "辉瑞": "PFE",
    "amgen": "AMGN", "安进": "AMGN",
    "gilead": "GILD", "吉利德": "GILD",
    "regeneron": "REGN", "再生元": "REGN",
    "vertex": "VRTX",

    # ---- 美股 消费电子 ----
    "apple": "AAPL", "苹果": "AAPL",
    "dell": "DELL", "戴尔": "DELL",

    # ---- 美股 其他 ----
    "uber": "UBER", "优步": "UBER",
    "joby": "JOBY", "joby aviation": "JOBY",

    # ---- 港股 互联网 ----
    "tencent": "0700.HK", "腾讯": "0700.HK",
    "alibaba": "9988.HK", "阿里巴巴": "9988.HK", "阿里": "9988.HK",
    "meituan": "3690.HK", "美团": "3690.HK",
    "jd": "9618.HK", "jd.com": "9618.HK", "京东": "9618.HK",
    "kuaishou": "1024.HK", "快手": "1024.HK",
    "bilibili": "9626.HK", "b站": "9626.HK", "哔哩哔哩": "9626.HK",

    # ---- 港股 AI/硬件 ----
    "sensetime": "0020.HK", "商汤": "0020.HK",
    "smic": "0981.HK", "中芯国际": "0981.HK",
    "xiaomi": "1810.HK", "小米": "1810.HK",
    "sunny optical": "2382.HK", "舜宇光学": "2382.HK",
    "kingdee": "0268.HK", "金蝶": "0268.HK",

    # ---- 港股 EV ----
    "xpeng hk": "9868.HK",
    "li auto hk": "2015.HK",
    "geely": "0175.HK", "吉利": "0175.HK", "吉利汽车": "0175.HK",
    "nio hk": "9866.HK",
    "byd hk": "1211.HK",

    # ---- 港股 金融 ----
    "hsbc": "0005.HK", "汇丰": "0005.HK",
    "icbc": "1398.HK", "工商银行": "1398.HK",
    "boc": "3988.HK", "中国银行": "3988.HK",
    "hkex": "0388.HK", "港交所": "0388.HK",
    "ping an": "2318.HK", "平安": "2318.HK", "中国平安": "2318.HK",
    "aia": "1299.HK", "友邦": "1299.HK",

    # ---- 港股 医药 ----
    "sino biopharm": "1177.HK", "中国生物制药": "1177.HK",
    "wuxi biologics": "2269.HK", "药明生物": "2269.HK",
    "wuxi apptec hk": "2359.HK", "药明康德hk": "2359.HK",

    # ---- A股 AI ----
    "科大讯飞": "002230.SZ", "iflytek": "002230.SZ",
    "寒武纪": "688256.SH", "cambricon": "688256.SH",
    "中科曙光": "603019.SH", "sugon": "603019.SH",
    "景嘉微": "300474.SZ",
    "海光信息": "688041.SH",

    # ---- A股 半导体 ----
    "中芯国际a": "688981.SH",
    "北方华创": "002371.SZ", "naura": "002371.SZ",
    "韦尔股份": "603501.SH",
    "中微公司": "688012.SH",

    # ---- A股 EV ----
    "宁德时代": "300750.SZ", "catl": "300750.SZ",
    "比亚迪": "002594.SZ", "byd": "002594.SZ",
    "赣锋锂业": "002460.SZ", "ganfeng": "002460.SZ",

    # ---- A股 医药 ----
    "恒瑞医药": "600276.SH", "hengrui": "600276.SH",
    "云南白药": "000538.SZ",
    "迈瑞医疗": "300760.SZ", "mindray": "300760.SZ",
}


def resolve_symbol(input_str: str, config_path: str = "config/config.yaml") -> str:
    """
    将用户输入解析为标准股票代码

    解析顺序:
    1. 已经是标准代码格式 (全大写/含.HK/.SH/.SZ) → 直接返回
    2. 在 ALIAS_MAP 中匹配 (大小写不敏感)
    3. 在 config.yaml 的 industry_mapping 中搜索
    4. 尝试 yfinance 查找
    5. 返回原始输入 (大写)
    """
    raw = input_str.strip()
    if not raw:
        return raw

    # 1. 已经是标准代码格式
    if _looks_like_ticker(raw):
        return raw.upper() if not any(c == "." for c in raw) else raw

    # 2. 别名查找 (大小写不敏感)
    lower = raw.lower()
    if lower in ALIAS_MAP:
        resolved = ALIAS_MAP[lower]
        logger.info(f"符号解析: '{raw}' → {resolved} (别名匹配)")
        return resolved

    # 3. 在 config 的行业映射中搜索公司名
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        mapping = config.get("industry_mapping", {})
        for _key, info in mapping.items():
            industry_name = info.get("name", "")
            if lower in industry_name.lower():
                symbols = info.get("symbols", [])
                if symbols:
                    logger.info(f"符号解析: '{raw}' → 行业 '{industry_name}' 首个: {symbols[0]}")
                    return symbols[0]
    except Exception:
        pass

    # 4. 尝试 yfinance 搜索
    match = _yfinance_search(raw)
    if match:
        logger.info(f"符号解析: '{raw}' → {match} (yfinance 搜索)")
        return match

    # 5. 回退: 大写返回
    upper = raw.upper()
    logger.warning(f"符号解析: '{raw}' 未找到匹配，原样返回 '{upper}'")
    return upper


def _looks_like_ticker(s: str) -> bool:
    """判断是否已经是标准代码格式"""
    # 港股: 0700.HK / A股: 002230.SZ, 600276.SH
    if re.match(r"^\d{4,6}\.(HK|SH|SZ)$", s, re.IGNORECASE):
        return True
    # 美股: 1-5个大写字母
    if re.match(r"^[A-Z]{1,5}$", s):
        return True
    return False


def _yfinance_search(query: str) -> Optional[str]:
    """通过 yfinance 搜索公司名"""
    try:
        import yfinance as yf
        results = yf.Search(query)
        quotes = results.quotes if hasattr(results, "quotes") else []
        if quotes:
            return quotes[0].get("symbol")
    except Exception as e:
        logger.debug(f"yfinance 搜索失败: {e}")
    return None
