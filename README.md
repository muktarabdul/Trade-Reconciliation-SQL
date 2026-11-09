# Trade and Position Reconciliation in SQL

A start and end of day trading operations workflow, built in SQLite. It compares a desk's trade records with a broker's records, finds the breaks, explains position differences and raises alerts.

**All data is simulated.** No real trades, accounts or firms are used. `generate_data.py` creates the data and plants known errors, and the answer key is only used afterwards to test the results.

## Data

1,597 desk trades and 1,591 broker fills over five trading days, across 10 instruments and 6 groups: commodities, futures, options, equities, FX and crypto.

## What the SQL does

| Check | View |
|---|---|
| Matches trades on execution ID, then repairs bad broker references | `v_ref_repairs` |
| Lists each trade break with its type and USD size | `v_trade_breaks` |
| Rebuilds daily closing positions and compares them with the broker statement | `v_position_breaks` |
| Separates differences caused by trade records from those with no trade behind them | `v_position_breaks` |
| Shows how long each position break has been open | `v_position_ageing` |
| Flags closing prices that have not changed | `v_stale_prices` |
| Calculates daily P&L by account | `v_daily_pnl` |
| Finds the first limit breach per account, instrument and day | `v_limit_alerts` |

## Results

- Found all 57 planted trade breaks across 8 break types, with no false positives.
- Isolated a 300-share MSFT difference on DESK_B from 14 October that no trade explains, the planted unbooked transfer.
- Flagged the planted stale gold price on 15 October.
- 51 position differences were found: 48 explained by trade records and 3 daily readings of the unexplained MSFT transfer.
- Raised 29 limit alerts.

## How it was tested

`validation/check.py` compares the output with the answer key. `validation/independent_check.py` recalculates positions, the stale price and daily P&L in pandas without using the SQL.

## Limitations

The errors are planted and the data is cleaner than a real feed. USD sizes are gross and do not include fees, FX conversion or settlement. P&L uses desk records, so it still contains the breaks it has not corrected.

## Run it

```
python generate_data.py
python build_db.py
python validation/check.py
```

Built with AI assistance while learning SQL.
