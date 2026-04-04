# Quant Strategy Optimization — Overview

## Task Type

This is an **A-stock quantitative strategy optimization task**.

## Goal

Given a human-provided direction (e.g. "mid-cap momentum strategy based on volume-price patterns"), the agent team autonomously iterates through strategy design, implementation, backtesting, and refinement cycles.

## Reference Strategies

The human will provide a path to reference strategies (typically JoinQuant-format Python files). These are for **logic reference only** — the actual implementation must use tushare data with a local backtest engine.

## Strategy Types

Strategies may be:

- **Rule-based**: technical indicators, breakout signals, mean reversion, etc.
- **Model-based**: XGBoost, LightGBM, or other tree models for signal generation. Model training must use **CPU only**.

## Evaluation Metrics

All backtest results must include at minimum:

| Category | Metrics |
|----------|---------|
| Returns | 策略收益, 策略年化收益, 超额收益, 基准收益 |
| Risk-adjusted | 阿尔法, 贝塔, 夏普比率, 信息比率 |
| Drawdown | 最大回撤, 最大回撤区间, 超额收益最大回撤 |
| Win/Loss | 胜率, 盈亏比, 日胜率, 盈利次数, 亏损次数 |
| Volatility | 策略波动率, 基准波动率 |
| Excess | 日均超额收益, 超额收益夏普比率 |

## Backtest Period

**2025-01-01 to present** unless the human specifies otherwise.

## Version Review Frequency

**Every 1 version** — after each completed version, review against market knowledge and strategy optimization experience.

## Workspace Layout

Same as the repository default:

- `src/baseline/` — backtest engine, strategy code, data fetchers, metrics
- `baseline/` — experiment configs, runner scripts
- `data/` — market data (cached from tushare)
- `output/` — backtest results, logs
- `docs/` — version design notes, result summaries, trend charts
- `eda/` — exploratory data analysis
