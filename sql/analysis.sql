-- Trade and position reconciliation on SIMULATED data. Written for SQLite.
-- Each result is saved as a view. Query a view to see its output.

-- 01 TRADE MATCHING
-- First mark repeated bookings of the same execution, so each execution is matched once.
DROP VIEW IF EXISTS v_internal_ranked;
CREATE VIEW v_internal_ranked AS
SELECT t.*,
       ROW_NUMBER() OVER (PARTITION BY exec_id ORDER BY trade_id) AS booking_no
FROM internal_trades t;

-- Pass 1 joins the two sides on execution ID. Pass 2 repairs trades the broker sent with a bad ID.
DROP VIEW IF EXISTS v_unmatched_internal;
CREATE VIEW v_unmatched_internal AS
SELECT i.*
FROM v_internal_ranked i
LEFT JOIN broker_fills b ON b.exec_id = i.exec_id
WHERE i.booking_no = 1 AND b.exec_id IS NULL;

DROP VIEW IF EXISTS v_unmatched_broker;
CREATE VIEW v_unmatched_broker AS
SELECT b.*
FROM broker_fills b
LEFT JOIN internal_trades i ON i.exec_id = b.exec_id
WHERE i.exec_id IS NULL;

DROP VIEW IF EXISTS v_ref_repairs;
CREATE VIEW v_ref_repairs AS
SELECT i.trade_id, i.exec_id AS internal_exec_id, b.exec_id AS broker_exec_id, b.broker_ref
FROM v_unmatched_internal i
JOIN v_unmatched_broker b
  ON b.trade_date = i.trade_date AND b.account = i.account AND b.symbol = i.symbol
 AND b.side = i.side AND b.qty = i.qty AND b.price = i.price
 AND b.exec_time = i.exec_time;

-- 02 BREAK REGISTER: one row per trade-level exception, with its size in USD.
DROP VIEW IF EXISTS v_trade_breaks;
CREATE VIEW v_trade_breaks AS
WITH matched AS (
    SELECT i.trade_id, i.exec_id, i.trade_date AS internal_date, b.trade_date AS broker_date,
           i.account, i.symbol, i.side AS internal_side, b.side AS broker_side,
           i.qty AS internal_qty, b.qty AS broker_qty, i.price AS internal_price, b.price AS broker_price
    FROM v_internal_ranked i
    JOIN broker_fills b ON b.exec_id = i.exec_id
    WHERE i.booking_no = 1
),
all_breaks AS (
    SELECT trade_id, exec_id, internal_date AS break_date, account, symbol,
           CASE WHEN internal_side <> broker_side THEN 'SIDE_MISMATCH'
                WHEN internal_date <> broker_date THEN 'DATE_MISMATCH'
                WHEN internal_qty <> broker_qty THEN 'QTY_MISMATCH'
                WHEN internal_price <> broker_price THEN 'PRICE_MISMATCH' END AS break_type,
           internal_side, internal_qty, internal_price, broker_side, broker_qty, broker_price
    FROM matched
    UNION ALL
    SELECT trade_id, exec_id, trade_date, account, symbol, 'DUPLICATE_INTERNAL',
           side, qty, price, NULL, NULL, NULL
    FROM v_internal_ranked WHERE booking_no > 1
    UNION ALL
    SELECT trade_id, exec_id, trade_date, account, symbol, 'REF_MISSING',
           side, qty, price, side, qty, price
    FROM v_unmatched_internal WHERE trade_id IN (SELECT trade_id FROM v_ref_repairs)
    UNION ALL
    SELECT trade_id, exec_id, trade_date, account, symbol, 'MISSING_AT_BROKER',
           side, qty, price, NULL, NULL, NULL
    FROM v_unmatched_internal WHERE trade_id NOT IN (SELECT trade_id FROM v_ref_repairs)
    UNION ALL
    SELECT NULL, exec_id, trade_date, account, symbol, 'MISSING_INTERNAL',
           NULL, NULL, NULL, side, qty, price
    FROM v_unmatched_broker WHERE exec_id NOT IN (SELECT broker_exec_id FROM v_ref_repairs)
)
SELECT a.*,
       ROUND(CASE
           WHEN a.break_type = 'PRICE_MISMATCH' THEN ABS(a.internal_price - a.broker_price) * a.internal_qty
           WHEN a.break_type = 'QTY_MISMATCH' THEN ABS(a.internal_qty - a.broker_qty) * a.internal_price
           WHEN a.break_type = 'REF_MISSING' THEN 0
           ELSE COALESCE(a.internal_qty * a.internal_price, a.broker_qty * a.broker_price)
       END * m.multiplier, 2) AS impact_usd
