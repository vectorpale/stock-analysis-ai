# 个股深度分析系统 - 多Agent辩论模型

## 项目概述

基于多Agent辩论模型的个股深度分析系统。参考 stock-trading-ai 的辩论架构，
专注于对单个股票进行全方位基本面深度分析，包括竞品对比、产业链分析、
财报解读、新闻资讯等全面数据来源。

## 技术架构

```
四阶段流水线:
  数据收集 → 独立分析(6Agent) → 多轮辩论(收敛检测) → 风控审核 → CIO决策

模型分级:
  CIO决策: Claude Opus (最强推理)
  分析师辩论: Claude Sonnet (平衡性能与成本)
  数据提取: Claude Haiku (快速处理)
```

## 目录结构

```
config/config.yaml       # 行业映射、产业链、模型配置
src/data/fetcher.py      # 多源行情与财务数据获取
src/data/web_search.py   # Web搜索数据源 (DuckDuckGo+LLM提取+IR验证)
src/data/industry.py     # 竞品识别、产业链、行业数据
src/data/news.py         # 新闻、业绩会、分析师预期
src/agents/definitions.py # Agent角色定义与提示词
src/agents/engine.py     # 多轮辩论引擎核心
src/agents/memory.py     # FinMem三层决策记忆
src/utils/helpers.py     # JSON解析、收敛计算等工具
src/paper_trading/portfolio.py  # 模拟盘组合管理器 (SQLite)
src/paper_trading/trader.py     # 交易执行器 (信号→交易映射)
analyze.py               # CLI入口
app.py                   # Streamlit 分析 Web UI
paper_trading.py         # Streamlit 模拟盘仪表盘
run_daily.py             # 每日定时分析+交易脚本
```

## 开发指南

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY

# CLI 运行
python analyze.py NVDA

# Web UI 运行 (深度分析)
streamlit run app.py

# 模拟盘仪表盘
streamlit run paper_trading.py

# 每日定时分析+自动交易
python run_daily.py                      # 分析全部自选股
python run_daily.py --snapshot-only      # 仅更新净值快照
python run_daily.py --dry-run            # 试运行不交易
```

## 数据源优先级

- 美股: FMP → yfinance → AkShare → **Web搜索**
- 港股: Tushare → AkShare → yfinance → **Web搜索**
- A股: Tushare → AkShare → BaoStock → **Web搜索**

### Web 搜索数据源 (新增)

当传统 API 不可用时，自动使用 DuckDuckGo 搜索 + LLM 提取结构化数据。
适合广为人知的上市公司。在 `config.yaml` 中设置 `web_search_enabled: true` 开启。

```bash
# 单独测试 Web 搜索数据源
python tests/test_web_search.py                  # 完整测试 (BIDU)
python tests/test_web_search.py --basic          # 仅测试搜索能力
python tests/test_web_search.py --symbol AAPL    # 指定其他股票
```
