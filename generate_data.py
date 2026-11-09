"""Generates SIMULATED trading data for the reconciliation project.
No real trades, accounts, firms or prices are used.
The answer key is written separately and is never read by the SQL."""
import csv
import os
import random
from datetime import date, datetime, timedelta

random.seed(2026)
OUT = "data"
os.makedirs(OUT, exist_ok=True)
os.makedirs("validation", exist_ok=True)

INSTRUMENTS = [
    ("CLZ6", "Crude oil future", "commodities", 1000, 75.0, 0.01, 1),
    ("GCZ6", "Gold future", "commodities", 100, 2400.0, 0.10, 1),
    ("ESZ6", "E-mini S&P future", "futures", 50, 6000.0, 0.25, 1),
    ("ZNZ6", "10-year note future", "futures", 1000, 110.0, 0.015625, 1),
    ("ESZ6C6100", "E-mini S&P call option", "options", 50, 85.0, 0.25, 1),
    ("AAPL", "Apple equity", "equities", 1, 220.0, 0.01, 100),
    ("MSFT", "Microsoft equity", "equities", 1, 480.0, 0.01, 100),
    ("EURUSD", "Euro spot FX", "fx", 100000, 1.08, 0.0001, 1),
    ("GBPUSD", "Sterling spot FX", "fx", 100000, 1.27, 0.0001, 1),
    ("BTCUSD", "Bitcoin spot", "crypto", 1, 90000.0, 1.0, 1),
]
ACCOUNTS = {"DESK_A": ["MOMENTUM", "MEAN_REV"], "DESK_B": ["ARB", "MARKET_MAKING"]}
DATES = [date(2026, 10, 12) + timedelta(days=i) for i in range(5)]
LIMITS = {"CLZ6": 40, "GCZ6": 30, "ESZ6": 40, "ZNZ6": 60, "ESZ6C6100": 30, "AAPL": 4000,
          "MSFT": 2500, "EURUSD": 40, "GBPUSD": 30, "BTCUSD": 8}


def snap(px, tick):
    return round(round(px / tick) * tick, 6)


# Daily closes, with a stale price deliberately planted on GCZ6 on day 4.
closes = {}
level = {i[0]: i[4] for i in INSTRUMENTS}
inst = {i[0]: i for i in INSTRUMENTS}
for d in DATES:
    for sym, *_rest in INSTRUMENTS:
        tick = inst[sym][5]
        while True:
            new = snap(level[sym] * (1 + random.gauss(0, 0.009)), tick)
            if new != level[sym]:
                break
        level[sym] = new
        closes[(d, sym)] = new
closes[(DATES[3], "GCZ6")] = closes[(DATES[2], "GCZ6")]

# Clean trades, matched one for one between the desk and the broker.
trades = []
n = 0
for d in DATES:
    for _ in range(320):
        n += 1
        sym = random.choice(list(inst))
        _, _, _, _, _, tick, lot = inst[sym]
        acct = random.choice(list(ACCOUNTS))
        t = datetime(d.year, d.month, d.day, 8, 0, 0) + timedelta(seconds=random.randint(0, 32400))
        base = closes[(d, sym)]
        qty = lot * random.randint(1, 6)
        if sym == "BTCUSD":
            qty = random.randint(1, 3)
        trades.append(dict(
            trade_id=f"T{n:06d}", exec_id=f"X{random.randint(10**8, 10**9 - 1)}", trade_date=d.isoformat(),
            exec_time=t.strftime("%H:%M:%S"), account=acct, strategy=random.choice(ACCOUNTS[acct]), symbol=sym,
            side=random.choice(["BUY", "SELL"]), qty=qty,
            price=snap(base * (1 + random.gauss(0, 0.003)), tick)))

broker = []
for i, t in enumerate(trades):
    broker.append(dict(broker_ref=f"B{i + 1:07d}", exec_id=t["exec_id"], trade_date=t["trade_date"],
                       exec_time=t["exec_time"], account=t["account"], symbol=t["symbol"], side=t["side"],
                       qty=t["qty"], price=t["price"]))

