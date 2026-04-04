# Quant Strategy Optimization — Start Prompt

This recipe drives a full-cycle quantitative strategy optimization workflow on A-stock market data.

## Phase 1 — Understand the Direction

1. Read the human's direction message carefully.
2. If the human provides a reference strategy path, read the strategies there to understand:
   - Trading logic and signal generation approach
   - Stock universe and filtering criteria
   - Position sizing and risk management rules
   - Rebalancing frequency
3. Use web search or MCP tools to gather relevant domain knowledge about the direction.
4. Summarize findings in the shared thread before proceeding.

## Phase 2 — Data Preparation

1. Use Context7 MCP to look up tushare API documentation.
2. Download necessary market data to `data/tushare/`:
   - Daily OHLCV bars for relevant stock universe
   - Index data for benchmark (e.g. CSI 300, CSI 500)
   - Stock basics and industry classification
   - Trading calendar
   - Adjustment factors for accurate return calculation
3. If any tushare endpoint fails or is restricted, report to human immediately.
4. Verify data quality: check for missing dates, suspended stocks, price limit days.

## Phase 3 — Build Backtest Infrastructure

The researcher should build a generic, reusable backtest framework under `src/baseline/`:

- `src/baseline/data_fetcher.py` — Abstract `DataFetcher` base class + `TushareDataFetcher` implementation. Standard methods: `get_daily_bars()`, `get_index_data()`, `get_stock_list()`, `get_trade_calendar()`. All strategy code should depend on the abstract interface, not tushare directly.
- `src/baseline/backtest_engine.py` — Core backtest loop: load data, generate signals, simulate execution, calculate portfolio returns. Support configurable: start/end dates, initial capital, commission rate, slippage, benchmark index.
- `src/baseline/strategy_base.py` — Strategy base class with standard interface: `generate_signals()`, `get_positions()`. Each concrete strategy inherits from this.
- `src/baseline/metrics.py` — Complete evaluation metrics module. Must compute all required metrics:
  - 策略收益, 策略年化收益, 超额收益, 基准收益
  - 阿尔法, 贝塔, 夏普比率, 信息比率
  - 最大回撤, 最大回撤区间, 超额收益最大回撤
  - 胜率, 盈亏比, 日胜率, 盈利次数, 亏损次数
  - 日均超额收益, 超额收益夏普比率
  - 策略波动率, 基准波动率
- `baseline/run_baseline.py` — Entry point script. Accept `--config <yaml>` and `--dry-run` flags. Load strategy config, instantiate backtest engine, run evaluation, output results to `output/baseline_vx/`.

## Phase 4 — Iterative Strategy Development

Follow the standard baseline version iteration:

1. **Design**: researcher proposes strategy v1 based on the direction and EDA findings. Write design doc to `docs/baseline_v1_1_exp.md`.
2. **Implement**: create strategy configs under `baseline/experiments_v1/`, implement strategy class under `src/baseline/`.
3. **Dry run**: researcher validates the backtest pipeline works end-to-end with `--dry-run`.
4. **Submit**: trainer submits the formal runner `baseline/run_experiments_v1.sh` to `train_service`.
5. **Analyze**: trainer writes result summary with full metrics table to `docs/baseline_v1_1_exp_result.md`, generates equity curve and trend charts.
6. **Review**: leader reviews results, compares against market knowledge and strategy optimization experience.
7. **Next version**: leader decides the next direction — parameter refinement, new signal sources, risk management improvements, or entirely different approach.

## Phase 5 — Version Review (Every Version)

After each completed version:

1. Compare backtest results against expectations and market knowledge.
2. Identify what worked and what did not.
3. Check for overfitting risks: does the strategy exploit a real market pattern or just noise?
4. Leader uses `/skill-creator` to update skills about strategy optimization patterns and A-stock market knowledge.
5. Document the review in `docs/` or the shared thread.
6. Turn insights into concrete next-version experiments.

## Key Principles

- **Data interface abstraction**: all code depends on the abstract `DataFetcher`, not tushare directly. This makes future data source migration trivial.
- **CPU-only for model training**: if the strategy uses XGBoost or similar models, train on CPU.
- **Complete metrics**: every backtest result must include the full metrics set. No partial reporting.
- **Backtest period**: 2025-01-01 to present unless human specifies otherwise.
- **No overfitting**: be skeptical of strategies that work perfectly in backtest. Check robustness across different time windows and stock subsets.
- **Continuous iteration**: finishing one version is not finishing the task. Keep improving until human says stop or acceptance criteria are met.
