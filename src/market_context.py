"""Live market-wide context. Public endpoints only; failures return N/A rather than fake data."""
import requests
import numpy as np

BINANCE="https://api.binance.com"
FUTURES="https://fapi.binance.com"

def market_breadth(timeout=10):
    r=requests.get(BINANCE+"/api/v3/ticker/24hr",timeout=timeout); r.raise_for_status(); raw=r.json()
    rows=[]
    for x in raw:
        s=x.get("symbol","")
        if not s.endswith("USDT") or any(z in s for z in ("UPUSDT","DOWNUSDT","BULLUSDT","BEARUSDT")): continue
        try:
            q=float(x.get("quoteVolume",0)); ch=float(x.get("priceChangePercent",0))
            if q>=5_000_000: rows.append((s,ch,q))
        except Exception: pass
    if not rows: return None
    changes=np.array([x[1] for x in rows]); vols=np.array([x[2] for x in rows])
    return {"n":len(rows),"positive_pct":float((changes>0).mean()*100),"median_change":float(np.median(changes)),
            "volume_weighted_change":float(np.average(changes,weights=vols)),
            "state":"RISK-ON" if (changes>0).mean()>=.58 else "RISK-OFF" if (changes>0).mean()<=.42 else "MIXTO"}

def fear_greed(timeout=10):
    r=requests.get("https://api.alternative.me/fng/?limit=1&format=json",timeout=timeout); r.raise_for_status(); d=r.json()["data"][0]
    return {"value":int(d["value"]),"classification":d["value_classification"]}

def derivatives(symbol, timeout=10):
    out={"funding":None,"open_interest":None}
    try:
        r=requests.get(FUTURES+"/fapi/v1/premiumIndex",params={"symbol":symbol},timeout=timeout); r.raise_for_status(); out["funding"]=float(r.json().get("lastFundingRate"))*100
    except Exception: pass
    try:
        r=requests.get(FUTURES+"/fapi/v1/openInterest",params={"symbol":symbol},timeout=timeout); r.raise_for_status(); out["open_interest"]=float(r.json().get("openInterest"))
    except Exception: pass
    return out