FROM all_breaks a
JOIN instruments m ON m.symbol = a.symbol
WHERE a.break_type IS NOT NULL;

DROP VIEW IF EXISTS v_break_summary;
CREATE VIEW v_break_summary AS
SELECT break_type, COUNT(*) AS breaks, ROUND(SUM(impact_usd), 2) AS impact_usd
FROM v_trade_breaks GROUP BY break_type ORDER BY breaks DESC;

-- 03 POSITION RECONCILIATION: rebuild the desk's closing position each day and compare it with the broker.
DROP VIEW IF EXISTS v_internal_eod;
CREATE VIEW v_internal_eod AS
WITH days AS (SELECT DISTINCT position_date AS d FROM broker_eod_positions),
grid AS (
    SELECT d.d, o.account, o.symbol, o.opening_qty
    FROM days d CROSS JOIN opening_positions o
),
flows AS (
    SELECT trade_date AS d, account, symbol,
           SUM(CASE WHEN side = 'BUY' THEN qty ELSE -qty END) AS net_qty
    FROM internal_trades GROUP BY trade_date, account, symbol
)
SELECT g.d AS position_date, g.account, g.symbol,
       g.opening_qty + SUM(COALESCE(f.net_qty, 0))
           OVER (PARTITION BY g.account, g.symbol ORDER BY g.d) AS internal_qty
FROM grid g
LEFT JOIN flows f ON f.d = g.d AND f.account = g.account AND f.symbol = g.symbol;

DROP VIEW IF EXISTS v_position_breaks;
CREATE VIEW v_position_breaks AS
WITH diff AS (
    SELECT i.position_date, i.account, i.symbol, i.internal_qty, b.broker_qty,
           i.internal_qty - b.broker_qty AS diff_qty
    FROM v_internal_eod i
    JOIN broker_eod_positions b
      ON b.position_date = i.position_date AND b.account = i.account AND b.symbol = i.symbol
),
expected AS (
    -- The difference between the two sets of trade records, added up to each date.
    -- Any position difference left over after this did not come from a recorded trade.
    SELECT p.position_date, p.account, p.symbol, COALESCE(SUM(x.effect), 0) AS explained_qty
    FROM (SELECT DISTINCT position_date, account, symbol FROM broker_eod_positions) p
    LEFT JOIN (
        SELECT i.trade_date AS flow_date, i.account, i.symbol,
               CASE WHEN i.side = 'BUY' THEN i.qty ELSE -i.qty END AS effect
        FROM internal_trades i
        WHERE i.exec_id NOT IN (SELECT internal_exec_id FROM v_ref_repairs)
        UNION ALL
        SELECT b.trade_date, b.account, b.symbol,
               CASE WHEN b.side = 'BUY' THEN -b.qty ELSE b.qty END
        FROM broker_fills b
        WHERE b.exec_id NOT IN (SELECT broker_exec_id FROM v_ref_repairs)
    ) x ON x.account = p.account AND x.symbol = p.symbol AND x.flow_date <= p.position_date
    GROUP BY p.position_date, p.account, p.symbol
)
SELECT d.position_date, d.account, d.symbol, d.internal_qty, d.broker_qty, d.diff_qty,
       e.explained_qty, d.diff_qty - e.explained_qty AS unexplained_qty,
       CASE WHEN d.diff_qty = e.explained_qty THEN 'EXPLAINED BY TRADE BREAKS'
            ELSE 'UNEXPLAINED, INVESTIGATE' END AS status
FROM diff d
JOIN expected e
  ON e.position_date = d.position_date AND e.account = d.account AND e.symbol = d.symbol
WHERE d.diff_qty <> 0;

