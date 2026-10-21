"""
GENOPOISK CRM — вкладка «Дашборд» (Финансы / Статистика / Операционка):
SQL-запросы для владельца/руководителя.

Отдельный репозиторий-модуль (тот же паттерн, что haplogroups_repo.py,
projects_repo.py) — дашборд только читает существующие таблицы
(orders/tests/test_types/test_events/audit_log) плюс новую
dashboard_targets, не меняя основной repository.py.

Определения (зафиксированы явно, чтобы не переделывать метрики позже):
  - "Выручка месяца" (Финансы, KPI и «Экономика по тестам» вместе не
    обязаны совпадать поштучно) — SUM(orders.order_amount) за месяц:
    реальные деньги по заказу целиком.
  - "Экономика по тестам" — количество проданных тестов каждого типа за
    месяц, умноженное на price/cost_price из справочника test_types (а не
    доля от orders.order_amount) — один заказ может включать несколько
    типов тестов, и в БД нет цены на отдельный тест внутри заказа.
  - "Готово к выдаче" (Операционка/воронка) — отдельного поля в БД нет;
    трактуется как lab_profile_received_at заполнено И client_issued_at
    пусто (лабораторный этап пройден, ждёт выдачи).
  - "В лаборатории" (Операционка, KPI) — lab_sent_at заполнено И
    lab_profile_received_at пусто (профиль ещё не готов).
  - "Среднее время выполнения" — по ВСЕМ завершённым тестам (client_issued_at
    заполнено, не архивные), НЕ ограничено выбранным месяцем: за один
    месяц по конкретному типу теста обычно набирается слишком мало
    завершённых тестов для содержательного среднего.
  - "Последние события" — берутся из test_events (создание/этапы
    маршрута теста, раздел ТЗ явно указывает этот источник) плюс
    архивирование заказа отдельно из audit_log, так как архивирование —
    операция над заказом, а не событие теста, и в test_events её нет.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import product_catalog as pcat


OPERATIONAL_START = "2026-08-01"

def _ensure_promo_column(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
    if "is_promo" in cols:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("ALTER TABLE orders ADD COLUMN is_promo INTEGER NOT NULL DEFAULT 0")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _commercial_order_filter(alias: str = "o") -> str:
    return f"{alias}.is_archived = 0 AND COALESCE({alias}.is_promo, 0) = 0 AND COALESCE({alias}.order_amount, 0) > 0"


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def _month_bounds(month: str) -> tuple[str, str]:
    """[start, end) в ISO 'YYYY-MM-DD' — end это первый день следующего месяца."""
    year, mon = (int(x) for x in month.split("-"))
    start = f"{year:04d}-{mon:02d}-01"
    if mon == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{mon + 1:02d}-01"
    return start, end


def _split_month(month: str) -> tuple[int, int]:
    y, m = month.split("-")
    return int(y), int(m)


def last_n_months(n: int = 12, *, end_month: Optional[str] = None) -> list[str]:
    """Список 'YYYY-MM' за последние n месяцев по возрастанию, включая end_month (по умолчанию текущий)."""
    if end_month is None:
        end_month = current_month()
    year, mon = _split_month(end_month)
    months = []
    for i in range(n - 1, -1, -1):
        y, m = year, mon - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")
    return months


# ---------------------------------------------------------------------
# Вкладка «Финансы»
# ---------------------------------------------------------------------

@dataclass
class DashboardKpis:
    revenue: float
    cost: float
    profit: float
    margin_pct: float
    new_orders: int
    avg_check: float


def _pricing_columns_available(conn: sqlite3.Connection) -> bool:
    """True, если test_types.price/cost_price уже существуют на этой БД.
    Миграция _add_test_type_pricing_columns() в db.init_db() добавляет их
    при каждом запуске приложения, так что в норме это всегда True — но
    dashboard_repo не должен падать, если его вызвали на подключении, где
    init_db() почему-то ещё не выполнялся (напр. отдельный тестовый сценарий,
    БД от версии до релиза 1.1.1, открытая в обход обычного main())."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(test_types)")}
    return "price" in cols and "cost_price" in cols


