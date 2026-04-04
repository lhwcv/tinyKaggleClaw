# Quant Strategy Optimization — Data

## Data Source

Primary data source is **tushare** (https://tushare.pro/).

API key is stored in the project root `.env` file as `tushare_api_key`.

Load it in Python:

```python
import os
from dotenv import load_dotenv
load_dotenv()
token = os.getenv("tushare_api_key")
```

Or read `.env` directly if `python-dotenv` is not available.

## Querying Tushare API Documentation

Use **Context7 MCP** to look up tushare API usage:

1. First resolve the library: call `resolve-library-id` with query `tushare`
2. Then get docs: call `get-library-docs` with the resolved library ID

This gives you the exact function signatures, parameters, and return schemas for any tushare endpoint.

## Data Caching

- Download necessary data to `data/tushare/` on first use.
- Organize by data type:
  - `data/tushare/daily/` — daily OHLCV bars
  - `data/tushare/index/` — index data (benchmark)
  - `data/tushare/basic/` — stock basics, industry classification
  - `data/tushare/adj_factor/` — adjustment factors
  - `data/tushare/calendar/` — trading calendar
- Use local cached files for subsequent runs to avoid redundant API calls.
- File format: CSV or Parquet, whichever is more convenient for the use case.

## API Limitations

Tushare has rate limits and data access tiers. If an API endpoint returns an error or is restricted:

1. Report the exact error to human immediately.
2. Do not silently skip the data — the human needs to know.
3. Suggest alternative endpoints or data workarounds if possible.

## Data Interface Design

The data layer must be **abstracted** for easy source switching:

- Define a `DataFetcher` base class (or protocol) with standard methods like `get_daily_bars()`, `get_index_data()`, `get_stock_list()`, etc.
- Implement `TushareDataFetcher` as the concrete class.
- All strategy and backtest code should depend on the abstract interface, not on tushare directly.
- This makes it straightforward to add a new data source later (e.g. AKShare, local database, or broker API).

## Backtest Period

Default: **2025-01-01 to present**.

The human may override this. If the data for the requested period is not available, report to human.
