from dataclasses import dataclass

@dataclass
class Decision:
    signal: str
    direction: str | None
    p_up: float
    p_flat: float
    p_down: float
    confidence: float


def decide(p_up, p_flat, p_down, conf_threshold=.55, high_conviction_threshold=.90):
    probs={"SUBIDA":p_up,"LATERAL":p_flat,"BAJADA":p_down}; top=max(probs,key=probs.get); conf=probs[top]
    if conf < conf_threshold: return Decision("NO_OPERAR",None,p_up,p_flat,p_down,conf)
    if top=="LATERAL": return Decision("ESPERAR",None,p_up,p_flat,p_down,conf)
    return Decision("ALTA_CONVICCION" if conf>=high_conviction_threshold else "ENTRAR",top,p_up,p_flat,p_down,conf)

@dataclass
class EntrySetup:
    entry_low: float; entry_high: float; target: float; invalidation: float; risk_reward: float

def build_entry_setup(current_price,direction,atr,target_atr_mult=3.0,stop_atr_mult=1.5):
    lo=current_price*.995; hi=current_price*1.005
    if direction=="SUBIDA": target=current_price+target_atr_mult*atr; invalid=current_price-stop_atr_mult*atr
    else: target=current_price-target_atr_mult*atr; invalid=current_price+stop_atr_mult*atr
    risk=abs(current_price-invalid); reward=abs(target-current_price)
    return EntrySetup(lo,hi,target,invalid,reward/risk if risk else float("nan"))

@dataclass
class StopOption:
    name:str; price:float; distance_pct:float; rr_to_tp1:float; basis:str
@dataclass
class RiskPlan:
    recommended:StopOption; tight:StopOption; standard:StopOption; conservative:StopOption
    tp1:float; tp2:float; tp3:float; entry:float; structure_level:float|None


def build_risk_plan(df,current_price,direction,atr,lookback=24,structure_buffer_atr=.25):
    if atr<=0: raise ValueError("ATR must be positive")
    recent=df.tail(max(5,min(lookback,len(df)))); entry=float(current_price)
    if direction=="SUBIDA":
        swing=float(recent["low"].min()); a1=entry-1*atr; a2=entry-1.6*atr; a3=entry-2.3*atr
        struct=swing-structure_buffer_atr*atr; tight=max(0,a1); standard=max(0,min(a2,struct)); cons=max(0,min(a3,struct-.5*atr))
        tp1,tp2,tp3=entry+2*atr,entry+3.2*atr,entry+4.5*atr; label="debajo del swing + buffer ATR"
    else:
        swing=float(recent["high"].max()); a1=entry+atr; a2=entry+1.6*atr; a3=entry+2.3*atr
        struct=swing+structure_buffer_atr*atr; tight=a1; standard=max(a2,struct); cons=max(a3,struct+.5*atr)
        tp1,tp2,tp3=entry-2*atr,entry-3.2*atr,entry-4.5*atr; label="encima del swing + buffer ATR"
    def opt(name,price,basis):
        risk=abs(entry-price); rew=abs(tp1-entry)
        return StopOption(name,float(price),risk/entry*100 if entry else float('nan'),rew/risk if risk else float('nan'),basis)
    t=opt("Ajustado",tight,"1.0 ATR; sensible al ruido"); s=opt("Recomendado",standard,f"1.6 ATR y {label}"); c=opt("Conservador",cons,f"2.3 ATR y {label}")
    return RiskPlan(s,t,s,c,float(tp1),float(tp2),float(tp3),entry,swing)


def confluence_analysis(row, direction: str | None):
    """Independent technical confluence score. It never rewrites calibrated probabilities."""
    if not direction: return {"score":0,"support":[],"conflict":[],"label":"Sin dirección"}
    long = direction=="SUBIDA"; support=[]; conflict=[]
    checks=[]
    def add(name, bullish, weight=1): checks.append((name,bool(bullish),weight))
    add("Precio vs EMA 200", row.get("dist_ema_200",0)>0, 2)
    add("EMA 20 vs EMA 50", row.get("dist_ema_20",0)>row.get("dist_ema_50",0), 1.5)
    add("Pendiente EMA 200", row.get("ema200_slope_20",0)>=0, 1.5)
    add("ADX/DMI", row.get("di_spread",0)>0, 1.5)
    add("MACD", row.get("macd_hist",0)>0, 1)
    add("RSI", row.get("rsi_14",50)>=50, 1)
    add("VWAP", row.get("vwap_dist",0)>0, 1.5)
    add("CMF", row.get("cmf_20",0)>0, 1)
    add("OBV", row.get("obv_norm",0)>0, 1)
    add("Estructura 50", row.get("range_pos_50",.5)>.5, 1)
    total=sum(w for _,_,w in checks); agree=0
    for name,bullish,w in checks:
        ok = bullish if long else not bullish
        if ok: support.append(name); agree+=w
        else: conflict.append(name)
    score=100*agree/total if total else 0
    return {"score":score,"support":support,"conflict":conflict,"label":"Alta" if score>=72 else "Media" if score>=55 else "Baja"}