def get_kpis(conn: sqlite3.Connection, month: str) -> DashboardKpis:
    _ensure_promo_column(conn)
    start, end = _month_bounds(month)
    revenue_row = conn.execute(
        f"""SELECT COALESCE(SUM(order_amount), 0) AS revenue, COUNT(*) AS cnt,
                  COUNT(*) AS paid_cnt
           FROM orders o
           WHERE {_commercial_order_filter('o')} AND o.created_at >= ? AND o.created_at < ?""",
        (start, end),
    ).fetchone()
    revenue = revenue_row["revenue"] or 0.0
    new_orders = revenue_row["cnt"] or 0
    paid_orders = revenue_row["paid_cnt"] or 0

    if _pricing_columns_available(conn):
        cost_row = conn.execute(
            f"""SELECT COALESCE(SUM(COALESCE(tt.cost_price, 0)), 0) AS cost
               FROM tests t
               JOIN orders o ON o.order_id = t.order_id
               LEFT JOIN test_types tt ON tt.code = t.test_type
               WHERE t.is_archived = 0 AND {_commercial_order_filter('o')}
                 AND t.created_at >= ? AND t.created_at < ?""",
            (start, end),
        ).fetchone()
        cost = cost_row["cost"] or 0.0
    else:
        cost = 0.0

    profit = revenue - cost
    margin_pct = (profit / revenue * 100) if revenue else 0.0
    avg_check = (revenue / paid_orders) if paid_orders else 0.0
    return DashboardKpis(
        revenue=revenue, cost=cost, profit=profit, margin_pct=margin_pct,
        new_orders=new_orders, avg_check=avg_check,
    )


@dataclass
class TestEconomicsRow:
    code: str
    display_name: str
    sold: int
    price: float
    cost_price: float
    revenue: float
    cost: float
    profit: float


def get_test_economics(conn: sqlite3.Connection, month: str) -> list[TestEconomicsRow]:
    """Экономика по коммерческим тестам; фактическая сумма заказа распределяется
    между тестами заказа пропорционально их каталожной цене."""
    _ensure_promo_column(conn)
    start, end = _month_bounds(month)
    rows = conn.execute(
        f"""SELECT o.order_id, o.order_amount, t.test_type AS code,
                      COALESCE(tt.price, 0) AS price, COALESCE(tt.cost_price, 0) AS cost_price
               FROM tests t
               JOIN orders o ON o.order_id = t.order_id
               LEFT JOIN test_types tt ON tt.code = t.test_type
               WHERE t.is_archived = 0 AND {_commercial_order_filter('o')}
                 AND o.created_at >= ? AND o.created_at < ?
               ORDER BY o.order_id""",
        (start, end),
    ).fetchall()

    by_order: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        by_order.setdefault(r["order_id"], []).append(r)

    agg: dict[str, dict[str, float]] = {}
    for order_rows in by_order.values():
        total_catalog = sum(max(float(r["price"] or 0), 0.0) for r in order_rows)
        shares = []
        for r in order_rows:
            if total_catalog > 0:
                share = float(r["price"] or 0) / total_catalog
            else:
                share = 1.0 / len(order_rows)
            shares.append((r, share))
        for r, share in shares:
            a = agg.setdefault(r["code"], {"sold": 0, "price": float(r["price"] or 0), "cost_price": float(r["cost_price"] or 0), "revenue": 0.0, "cost": 0.0})
            a["sold"] += 1
            a["revenue"] += float(order_rows[0]["order_amount"] or 0) * share
            a["cost"] += float(r["cost_price"] or 0)

    out = []
    for code, a in sorted(agg.items(), key=lambda kv: kv[1]["sold"], reverse=True):
        out.append(TestEconomicsRow(
            code=code, display_name=pcat.get_display_name(code),
            sold=int(a["sold"]), price=a["price"], cost_price=a["cost_price"],
            revenue=a["revenue"], cost=a["cost"], profit=a["revenue"] - a["cost"],
        ))
    return out


def get_revenue_dynamics(conn: sqlite3.Connection, months: int = 12) -> list[tuple[str, float]]:
    _ensure_promo_column(conn)
    result = []
    for month in last_n_months(months):
        start, end = _month_bounds(month)
        row = conn.execute(
            f"SELECT COALESCE(SUM(order_amount), 0) AS revenue FROM orders o WHERE {_commercial_order_filter('o')} AND o.created_at >= ? AND o.created_at < ?",
            (start, end),
        ).fetchone()
        result.append((month, float(row["revenue"] or 0)))
    return result


