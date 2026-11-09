# Recomputes key results in pandas, without using any of the SQL views.
import pandas as pd
d="data/"
it=pd.read_csv(d+"internal_trades.csv"); br=pd.read_csv(d+"broker_fills.csv"); op=pd.read_csv(d+"opening_positions.csv")
st=pd.read_csv(d+"broker_eod_positions.csv"); px=pd.read_csv(d+"eod_prices.csv"); m=pd.read_csv(d+"instruments.csv")
it["s"]=it.qty.where(it.side=="BUY",-it.qty); br["s"]=br.qty.where(br.side=="BUY",-br.qty)
days=sorted(st.position_date.unique()); un=0; rows=[]
for a,s,o in op.itertuples(index=False):
    for day in days:
        i=o+it[(it.account==a)&(it.symbol==s)&(it.trade_date<=day)].s.sum()
        b=o+br[(br.account==a)&(br.symbol==s)&(br.trade_date<=day)].s.sum()
        q=st[(st.position_date==day)&(st.account==a)&(st.symbol==s)].broker_qty.iloc[0]
        if q!=b: rows.append((day,a,s,int(q-b)))
        un+= (i!=q)
print("position differences",un,"statement moves not from a fill",rows)
mult=m.set_index("symbol").multiplier
px=px.sort_values(["symbol","price_date"]); px["prev"]=px.groupby("symbol").close_price.shift()
print("stale",px[px.close_price==px.prev][["price_date","symbol"]].values.tolist())
tot=0
for day in days:
    for a in ["DESK_A","DESK_B"]:
        v=0
        for s,mu in mult.items():
            o=op[(op.account==a)&(op.symbol==s)].opening_qty.iloc[0]
            t=it[(it.account==a)&(it.symbol==s)]
            start=o+t[t.trade_date<day].s.sum()
            r=px[(px.symbol==s)&(px.price_date==day)].iloc[0]
            if pd.notna(r.prev): v+=start*(r.close_price-r.prev)*mu
            td=t[t.trade_date==day]; v+=(td.s*(r.close_price-td.price)).sum()*mu
        print(day,a,round(v,2)); tot+=v
print("total",round(tot,2))
