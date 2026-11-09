import csv, sqlite3, os, glob
if os.path.exists("recon.db"): os.remove("recon.db")
c = sqlite3.connect("recon.db")
for f in glob.glob("data/*.csv"):
    t = os.path.basename(f)[:-4]
    rows = list(csv.DictReader(open(f)))
    cols = list(rows[0])
    def typ(col):
        try:
            [int(r[col]) for r in rows]; return "INTEGER"
        except ValueError:
            try:
                [float(r[col]) for r in rows]; return "REAL"
            except ValueError: return "TEXT"
    c.execute(f"CREATE TABLE {t} (" + ",".join(f"{k} {typ(k)}" for k in cols) + ")")
    c.executemany(f"INSERT INTO {t} VALUES (" + ",".join("?"*len(cols)) + ")", [[r[k] for k in cols] for r in rows])
c.executescript(open("sql/analysis.sql").read())
c.commit()
