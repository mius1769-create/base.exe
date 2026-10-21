"""Минимальная автономная проверка логики этой итерации Dashboard."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
repo_path = ROOT / "dashboard_repo.py"

# Делаем временный пакет, чтобы dashboard_repo мог использовать относительный import product_catalog.
tmp = ROOT / "_test_pkg"
tmp.mkdir(exist_ok=True)
(tmp / "__init__.py").write_text("", encoding="utf-8")
(tmp / "product_catalog.py").write_text("def get_display_name(code): return code\n", encoding="utf-8")
(tmp / "dashboard_repo.py").write_text(repo_path.read_text(encoding="utf-8"), encoding="utf-8")

spec = importlib.util.spec_from_file_location("_test_pkg.dashboard_repo", tmp / "dashboard_repo.py", submodule_search_locations=[])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
mod.__package__ = "_test_pkg"
spec.loader.exec_module(mod)

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript("""
CREATE TABLE orders(order_id INTEGER PRIMARY KEY, order_no TEXT, customer_name TEXT,
    order_amount REAL, is_archived INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE tests(test_id INTEGER PRIMARY KEY, order_id INTEGER, test_type TEXT,
    is_archived INTEGER DEFAULT 0, created_at TEXT, client_issued_at TEXT,
    deadline_date TEXT, lab_sent_at TEXT, lab_profile_received_at TEXT,
    sample_received_at TEXT);
CREATE TABLE test_types(code TEXT PRIMARY KEY, price REAL, cost_price REAL, requires_lab INTEGER);
""")
mod._ensure_promo_column(conn)
conn.executemany("INSERT INTO test_types VALUES (?,?,?,?)", [
    ("STRELKA", 14900, 5000, 1),
    ("Y50", 7490, 3000, 1),
])
conn.executemany("""INSERT INTO orders
    (order_id, order_no, customer_name, order_amount, is_archived, created_at, is_promo)
    VALUES (?,?,?,?,?,?,?)""", [
    (1,"1","Commercial A",14900,0,"2026-09-10",0),
    (2,"2","Promo B",0,0,"2026-09-11",1),
    (3,"3","Promo C",10000,0,"2026-09-12",1),
    (4,"4","Commercial D",10000,0,"2026-09-13",0),
])
conn.executemany("""INSERT INTO tests
    (test_id,order_id,test_type,is_archived,created_at,client_issued_at)
    VALUES (?,?,?,?,?,?)""", [
    (1,1,"STRELKA",0,"2026-09-10","2026-09-20"),
    (2,1,"Y50",0,"2026-09-10","2026-09-20"),
    (3,2,"STRELKA",0,"2026-09-11",None),
    (4,3,"Y50",0,"2026-09-12",None),
    (5,4,"Y50",0,"2026-09-13",None),
])

k = mod.get_kpis(conn, "2026-09")
assert k.revenue == 24900
assert k.cost == 11000
assert k.avg_check == 12450
assert mod.get_promo_summary(conn, "2026-09")["orders"] == 2
assert mod.get_month_activity(conn, "2026-09").tests_count == 3

# Old migration records must not enter operational analytics.
conn.execute("INSERT INTO orders(order_id,customer_name,is_archived,created_at,is_promo) VALUES (5,'Old',0,'2025-01-01',0)")
conn.execute("INSERT INTO tests(test_id,order_id,test_type,created_at) VALUES (6,5,'Y50','2025-01-01')")
ops = mod.get_operational_kpis(conn)
funnel = mod.get_production_funnel(conn)
assert ops.in_progress == 3  # two commercial + one commercial? exact current rows: test 5 plus promo tests 3/4
assert funnel.created == 5

print("DASHBOARD ITERATION TESTS PASSED")