def get_revenue_structure(conn: sqlite3.Connection, month: str) -> list[tuple[str, str, float]]:
    return [(r.code, r.display_name, r.revenue) for r in get_test_economics(conn, month)]


def get_promo_summary(conn: sqlite3.Connection, month: str) -> dict[str, float]:
    _ensure_promo_column(conn)
    start, end = _month_bounds(month)
    row = conn.execute(
        """SELECT COUNT(DISTINCT o.order_id) AS orders_count,
                  COUNT(t.test_id) AS tests_count,
                  COALESCE(SUM(COALESCE(tt.price, 0)), 0) AS catalog_value
           FROM orders o
           LEFT JOIN tests t ON t.order_id = o.order_id AND t.is_archived = 0
           LEFT JOIN test_types tt ON tt.code = t.test_type
           WHERE o.is_archived = 0 AND COALESCE(o.is_promo, 0) = 1
             AND o.created_at >= ? AND o.created_at < ?""",
        (start, end),
    ).fetchone()
    return {"orders": int(row["orders_count"] or 0), "tests": int(row["tests_count"] or 0), "catalog_value": float(row["catalog_value"] or 0)}



def list_test_type_pricing(conn: sqlite3.Connection) -> list[dict]:
    if _pricing_columns_available(conn):
        rows = conn.execute(
            "SELECT code, display_name, price, cost_price FROM test_types ORDER BY sort_order"
        ).fetchall()
        return [dict(r) for r in rows]
    rows = conn.execute("SELECT code, display_name FROM test_types ORDER BY sort_order").fetchall()
    return [{"code": r["code"], "display_name": r["display_name"], "price": 0.0, "cost_price": 0.0} for r in rows]


def update_test_type_pricing(conn: sqlite3.Connection, code: str, *, price: float, cost_price: float) -> None:
    if not _pricing_columns_available(conn):
        # Колонки ещё не мигрированы на этой БД — тихо игнорируем вместо
        # падения на "no such column", как и было до релиза 1.1.1.
        return
    conn.execute(
        "UPDATE test_types SET price = ?, cost_price = ? WHERE code = ?",
        (price, cost_price, code),
    )


# ---------------------------------------------------------------------
# Вкладка «Статистика»
# ---------------------------------------------------------------------

@dataclass
class MonthActivity:
    orders_count: int
    tests_count: int
    issued_count: int
    new_clients_count: int


def get_month_activity(conn: sqlite3.Connection, month: str) -> MonthActivity:
    _ensure_promo_column(conn)
    start, end = _month_bounds(month)
    orders_row = conn.execute(
        f"""SELECT COUNT(*) AS c, COUNT(DISTINCT customer_name) AS clients
           FROM orders o WHERE {_commercial_order_filter('o')} AND o.created_at >= ? AND o.created_at < ?""",
        (start, end),
    ).fetchone()
    tests_count = conn.execute(
        f"""SELECT COUNT(*) AS c FROM tests t JOIN orders o ON o.order_id=t.order_id
           WHERE t.is_archived=0 AND {_commercial_order_filter('o')} AND t.created_at >= ? AND t.created_at < ?""",
        (start, end),
    ).fetchone()["c"]
    issued_count = conn.execute(
        f"""SELECT COUNT(*) AS c FROM tests t JOIN orders o ON o.order_id=t.order_id
           WHERE t.is_archived=0 AND {_commercial_order_filter('o')} AND t.client_issued_at >= ? AND t.client_issued_at < ?""",
        (start, end),
    ).fetchone()["c"]
    return MonthActivity(
        orders_count=orders_row["c"], tests_count=tests_count,
        issued_count=issued_count, new_clients_count=orders_row["clients"],
    )


