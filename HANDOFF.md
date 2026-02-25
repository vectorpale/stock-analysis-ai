# Openclaw 交接指令 — 个股深度分析系统

## 你的任务

你正在接手一个 **多Agent辩论模型的个股深度分析系统**。当前阶段需要你做的是：

1. **验证外部 API 数据可获取性** — 在有真实网络的环境中运行测试
2. **修复发现的任何问题** — 如果 API 返回格式变化、端点不可用等

## 项目结构

```
stock-analysis-ai/
├── CLAUDE.md              # 项目完整说明
├── .env                   # API Key 配置 (需要你创建)
├── pytest.ini             # pytest 配置 (默认只跑离线测试)
├── requirements.txt       # Python 依赖
├── src/data/fetcher.py    # 核心: 多源数据获取器 (FMP + Tushare + yfinance)
├── tests/
│   ├── conftest.py        # Mock 配置 (离线测试用)
│   ├── fixtures/sample_data.py  # Mock 数据
│   ├── test_fetcher.py    # 32个离线单元测试
│   ├── test_integration.py # 27个集成测试 (需要真实API)
│   └── healthcheck.py     # 独立数据源健康检查脚本
```

## 第一步: 创建 .env 文件

在项目根目录创建 `.env`，内容如下：

```
# Anthropic API Key (required)
ANTHROPIC_API_KEY=<your-anthropic-api-key>

# Tushare Token (A-share data)
TUSHARE_TOKEN=<your-tushare-token>
TUSHARE_URL=http://lianghua.nanyangqiankun.top

# FMP API Key (US stock data) — 使用 stable API
FMP_API_KEY=<your-fmp-api-key>

# News API Key (optional, for enhanced news coverage)
NEWS_API_KEY=
```

> **注意**: 真实 API Key 不应提交到 Git。请从项目拥有者处获取，或参考 .env.example。

## 第二步: 安装依赖

```bash
pip install -r requirements.txt
```

## 第三步: 运行测试 (按顺序)

### 3.1 离线单元测试 (应该全部通过)
```bash
pytest tests/ -v
```
预期: 32 passed, 27 deselected

### 3.2 数据源健康检查 (关键!)
```bash
python tests/healthcheck.py
```

这会检查三个数据源:
- **Tushare**: A股 (daily, daily_basic, income, fina_indicator) + 港股 (hk_basic, hk_daily, hk_daily_adj, hk_fina_indicator)
- **FMP**: 美股 (profile, income-statement, historical-price)
- **yfinance**: 美股 + 港股 (history, info, financials)

**如果 Tushare 镜像失败** (全部返回空数据):
```bash
# 注释掉 .env 中的 TUSHARE_URL, 改用官方地址:
# TUSHARE_URL=http://lianghua.nanyangqiankun.top
python tests/healthcheck.py --source tushare
```

**如果 FMP 返回 403 或报错**:
FMP 已从 v3 API 迁移到 stable API。当前代码使用:
- Base URL: `https://financialmodelingprep.com/stable`
- Symbol 通过查询参数传递: `/stable/profile?symbol=AAPL&apikey=KEY`

如果 FMP 还是不工作，可能需要检查这个 Key 是否绑定了 v3 还是 stable。

### 3.3 集成测试 (有网络时)
```bash
pytest tests/test_integration.py -m integration -v
```

## 第四步: 报告结果

请详细报告:
1. 每个数据源的可用状态 (OK / FAIL / SKIP)
2. 如果有 FAIL，具体的错误信息 (HTTP 状态码、返回内容等)
3. 你做了哪些修复 (如果有)

## 技术要点

### 数据源优先级
- 美股: FMP (stable API) → yfinance → AkShare
- 港股: Tushare → AkShare → yfinance
- A股: Tushare → AkShare → BaoStock

### FMP Stable API 格式
```
旧 (v3):  GET /api/v3/profile/AAPL?apikey=KEY
新 (stable): GET /stable/profile?symbol=AAPL&apikey=KEY
```
代码中所有 FMP 调用已迁移到 stable 格式。

### Tushare 已知限制
- 港股无原始财报 API (无 hk_income / hk_balancesheet / hk_cashflow)
- hk_fina_indicator 需要 15000 积分
- hk_daily_adj 需要较高积分

### 关键文件
- `src/data/fetcher.py` — DataFetcher 类，所有数据获取逻辑
- `tests/healthcheck.py` — 独立健康检查，无 pytest 依赖
- `tests/test_integration.py` — 带 schema 校验的集成测试
