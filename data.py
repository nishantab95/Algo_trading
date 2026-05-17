"""
Data acquisition engine for canonical stock CSV storage.

The live system reads and writes only config_settings.DATA_DIR. A legacy import
path is supported when present, but duplicated folders are not required for
normal operation.
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
    if any(column not in df.columns for column in required):
        return pd.DataFrame()
    out = df[required].copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _csv_path(symbol: str) -> str:
    return os.path.join(cfg.DATA_DIR, f"{cfg.to_file_symbol(symbol)}.csv")


def _legacy_candidates() -> list[str]:
    return [
        cfg.LEGACY_DATA_SOURCE,
        os.path.join(cfg.LEGACY_DATA_SOURCE, "raw"),
        os.path.join(cfg.BASE_DIR, "data_strategies", "data"),
        os.path.join(cfg.BASE_DIR, "data_strategies", "data", "raw"),
    ]


def _resolve_legacy_source() -> str | None:
    for candidate in _legacy_candidates():
        if not os.path.isdir(candidate):
            continue
        try:
            if any(name.lower().endswith(".csv") for name in os.listdir(candidate)):
                return os.path.abspath(candidate)
        except OSError:
            continue
    return None


def sync_from_legacy_cache(force_copy: bool = False) -> dict:
    """
    Imports CSV files from the old data_strategies cache into data/raw if that
    optional cache exists. If it does not exist, validates the canonical folder.
    """
    cfg.ensure_directories()
    legacy_dir = _resolve_legacy_source()
    copied = 0
    skipped = 0
    errors: list[str] = []

    print("=" * 72)
    print("[DATA] Canonical data/raw synchronization")
    print("=" * 72)
    print(f"[DATA] Target folder: {cfg.DATA_DIR}")

    if legacy_dir is None:
        existing = sorted(name for name in os.listdir(cfg.DATA_DIR) if name.lower().endswith(".csv"))
        print("[DATA] Legacy cache not present. Canonical data/raw remains source of truth.")
        print(f"[DATA] Canonical CSV files: {len(existing)}")
        return {
            "copied": 0,
            "skipped": len(existing),
            "errors": [],
            "total": len(existing),
            "legacy_dir": None,
            "canonical_dir": cfg.DATA_DIR,
        }

    legacy_files = sorted(name for name in os.listdir(legacy_dir) if name.lower().endswith(".csv"))
    print(f"[DATA] Optional source cache: {legacy_dir}")
    print(f"[DATA] Source CSV files : {len(legacy_files)}")

    for index, filename in enumerate(legacy_files, start=1):
        src = os.path.join(legacy_dir, filename)
        dst = os.path.join(cfg.DATA_DIR, filename)
        try:
            if os.path.exists(dst) and not force_copy:
                skipped += 1
                continue
            shutil.copy2(src, dst)
            copied += 1
            if index % 100 == 0 or index == len(legacy_files):
                print(f"[DATA] Sync progress {index}/{len(legacy_files)} | copied={copied} skipped={skipped}")
        except OSError as exc:
            errors.append(f"{filename}: {exc}")
            print(f"[DATA] Copy failed for {filename}: {exc}")

    print("=" * 72)
    print(f"[DATA] Sync complete | copied={copied} skipped={skipped} errors={len(errors)}")
    print("=" * 72)
    return {
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "total": len(legacy_files),
        "legacy_dir": legacy_dir,
        "canonical_dir": cfg.DATA_DIR,
    }


def download_all(tickers: list[str] | None = None, force_copy: bool = False) -> dict:
    print("[DATA] download_all() -> importing optional legacy cache and validating data/raw.")
    sync_result = sync_from_legacy_cache(force_copy=force_copy)
    universe = tickers or cfg.get_full_ticker_universe()
    sync_result["universe_count"] = len(universe)
    return sync_result


def download_custom_ticker(ticker_symbol: str) -> dict:
    """
    Downloads five years of daily data for one custom ticker into data/raw and
    validates that preprocessing can build features/signals for it.
    """
    symbol = ticker_symbol.strip().upper()
    if not symbol:
        raise ValueError("Ticker symbol cannot be empty.")

    yf_symbol = cfg.to_yfinance_symbol(symbol)
    file_symbol = cfg.to_file_symbol(yf_symbol)
    path = _csv_path(file_symbol)
    cfg.ensure_directories()

    print("=" * 72)
    print(f"[DATA] Custom ticker download requested: {yf_symbol}")
    print("=" * 72)

    try:
        raw = yf.download(
            yf_symbol,
            period="5y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        normalized = _normalize_ohlcv(raw)
        if normalized.empty or len(normalized) < 220:
            raise ValueError(f"No usable daily OHLCV data returned for {yf_symbol}.")

        normalized.to_csv(path)
        print(f"[DATA] Saved {len(normalized)} rows -> {path}")

        import preprocessing

        processed = preprocessing.process_single_stock(path, file_symbol)
        if processed.empty:
            raise ValueError(f"{yf_symbol} downloaded, but preprocessing produced no strategy rows.")

        return {
            "ticker": file_symbol,
            "yfinance_symbol": yf_symbol,
            "rows_downloaded": int(len(normalized)),
            "processed_rows": int(len(processed)),
            "path": path,
        }

    except Exception as exc:
        raise RuntimeError(f"Custom ticker download failed for {yf_symbol}: {exc}") from exc


def update_symbol(symbol: str) -> bool:
    file_symbol = cfg.to_file_symbol(symbol)
    path = _csv_path(file_symbol)
    yf_symbol = cfg.to_yfinance_symbol(symbol)

    try:
        if not os.path.exists(path):
            print(f"[DATA] {file_symbol}: no local CSV in data/raw.")
            return False
        existing = pd.read_csv(path, index_col=0, parse_dates=True)
        existing = _normalize_ohlcv(existing)
        if existing.empty:
            print(f"[DATA] {file_symbol}: empty or invalid local file.")
            return False

        last_date = pd.Timestamp(existing.index.max()).normalize()
        start_date = last_date + timedelta(days=1)
        end_date = pd.Timestamp(datetime.now().date())
        if start_date > end_date:
            return True

        raw = yf.download(
            yf_symbol,
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=cfg.BAR_INTERVAL,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        fresh = _normalize_ohlcv(raw)
        if fresh.empty:
            return True
        merged = pd.concat([existing, fresh])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        merged.to_csv(path)
        print(f"[DATA] {file_symbol}: +{len(fresh)} row(s) | total={len(merged)}")
        return True

    except Exception as exc:
        print(f"[DATA] Incremental update failed for {file_symbol}: {exc}")
        return False


def update_data(tickers: list[str] | None = None, pause_seconds: float = 0.08) -> dict:
    cfg.ensure_directories()
    universe = tickers or cfg.get_full_ticker_universe()
    updated = 0
    up_to_date = 0
    failed: list[str] = []

    print("=" * 72)
    print(f"[DATA] Incremental daily update | tickers={len(universe)}")
    print("=" * 72)

    for index, symbol in enumerate(universe, start=1):
        try:
            path = _csv_path(symbol)
            if not os.path.exists(path):
                failed.append(symbol)
                continue
            before_rows = len(pd.read_csv(path, index_col=0))
            ok = update_symbol(symbol)
            after_rows = len(pd.read_csv(path, index_col=0))
            if ok and after_rows > before_rows:
                updated += 1
            elif ok:
                up_to_date += 1
            else:
                failed.append(symbol)
        except Exception as exc:
            print(f"[DATA] Unexpected update error for {symbol}: {exc}")
            failed.append(symbol)
        if index % 50 == 0:
            print(f"[DATA] Update progress {index}/{len(universe)}")
        time.sleep(pause_seconds)

    print("=" * 72)
    print(f"[DATA] Update complete | updated={updated} up_to_date={up_to_date} failed={len(failed)}")
    print("=" * 72)
    return {"updated": updated, "up_to_date": up_to_date, "failed": failed, "total": len(universe)}


if __name__ == "__main__":
    cfg.ensure_directories()
    download_all()
    update_data()
