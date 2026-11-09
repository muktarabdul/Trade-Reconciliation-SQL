import sqlite3, csv, collections
c = sqlite3.connect("recon.db")
key = list(csv.DictReader(open("validation/answer_key.csv")))
trade_key = [k for k in key if k["break_type"] not in ("UNBOOKED_TRANSFER","STALE_PRICE")]
found = c.execute("select trade_id, exec_id, break_type from v_trade_breaks").fetchall()
def ids(t,e,b):
    return e if b=="MISSING_INTERNAL" else t
expected = {(k["exec_id"] if k["break_type"]=="MISSING_INTERNAL" else (k["trade_id"]+"D" if k["break_type"]=="DUPLICATE_INTERNAL" else k["trade_id"]), k["break_type"]) for k in trade_key}
got = {(ids(*f), f[2]) for f in found}
print("expected", len(expected), "found", len(got), "missed", expected-got, "false", got-expected)
print(collections.Counter(k["break_type"] for k in key))
for v in ["v_break_summary","v_stale_prices","v_position_ageing","v_daily_pnl"]:
    print(v); [print(r) for r in c.execute(f"select * from {v}").fetchall()]
print("pos breaks", c.execute("select status,count(*) from v_position_breaks group by 1").fetchall())
print([r for r in c.execute("select * from v_position_breaks where status like 'UNEX%'")])
print("alerts", c.execute("select count(*) from v_limit_alerts").fetchone())
print("rows", [c.execute(f"select count(*) from {t}").fetchone()[0] for t in ["internal_trades","broker_fills","broker_eod_positions"]])
