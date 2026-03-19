"""OpenBB adapter configuration.

Reads provider API keys from environment or .env file.
yfinance provider works without any API keys.
"""
from __future__ import annotations

import os
from pathlib import Path

# Resolve project root (jarvis-v5/)
_THIS_DIR = Path(__file__).resolve().parent
QUANT_INFRA_DIR = _THIS_DIR.parent
PROJECT_ROOT = QUANT_INFRA_DIR.parent.parent  # workspace/quant_infra -> workspace -> jarvis-v5

# OpenBB venv python path
OPENBB_VENV = QUANT_INFRA_DIR / "env" / ".venv-openbb"
OPENBB_PYTHON = OPENBB_VENV / "bin" / "python3"

# Data directories
DATA_DIR = Path(os.environ.get(
    "QUANT_DATA_DIR",
    str(Path.home() / ".openclaw" / "workspace" / "data")
))

# DuckDB warehouse path
WAREHOUSE_PATH = Path(os.environ.get(
    "QUANT_WAREHOUSE_PATH",
    str(QUANT_INFRA_DIR / "warehouse" / "quant.duckdb")
))

# Default providers (yfinance is free, no key needed)
DEFAULT_PROVIDER = "yfinance"

# Symbols
NQ_SYMBOL = "NQ=F"
VIX_SYMBOL = "^VIX"
SPY_SYMBOL = "SPY"
QQQ_SYMBOL = "QQQ"

# Market context symbols to pull
MARKET_SYMBOLS = [NQ_SYMBOL, VIX_SYMBOL, SPY_SYMBOL, QQQ_SYMBOL]

# News search terms for NQ/tech context
NEWS_SEARCH_TERMS = ["nasdaq", "tech stocks", "fed rate", "inflation"]
