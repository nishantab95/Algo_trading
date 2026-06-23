from __future__ import annotations

import hashlib,json
from datetime import datetime,timezone
import pandas as pd


def validate_market_data(data:pd.DataFrame,symbols=None,min_rows=50,stale_days=30):
    symbols=symbols or sorted(data["Ticker"].dropna().unique().tolist()) if "Ticker" in data else []
    warnings=[];rows={};missing={};skipped=[];stale=[]
    required={"Date","Open","High","Low","Close","Volume"}
    absent=sorted(required-set(data.columns))
    if absent:warnings.append(f"Missing OHLCV columns: {', '.join(absent)}")
    if "Date" in data:
        dates=pd.to_datetime(data["Date"],errors="coerce")
        if dates.duplicated().any() and "Ticker" not in data:warnings.append("Duplicate dates detected")
    for symbol in symbols:
        frame=data[data["Ticker"]==symbol].copy() if "Ticker" in data else data.copy();rows[symbol]=len(frame)
        if len(frame)<min_rows:warnings.append(f"{symbol}: too few rows");skipped.append(symbol)
        if required<=set(frame.columns):
            bad_price=(frame[["Open","High","Low","Close"]]<=0).any(axis=1).sum();bad_volume=(frame["Volume"]<0).sum()
            if bad_price:warnings.append(f"{symbol}: {bad_price} non-positive price rows")
            if bad_volume:warnings.append(f"{symbol}: {bad_volume} negative-volume rows")
            duplicate=frame["Date"].duplicated().sum()
            if duplicate:warnings.append(f"{symbol}: {duplicate} duplicate dates")
            missing[symbol]={c:int(frame[c].isna().sum()) for c in required if frame[c].isna().any()}
            latest=pd.to_datetime(frame["Date"],errors="coerce").max()
            if pd.notna(latest) and (pd.Timestamp.now(tz=None)-latest.tz_localize(None)).days>stale_days:stale.append(symbol);warnings.append(f"{symbol}: stale data")
    warnings.extend(["Survivorship bias has not been independently audited","Corporate actions have not been independently audited","Historical index membership is unavailable unless supplied"])
    return {"valid":not absent,"warnings":warnings,"rows_per_symbol":rows,"missing_dates":missing,"skipped_symbols":sorted(set(skipped)),"stale_symbols":stale}

def split_data(data:pd.DataFrame,mode="percentage_split",config=None):
    config=config or {};frame=data.sort_values("Date").copy();dates=sorted(pd.to_datetime(frame["Date"]).dt.normalize().unique())
    if len(dates)<2:raise ValueError("At least two dates are required for train/test validation")
    if mode=="fixed_date_split":cut=pd.Timestamp(config["split_date"]);train=frame[pd.to_datetime(frame["Date"])<=cut];test=frame[pd.to_datetime(frame["Date"])>cut]
    elif mode in {"percentage_split","final_holdout"}:
        ratio=float(config.get("train_pct",80))/100;index=max(1,min(len(dates)-1,int(len(dates)*ratio)));cut=pd.Timestamp(dates[index-1]);train=frame[pd.to_datetime(frame["Date"])<=cut];test=frame[pd.to_datetime(frame["Date"])>cut]
    elif mode=="rolling_time_split":
        days=int(config.get("train_days",max(1,len(dates)*2//3)));cut=pd.Timestamp(dates[min(days-1,len(dates)-2)]);train=frame[pd.to_datetime(frame["Date"])<=cut];test=frame[pd.to_datetime(frame["Date"])>cut]
    else:raise ValueError("Unsupported train/test split mode")
    if train.empty or test.empty:raise ValueError("Train/test split produced an empty period")
    return train,test,{"mode":mode,"train_start":str(pd.to_datetime(train["Date"]).min().date()),"train_end":str(pd.to_datetime(train["Date"]).max().date()),"test_start":str(pd.to_datetime(test["Date"]).min().date()),"test_end":str(pd.to_datetime(test["Date"]).max().date())}

def content_hash(data):
    if hasattr(data,"to_csv"):raw=data.to_csv(index=False).encode()
    else:raw=json.dumps(data,sort_keys=True,default=str).encode()
    return hashlib.sha256(raw).hexdigest()