def get_sales_by_test_type(conn: sqlite3.Connection, month: str) -> list[tuple[str, str, int]]:
    _ensure_promo_column(conn)
    start, end = _month_bounds(month)
    rows = conn.execute(
        f"""SELECT t.test_type, COUNT(*) AS cnt
           FROM tests t JOIN orders o ON o.order_id=t.order_id
           WHERE t.is_archived=0 AND {_commercial_order_filter('o')}
             AND t.created_at >= ? AND t.created_at < ?
           GROUP BY t.test_type""",
        (start, end),
    ).fetchall()
    return [(r["test_type"], pcat.get_display_name(r["test_type"]), r["cnt"]) for r in rows]


@dataclass
class TurnaroundRow:
    code: str
    display_name: str
    avg_days: float
    median_days: float
    count: int
    min_days: float
    max_days: float


def get_avg_turnaround(conn: sqlite3.Connection) -> list[TurnaroundRow]:
    import statistics
    agg_rows = conn.execute(
        """SELECT t.test_type AS code,
                  AVG(julianday(t.client_issued_at) - julianday(t.created_at)) AS avg_d,
                  COUNT(*) AS cnt,
                  MIN(julianday(t.client_issued_at) - julianday(t.created_at)) AS min_d,
                  MAX(julianday(t.client_issued_at) - julianday(t.created_at)) AS max_d
           FROM tests t
           LEFT JOIN test_types tt ON tt.code = t.test_type
           WHERE t.is_archived = 0 AND t.client_issued_at IS NOT NULL
             AND t.created_at >= ?
             AND julianday(t.client_issued_at) >= julianday(t.created_at)
             AND COALESCE(tt.requires_lab, 1) = 1
           GROUP BY t.test_type ORDER BY avg_d DESC""",
        (OPERATIONAL_START,),
    ).fetchall()
    raw_rows = conn.execute(
        """SELECT t.test_type AS code, julianday(t.client_issued_at)-julianday(t.created_at) AS days
           FROM tests t LEFT JOIN test_types tt ON tt.code=t.test_type
           WHERE t.is_archived=0 AND t.client_issued_at IS NOT NULL
             AND t.created_at >= ? AND julianday(t.client_issued_at) >= julianday(t.created_at)
             AND COALESCE(tt.requires_lab,1)=1""",
        (OPERATIONAL_START,),
    ).fetchall()
    days_by_code: dict[str,list[float]] = {}
    for r in raw_rows:
        if r["days"] is not None:
            days_by_code.setdefault(r["code"], []).append(r["days"])
    return [TurnaroundRow(
        code=r["code"], display_name=pcat.get_display_name(r["code"]),
        avg_days=r["avg_d"] or 0.0, median_days=statistics.median(days_by_code[r["code"]]) if days_by_code.get(r["code"]) else 0.0,
        count=r["cnt"], min_days=r["min_d"] or 0.0, max_days=r["max_d"] or 0.0,
    ) for r in agg_rows]


def get_targets(conn: sqlite3.Connection, month: str) -> dict:
    year, mon = _split_month(month)
    row = conn.execute(
        "SELECT * FROM dashboard_targets WHERE year = ? AND month = ?", (year, mon)
    ).fetchone()
    if row is None:
        return {"target_orders": 0, "target_tests": 0, "target_issued": 0, "target_revenue": 0}
    return {
        "target_orders": row["target_orders"],
        "target_tests": row["target_tests"],
        "target_issued": row["target_issued"],
        "target_revenue": row["target_revenue"],
    }