-- 04 BREAK AGEING: how many reporting days each position break has been open at the latest date.
DROP VIEW IF EXISTS v_position_ageing;
CREATE VIEW v_position_ageing AS
WITH latest AS (SELECT MAX(position_date) AS d FROM broker_eod_positions)
SELECT b.account, b.symbol, MIN(b.position_date) AS first_seen, COUNT(*) AS days_open,
       MAX(CASE WHEN b.position_date = l.d THEN b.diff_qty END) AS latest_diff,
       MAX(CASE WHEN b.position_date = l.d THEN b.status END) AS latest_status
FROM v_position_breaks b CROSS JOIN latest l
GROUP BY b.account, b.symbol
ORDER BY days_open DESC, b.account, b.symbol;

-- 05 PRICE CHECK: a close identical to the previous close is flagged as possibly stale.
DROP VIEW IF EXISTS v_stale_prices;
CREATE VIEW v_stale_prices AS
SELECT * FROM (
    SELECT price_date, symbol, close_price,
           LAG(close_price) OVER (PARTITION BY symbol ORDER BY price_date) AS prior_close
    FROM eod_prices
)
WHERE close_price = prior_close;

-- 06 DAILY P&L, desk view: overnight position move plus each day's trades marked to the close.
DROP VIEW IF EXISTS v_daily_pnl;
CREATE VIEW v_daily_pnl AS
WITH prices AS (
    SELECT price_date, symbol, close_price,
           LAG(close_price) OVER (PARTITION BY symbol ORDER BY price_date) AS prior_close
    FROM eod_prices
),
start_pos AS (
    SELECT e.position_date, e.account, e.symbol,
           e.internal_qty - COALESCE((
               SELECT SUM(CASE WHEN t.side = 'BUY' THEN t.qty ELSE -t.qty END)
               FROM internal_trades t
               WHERE t.trade_date = e.position_date AND t.account = e.account AND t.symbol = e.symbol), 0) AS start_qty
    FROM v_internal_eod e
),
carry AS (
    SELECT s.position_date AS pnl_date, s.account, s.symbol,
           s.start_qty * (p.close_price - p.prior_close) * m.multiplier AS pnl
    FROM start_pos s
    JOIN prices p ON p.price_date = s.position_date AND p.symbol = s.symbol
    JOIN instruments m ON m.symbol = s.symbol
    WHERE p.prior_close IS NOT NULL
),
intraday AS (
    SELECT t.trade_date AS pnl_date, t.account, t.symbol,
           (CASE WHEN t.side = 'BUY' THEN t.qty ELSE -t.qty END) * (p.close_price - t.price) * m.multiplier AS pnl
    FROM internal_trades t
    JOIN prices p ON p.price_date = t.trade_date AND p.symbol = t.symbol
    JOIN instruments m ON m.symbol = t.symbol
)
SELECT pnl_date, account, ROUND(SUM(pnl), 2) AS pnl_usd
FROM (SELECT * FROM carry UNION ALL SELECT * FROM intraday)
GROUP BY pnl_date, account
ORDER BY pnl_date, account;

-- 07 INTRADAY ALERT: the first time each day a running position goes over its limit.
DROP VIEW IF EXISTS v_limit_alerts;
CREATE VIEW v_limit_alerts AS
WITH events AS (
    SELECT t.trade_date, t.exec_time, t.trade_id, t.account, t.symbol,
           o.opening_qty + SUM(CASE WHEN t.side = 'BUY' THEN t.qty ELSE -t.qty END)
               OVER (PARTITION BY t.account, t.symbol ORDER BY t.trade_date, t.exec_time, t.trade_id) AS running_qty
    FROM internal_trades t
    JOIN opening_positions o ON o.account = t.account AND o.symbol = t.symbol
),
over_limit AS (
    SELECT e.*, l.max_abs_position,
           ROW_NUMBER() OVER (PARTITION BY e.trade_date, e.account, e.symbol ORDER BY e.exec_time, e.trade_id) AS n
    FROM events e
    JOIN position_limits l ON l.symbol = e.symbol
    WHERE ABS(e.running_qty) > l.max_abs_position
)
SELECT trade_date, exec_time, trade_id, account, symbol, running_qty, max_abs_position
FROM over_limit WHERE n = 1
ORDER BY trade_date, exec_time;
