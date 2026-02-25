# Stock Deep Analysis - Multi-Agent Debate System

基于多 Agent 辩论模型的个股深度分析系统。

对单只股票进行全方位基本面深度分析，数据来源覆盖竞品对比、产业链上下游、财务报表、新闻资讯与分析师预期。六位 AI 分析师独立分析后经多轮辩论收敛，再经风控审核，最终由 CIO 做出投资决策。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                       数据收集层                              │
│  yfinance / AkShare / Tushare / BaoStock / NewsAPI          │
│  个股财报 · 竞品指标 · 产业链数据 · 新闻 · 分析师预期          │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               Phase 1: 独立分析 (防止锚定偏差)                 │
│                                                             │
│  Alex          Morgan        Sarah        David       Kai   │
│  基本面多头    基本面空头    行业分析师    财务分析师   宏观策略 │
│  ┌──┐         ┌──┐         ┌──┐         ┌──┐        ┌──┐   │
│  │+65│        │-40│         │+30│        │+50│       │+20│  │
│  └──┘         └──┘         └──┘         └──┘        └──┘   │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│             Phase 2: 多轮辩论 (Read-Critique-Update)          │
│                                                             │
│  Round 2: 阅读他人论点 → 质疑 → 回应 → 更新立场               │
│  Round 3: 再次交锋 → 收敛检测 (σ < threshold → 提前终止)      │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               Phase 3: 风控审核 (Chris 风控官)                 │
│                                                             │
│  APPROVE / APPROVE_WITH_CONDITIONS / VETO (一票否决)         │
│  风险等级 · 最大仓位 · 止损条件 · 监控指标                      │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               Phase 4: CIO 最终决策 (Claude Opus)             │
│                                                             │
│  综合各方观点 → 独立判断 → 投资建议                             │
│  STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL               │
│  目标价 · 止损位 · 仓位比例 · 时间维度                          │
└─────────────────────────────────────────────────────────────┘
```

## 分析师团队

| 角色 | 名称 | 专注领域 | 权重 |
|------|------|----------|------|
| 基本面多头 | Alex | 成长动力、竞争优势、上行催化剂 | 1.0 |
| 基本面空头 | Morgan | 风险识别、竞争威胁、估值泡沫 | 1.0 |
| 行业分析师 | Sarah | 竞品对比、产业链分析、行业动态 | 1.2 |
| 财务分析师 | David | 财报解读、盈利质量、估值模型 | 1.2 |
| 宏观策略师 | Kai | 宏观环境、政策影响、资金流向 | 0.9 |
| 风控官 | Chris | 风险评估、仓位建议、一票否决 | 1.1 |
| **CIO** | — | **综合决策 (Claude Opus)** | — |

## 数据来源

| 数据类型 | 内容 | 来源 |
|----------|------|------|
| 财务报表 | 利润表、资产负债表、现金流量表 (年度+季度) | yfinance |
| 关键指标 | PE/PS/PB/EV-EBITDA/ROE/利润率/增速等 | yfinance |
| 竞品对比 | 同行业公司核心指标横向对比 | yfinance + config 映射 |
| 产业链 | 上游供应商、下游客户的经营数据 | yfinance + config 映射 |
| 新闻资讯 | 公司新闻、行业新闻 | yfinance / NewsAPI |
| 业绩预期 | 分析师目标价、评级、下次财报日 | yfinance |
| 行情数据 | OHLCV + 技术指标 (RSI/MACD/布林带等) | yfinance / AkShare / Tushare / BaoStock |

**市场覆盖与降级策略：**

- 美股: yfinance → AkShare
- 港股: AkShare → yfinance
- A股: AkShare → Tushare → BaoStock

**行业映射覆盖** (config/config.yaml)：AI 芯片、云基础设施、AI 软件、新能源车、半导体设备、社交媒体、金融科技、生物医药、消费电子，以及港股互联网/AI/新能源车/金融/医药、A股 AI/半导体/新能源车/医药等 17 个板块。

## 模型分级

| 角色 | 模型 | 用途 |
|------|------|------|
| CIO 决策 | Claude Opus | 最终投资决策，最强推理能力 |
| 分析师辩论 | Claude Sonnet | 独立分析 + 多轮辩论，平衡性能与成本 |
| 数据提取 | Claude Haiku | 新闻摘要等轻量任务 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要的 API Key：

```
ANTHROPIC_API_KEY=your_key_here     # 必须
TUSHARE_TOKEN=your_token_here       # 可选，A股增强数据
NEWS_API_KEY=your_key_here          # 可选，行业新闻增强
```

### 3. 运行分析

**CLI 模式：**

```bash
# 分析美股
python analyze.py NVDA

# 分析港股
python analyze.py 0700.HK

# 分析A股
python analyze.py 002230.SZ

# 保存报告到文件
python analyze.py NVDA -o reports/nvda

# 输出完整 JSON 结果
python analyze.py NVDA --json
```

**Web UI 模式：**

```bash
streamlit run app.py
```

在浏览器中输入股票代码、填入 API Key，点击「开始深度分析」即可。分析过程中会实时显示各阶段进度和分析师立场。

## 项目结构

```
stock-analysis-ai/
├── config/
│   └── config.yaml            # 行业映射、产业链、模型参数、辩论参数
├── src/
│   ├── data/
│   │   ├── fetcher.py         # 多源行情与财务数据获取（含缓存与降级）
│   │   ├── industry.py        # 竞品识别、产业链映射、行业横向对比
│   │   └── news.py            # 新闻收集、业绩预期、分析师评级
│   ├── agents/
│   │   ├── definitions.py     # 6 个 Agent 角色定义 + CIO/辩论提示词
│   │   ├── engine.py          # 四阶段辩论引擎核心
│   │   └── memory.py          # FinMem 三层决策记忆（短期+长期+反思）
│   └── utils/
│       └── helpers.py         # JSON 解析、收敛计算、格式化工具
├── analyze.py                 # CLI 入口
├── app.py                     # Streamlit Web UI
├── requirements.txt
├── .env.example
└── CLAUDE.md
```

## 核心机制

### 辩论收敛检测

每轮辩论后计算各分析师立场 (position) 的标准差，当标准差低于阈值（默认 convergence_threshold=0.80）时提前终止辩论，避免无效重复。

### 加权得分聚合

最终得分 = Σ(position × weight × confidence) / Σ(weight × confidence)

其中行业分析师和财务分析师权重略高（1.2），体现基本面分析的侧重。

### FinMem 三层记忆

- **短期记忆**：最近 5 次分析记录
- **长期记忆**：30 天内的分析历史
- **反思记忆**：从历史错误判断中提取教训，注入 CIO 决策提示词

### 风控一票否决

风控官可对任何分析结论行使 VETO 否决权。被否决的标的强制输出 HOLD 建议。

## 参考文献

- Du et al. *Improving Factuality and Reasoning in Language Models through Multi-Agent Debate* (2023)
- TradingAgents: Multi-Agents LLM Financial Trading Framework (2024)
- FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Reflection (2024)
- Yao et al. *Reflexion: Language Agents with Verbal Reinforcement Learning* (NeurIPS 2023)

## 免责声明

本系统由 AI 生成分析内容，仅供学习研究参考，不构成任何投资建议。投资有风险，决策需谨慎。