def upsert_targets(
    conn: sqlite3.Connection, month: str, *,
    target_orders: int, target_tests: int, target_issued: int, target_revenue: int = 0,
) -> None:
    year, mon = _split_month(month)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO dashboard_targets
               (year, month, target_orders, target_tests, target_issued, target_revenue)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(year, month) DO UPDATE SET
                 target_orders = excluded.target_orders,
                 target_tests = excluded.target_tests,
                 target_issued = excluded.target_issued,
                 target_revenue = excluded.target_revenue""",
            (year, mon, target_orders, target_tests, target_issued, target_revenue),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


@dataclass
class RevenueForecast:
    plan: float
    fact: float
    forecast: float
    completion_pct: float  # прогноз / план × 100 — темп относительно плана


def get_revenue_forecast(conn: sqlite3.Connection, month: str) -> RevenueForecast:
    """
    Прогноз = факт_выручки / прошедшие_дни_месяца × дней_в_месяце (раздел
    ТЗ v2). Для месяца, отличного от текущего, "прошедшие дни" — это весь
    месяц целиком (он уже закончился, прогнозировать нечего — прогноз
    совпадает с фактом).
    """
    import calendar

    year, mon = _split_month(month)
    days_in_month = calendar.monthrange(year, mon)[1]

    today = date.today()
    if year == today.year and mon == today.month:
        elapsed_days = today.day
    else:
        elapsed_days = days_in_month

    kpi = get_kpis(conn, month)
    fact = kpi.revenue
    forecast = (fact / elapsed_days * days_in_month) if elapsed_days else fact

    targets = get_targets(conn, month)
    plan = targets["target_revenue"]
    completion_pct = (forecast / plan * 100) if plan else 0.0

    return RevenueForecast(plan=plan, fact=fact, forecast=forecast, completion_pct=completion_pct)


@dataclass
class PlanFact:
    orders_fact: int
    orders_plan: int
    tests_fact: int
    tests_plan: int
    issued_fact: int
    issued_plan: int


def get_plan_fact(conn: sqlite3.Connection, month: str) -> PlanFact:
    activity = get_month_activity(conn, month)
    targets = get_targets(conn, month)
    return PlanFact(
        orders_fact=activity.orders_count, orders_plan=targets["target_orders"],
        tests_fact=activity.tests_count, tests_plan=targets["target_tests"],
        issued_fact=activity.issued_count, issued_plan=targets["target_issued"],
    )



# ---------------------------------------------------------------------
# Вкладка «Операционка»
# ---------------------------------------------------------------------

@dataclass
class OperationalKpis:
    in_progress: int
    in_lab: int
    ready_to_issue: int
    overdue: int


def get_operational_kpis(conn: sqlite3.Connection) -> OperationalKpis:
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN t.client_issued_at IS NULL THEN 1 ELSE 0 END) AS in_progress,
             SUM(CASE WHEN t.lab_sent_at IS NOT NULL AND t.lab_profile_received_at IS NULL THEN 1 ELSE 0 END) AS in_lab,
             SUM(CASE WHEN t.lab_profile_received_at IS NOT NULL AND t.client_issued_at IS NULL THEN 1 ELSE 0 END) AS ready_to_issue,
             SUM(CASE WHEN t.client_issued_at IS NULL AND t.deadline_date IS NOT NULL AND t.deadline_date < ? THEN 1 ELSE 0 END) AS overdue
           FROM tests t JOIN orders o ON o.order_id=t.order_id
           LEFT JOIN test_types tt ON tt.code=t.test_type
           WHERE t.is_archived=0 AND o.is_archived=0 AND t.created_at >= ?
             AND COALESCE(tt.requires_lab,1)=1""",
        (today, OPERATIONAL_START),
    ).fetchone()
    return OperationalKpis(
        in_progress=row["in_progress"] or 0, in_lab=row["in_lab"] or 0,
        ready_to_issue=row["ready_to_issue"] or 0, overdue=row["overdue"] or 0,
    )


@dataclass
class FunnelCounts:
    created: int
    sample_received: int
    in_lab: int
    profile_received: int
    ready_to_issue: int
    issued: int


def get_production_funnel(conn: sqlite3.Connection) -> FunnelCounts:
    row = conn.execute(
        """SELECT COUNT(*) AS created,
             SUM(CASE WHEN sample_received_at IS NOT NULL THEN 1 ELSE 0 END) AS sample_received,
             SUM(CASE WHEN lab_sent_at IS NOT NULL THEN 1 ELSE 0 END) AS in_lab,
             SUM(CASE WHEN lab_profile_received_at IS NOT NULL THEN 1 ELSE 0 END) AS profile_received,
             SUM(CASE WHEN lab_profile_received_at IS NOT NULL AND client_issued_at IS NULL THEN 1 ELSE 0 END) AS ready_to_issue,
             SUM(CASE WHEN client_issued_at IS NOT NULL THEN 1 ELSE 0 END) AS issued
           FROM tests t JOIN orders o ON o.order_id=t.order_id
           LEFT JOIN test_types tt ON tt.code=t.test_type
           WHERE t.is_archived=0 AND o.is_archived=0 AND t.created_at >= ?
             AND COALESCE(tt.requires_lab,1)=1""",
        (OPERATIONAL_START,),
    ).fetchone()
    return FunnelCounts(created=row["created"] or 0, sample_received=row["sample_received"] or 0,
        in_lab=row["in_lab"] or 0, profile_received=row["profile_received"] or 0,
        ready_to_issue=row["ready_to_issue"] or 0, issued=row["issued"] or 0)