# Plant trade-level breaks on separate trades.
counts = dict(MISSING_AT_BROKER=9, MISSING_INTERNAL=8, QTY_MISMATCH=9, PRICE_MISMATCH=10, SIDE_MISMATCH=4,
              DUPLICATE_INTERNAL=5, REF_MISSING=7, DATE_MISMATCH=5)
pool = random.sample(range(len(trades)), sum(counts.values()))
key = []
drop_internal, drop_broker, extra_internal = set(), set(), []
p = 0
for kind, c in counts.items():
    for _ in range(c):
        idx = pool[p]
        p += 1
        t, b = trades[idx], broker[idx]
        tick = inst[t["symbol"]][5]
        lot = inst[t["symbol"]][6]
        if kind == "MISSING_AT_BROKER":
            drop_broker.add(idx)
        elif kind == "MISSING_INTERNAL":
            drop_internal.add(idx)
        elif kind == "QTY_MISMATCH":
            b["qty"] = t["qty"] + lot
        elif kind == "PRICE_MISMATCH":
            b["price"] = snap(t["price"] + tick * random.choice([-5, -3, 2, 4, 6]), tick)
        elif kind == "SIDE_MISMATCH":
            b["side"] = "SELL" if t["side"] == "BUY" else "BUY"
        elif kind == "DUPLICATE_INTERNAL":
            d = dict(t)
            d["trade_id"] = t["trade_id"] + "D"
            extra_internal.append(d)
        elif kind == "REF_MISSING":
            b["exec_id"] = "UNK" + b["exec_id"][3:]
        elif kind == "DATE_MISMATCH":
            current = date.fromisoformat(t["trade_date"])
            if current == DATES[-1]:  # keep the booked date inside the sample
                b["trade_date"] = DATES[-2].isoformat()
            else:
                t["trade_date"] = DATES[DATES.index(current) + 1].isoformat()
        key.append(dict(exec_id=t["exec_id"], trade_id=t["trade_id"], break_type=kind))

internal_out = [t for i, t in enumerate(trades) if i not in drop_internal] + extra_internal
broker_out = [b for i, b in enumerate(broker) if i not in drop_broker]
internal_out.sort(key=lambda r: (r["trade_date"], r["exec_time"], r["trade_id"]))
broker_out.sort(key=lambda r: (r["trade_date"], r["exec_time"], r["broker_ref"]))


def write(name, rows, folder=OUT):
    with open(f"{folder}/{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


write("internal_trades", internal_out)
write("broker_fills", broker_out)
write("instruments", [dict(symbol=i[0], description=i[1], asset_class=i[2], multiplier=i[3], tick_size=i[5]) for i in INSTRUMENTS])
write("eod_prices", [dict(price_date=d.isoformat(), symbol=s, close_price=closes[(d, s)]) for (d, s) in closes])
write("position_limits", [dict(symbol=s, max_abs_position=v) for s, v in LIMITS.items()])

# Opening positions agree on both sides.
opening = []
for a in ACCOUNTS:
    for s in inst:
        lot = inst[s][6]
        opening.append(dict(account=a, symbol=s, opening_qty=lot * random.randint(-8, 8)))
write("opening_positions", opening)

# Broker end-of-day statement is built from broker fills, plus one transfer the desk never booked.
pos = {(o["account"], o["symbol"]): o["opening_qty"] for o in opening}
statement = []
TRANSFER_DAY, TRANSFER = DATES[2].isoformat(), ("DESK_B", "MSFT", -300)
for d in DATES:
    iso = d.isoformat()
    for b in broker_out:
        if b["trade_date"] == iso:
            sign = 1 if b["side"] == "BUY" else -1
            pos[(b["account"], b["symbol"])] += sign * b["qty"]
    if iso == TRANSFER_DAY:
        pos[TRANSFER[:2]] += TRANSFER[2]
    for (a, s), q in sorted(pos.items()):
        statement.append(dict(position_date=iso, account=a, symbol=s, broker_qty=q))
write("broker_eod_positions", statement)

key.append(dict(exec_id="", trade_id=f"{TRANSFER[0]}/{TRANSFER[1]}", break_type="UNBOOKED_TRANSFER"))
key.append(dict(exec_id="", trade_id=f"GCZ6/{DATES[3].isoformat()}", break_type="STALE_PRICE"))
write("answer_key", key, "validation")
print(len(internal_out), len(broker_out), len(key))
