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
src/data/industry.py     # 竞品识别、产业链、行业数据
src/data/news.py         # 新闻、业绩会、分析师预期
src/agents/definitions.py # Agent角色定义与提示词
src/agents/engine.py     # 多轮辩论引擎核心
src/agents/memory.py     # FinMem三层决策记忆
src/utils/helpers.py     # JSON解析、收敛计算等工具
analyze.py               # CLI入口
app.py                   # Streamlit Web UI
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

# Web UI 运行
streamlit run app.py
```

## 数据源优先级

- 美股: yfinance → AkShare
- 港股: AkShare → yfinance
- A股: AkShare → Tushare → BaoStock
