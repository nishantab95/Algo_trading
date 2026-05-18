"""
Data acquisition engine.

Flow:
  1. On startup: copy CSVs from D:\\Markets\\nifty → data/raw (project folder)
     Source files are NEVER modified — only read and copied.
  2. Custom downloads via yfinance go to data/raw.
  3. Preprocessing reads from data/raw exclusively.
  4. Processed consolidated file saved to data/processed_universe.csv.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

import config_settings as cfg


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)
    if "Adj Close" in df.columns and "Close" not in df.columns:
        df = df.rename(columns={"Adj Close": "Close"})
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()
    out = df[required].copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _csv_path(symbol: str) -> str:
    return os.path.join(cfg.DATA_DIR, f"{cfg.to_file_symbol(symbol)}.csv")


# ── Source resolution ──────────────────────────────────────────────────────────

def _resolve_raw_source() -> str | None:
    """
    Returns the path to the raw CSV source if it exists and contains CSVs.
    Checks RAW_DATA_DIR (D:\\Markets\\nifty) first, then LEGACY_DATA_SOURCE fallbacks.
    """
    candidates = [
        cfg.RAW_DATA_DIR,
        cfg.LEGACY_DATA_SOURCE,
        os.path.join(cfg.LEGACY_DATA_SOURCE, "raw"),
        os.path.join(cfg.BASE_DIR, "data_strategies", "data"),
        os.path.join(cfg.BASE_DIR, "data_strategies", "data", "raw"),
    ]
    # deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    for candidate in unique:
        if not os.path.isdir(candidate):
            continue
        try:
            if any(n.lower().endswith(".csv") for n in os.listdir(candidate)):
                return os.path.abspath(candidate)
        except OSError:
            continue
    return None


# ── Sync from raw source ───────────────────────────────────────────────────────

def sync_from_raw_source(force_copy: bool = False) -> dict:
    """
    Copies CSVs from D:\\Markets\\nifty into data/raw.
    Source files are never modified. Existing files in data/raw are skipped
    unless force_copy=True.
    """
    cfg.ensure_directories()
    source_dir = _resolve_raw_source()
    copied = 0
    skipped = 0
    errors: list[str] = []

    print("=" * 72)
    print("[DATA] Syncing raw data source → data/raw")
    print("=" * 72)
    print(f"[DATA] Target  : {cfg.DATA_DIR}")

    if source_dir is None:
        existing = [n for n in os.listdir(cfg.DATA_DIR) if n.lower().endswith(".csv")]
        print(f"[DATA] Source  : {cfg.RAW_DATA_DIR} — NOT FOUND or empty")
        print(f"[DATA] Falling back to existing data/raw ({len(existing)} files)")
        return {
            "copied": 0, "skipped": len(existing),
            "errors": [], "total": len(existing),
            "source_dir": None, "target_dir": cfg.DATA_DIR,
        }

    source_files = sorted(n for n in os.listdir(source_dir) if n.lower().endswith(".csv"))
    print(f"[DATA] Source  : {source_dir}")
    print(f"[DATA] Files   : {len(source_files)} CSVs found")

    for i, filename in enumerate(source_files, start=1):
        src = os.path.join(source_dir, filename)
        dst = os.path.join(cfg.DATA_DIR, filename)
        try:
            if os.path.exists(dst) and not force_copy:
                skipped += 1
                continue
            shutil.copy2(src, dst)
            copied += 1
            if i % 100 == 0 or i == len(source_files):
                print(f"[DATA] Progress {i}/{len(source_files)} | copied={copied} skipped={skipped}")
        except OSError as exc:
            errors.append(f"{filename}: {exc}")
            print(f"[DATA] Copy failed: {filename}: {exc}")

    print("=" * 72)
    print(f"[DATA] Sync done | copied={copied} skipped={skipped} errors={len(errors)}")
    print("=" * 72)
    return {
        "copied": copied, "skipped": skipped, "errors": errors,
        "total": len(source_files),
        "source_dir": source_dir, "target_dir": cfg.DATA_DIR,
    }


# ── Keep backward-compat alias used by main.py ────────────────────────────────
def sync_from_legacy_cache(force_copy: bool = False) -> dict:
    return sync_from_raw_source(force_copy=force_copy)


def download_all(tickers: list[str] | None = None, force_copy: bool = False) -> dict:
    print("[DATA] download_all() — syncing D:\\Markets\\nifty → data/raw")
    result = sync_from_raw_source(force_copy=force_copy)
    universe = tickers or cfg.get_full_ticker_universe()
    result["universe_count"] = len(universe)
    return result


# ── Custom ticker download ─────────────────────────────────────────────────────

def download_custom_ticker(ticker_symbol: str) -> dict:
    """
    Downloads 5 years of daily data for one ticker via yfinance → data/raw.
    Does NOT touch D:\\Markets\\nifty.
    """
    symbol     = ticker_symbol.strip().upper()
    if not symbol:
        raise ValueError("Ticker symbol cannot be empty.")
    yf_symbol  = cfg.to_yfinance_symbol(symbol)
    file_symbol= cfg.to_file_symbol(yf_symbol)
    path       = _csv_path(file_symbol)
    cfg.ensure_directories()

    print("=" * 72)
    print(f"[DATA] Downloading {yf_symbol} via yfinance → {path}")
    print("=" * 72)

    try:
        raw = yf.download(
            yf_symbol, period="5y", interval="1d",
            auto_adjust=True, progress=False, threads=False,
        )
        normalized = _normalize_ohlcv(raw)
        if normalized.empty or len(normalized) < 220:
            raise ValueError(f"Not enough data for {yf_symbol} (need ≥220 rows).")

        normalized.to_csv(path)
        print(f"[DATA] Saved {len(normalized)} rows → {path}")

        import preprocessing
        processed = preprocessing.process_single_stock(path, file_symbol)
        if processed.empty:
            raise ValueError(f"{yf_symbol} downloaded but preprocessing produced no rows.")

        return {
            "ticker": file_symbol, "yfinance_symbol": yf_symbol,
            "rows_downloaded": int(len(normalized)),
            "processed_rows": int(len(processed)), "path": path,
        }
    except Exception as exc:
        raise RuntimeError(f"Download failed for {yf_symbol}: {exc}") from exc


# ── Incremental update ─────────────────────────────────────────────────────────

def update_symbol(symbol: str) -> bool:
    """Appends new EOD rows to an existing CSV in data/raw from yfinance."""
    file_symbol = cfg.to_file_symbol(symbol)
    path        = _csv_path(file_symbol)
    yf_symbol   = cfg.to_yfinance_symbol(symbol)

    try:
        if not os.path.exists(path):
            print(f"[DATA] {file_symbol}: not in data/raw — skipping update")
            return False
        existing = _normalize_ohlcv(pd.read_csv(path, index_col=0, parse_dates=True))
        if existing.empty:
            return False

        last_date  = pd.Timestamp(existing.index.max()).normalize()
        start_date = last_date + timedelta(days=1)
        end_date   = pd.Timestamp(datetime.now().date())
        if start_date > end_date:
            return True

        raw   = yf.download(
            yf_symbol,
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=cfg.BAR_INTERVAL, auto_adjust=True,
            progress=False, threads=False,
        )
        fresh = _normalize_ohlcv(raw)
        if fresh.empty:
            return True
        merged = pd.concat([existing, fresh])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        merged.to_csv(path)
        print(f"[DATA] {file_symbol}: +{len(fresh)} row(s) → {len(merged)} total")
        return True

    except Exception as exc:
        print(f"[DATA] Update failed for {file_symbol}: {exc}")
        return False


def update_data(tickers: list[str] | None = None, pause_seconds: float = 0.08) -> dict:
    cfg.ensure_directories()
    universe  = tickers or cfg.get_full_ticker_universe()
    updated   = 0
    up_to_date= 0
    failed: list[str] = []

    print("=" * 72)
    print(f"[DATA] Incremental daily update | tickers={len(universe)}")
    print("=" * 72)

    for i, symbol in enumerate(universe, start=1):
        try:
            path = _csv_path(symbol)
            if not os.path.exists(path):
                failed.append(symbol)
                continue
            before = len(pd.read_csv(path, index_col=0))
            ok     = update_symbol(symbol)
            after  = len(pd.read_csv(path, index_col=0))
            if ok and after > before:
                updated += 1
            elif ok:
                up_to_date += 1
            else:
                failed.append(symbol)
        except Exception as exc:
            print(f"[DATA] Error updating {symbol}: {exc}")
            failed.append(symbol)
        if i % 50 == 0:
            print(f"[DATA] Progress {i}/{len(universe)}")
        time.sleep(pause_seconds)

    print("=" * 72)
    print(f"[DATA] Done | updated={updated} up_to_date={up_to_date} failed={len(failed)}")
    print("=" * 72)
    return {"updated": updated, "up_to_date": up_to_date, "failed": failed, "total": len(universe)}


if __name__ == "__main__":
    cfg.ensure_directories()
    download_all()
    update_data()