def get_overdue_tests(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    today=date.today().isoformat()
    return conn.execute(
        """SELECT t.test_id,t.gns_number,t.test_type,t.deadline_date,o.customer_name
           FROM tests t JOIN orders o ON o.order_id=t.order_id LEFT JOIN test_types tt ON tt.code=t.test_type
           WHERE t.is_archived=0 AND o.is_archived=0 AND t.created_at >= ?
             AND t.client_issued_at IS NULL AND t.deadline_date IS NOT NULL AND t.deadline_date < ?
             AND COALESCE(tt.requires_lab,1)=1 ORDER BY t.deadline_date ASC""",
        (OPERATIONAL_START,today),
    ).fetchall()


def get_stuck_tests(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.test_id,t.gns_number,t.test_type,t.created_at
           FROM tests t JOIN orders o ON o.order_id=t.order_id LEFT JOIN test_types tt ON tt.code=t.test_type
           WHERE t.is_archived=0 AND o.is_archived=0 AND t.created_at >= ?
             AND t.client_issued_at IS NULL AND COALESCE(tt.requires_lab,1)=1
           ORDER BY t.created_at ASC LIMIT ?""",
        (OPERATIONAL_START,limit),
    ).fetchall()


_EVENT_LINE_LABELS = {
    "order_created": "Создан заказ",
    "dispatched": "Отправлен",
    "received": "Получен образец",
    "handed_to_lab": "Передано в лабораторию",
    "profile_received": "Получен профиль",
    "in_progress": "Взято в работу",
    "issued": "Выдан результат",
}


def get_recent_events(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """
    Последние N событий маршрута теста — из test_events, как явно указано в
    ТЗ. Плюс архивирование заказа (audit_log, т.к. это операция над
    заказом, а не тестом, и в test_events её нет) — без этого блок не
    покрывал бы пример из ТЗ "15:13 Архивирован заказ".
    """
    event_rows = conn.execute(
        """SELECT te.event_time AS ts, te.event_type AS event_type, t.gns_number AS gns
           FROM test_events te JOIN tests t ON t.test_id = te.test_id
           WHERE te.event_time >= ?
           ORDER BY te.event_time DESC LIMIT ?""",
        (OPERATIONAL_START, limit),
    ).fetchall()

    archive_rows = conn.execute(
        """SELECT timestamp AS ts, entity_id AS order_id
           FROM audit_log
           WHERE entity = 'order' AND field = 'is_archived' AND timestamp >= ?
           ORDER BY timestamp DESC LIMIT ?""",
        (OPERATIONAL_START, limit),
    ).fetchall()
    order_ids = {r["order_id"] for r in archive_rows}
    order_no_by_id: dict[int, str] = {}
    if order_ids:
        placeholders = ",".join("?" * len(order_ids))
        for r in conn.execute(
            f"SELECT order_id, order_no FROM orders WHERE order_id IN ({placeholders})", list(order_ids)
        ):
            order_no_by_id[r["order_id"]] = r["order_no"] or str(r["order_id"])

    combined = []
    for r in event_rows:
        label = _EVENT_LINE_LABELS.get(r["event_type"], r["event_type"])
        text = f"{label} — {r['gns']}" if r["event_type"] != "order_created" else f"{label} ({r['gns']})"
        combined.append((r["ts"], text))
    for r in archive_rows:
        order_no = order_no_by_id.get(r["order_id"], str(r["order_id"]))
        combined.append((r["ts"], f"Архивирован заказ №{order_no}"))

    combined.sort(key=lambda x: x[0] or "", reverse=True)
    result = []
    for ts, text in combined[:limit]:
        ts = ts or ""
        time_label = ts[11:16] if len(ts) >= 16 else ts
        result.append({"time": time_label, "text": text})
    return result
