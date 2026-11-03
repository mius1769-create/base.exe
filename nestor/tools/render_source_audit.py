"""Генерирует docs/SCIENTIFIC_SOURCES_AUDIT.md из data/source_audit.json и docs/QC_SUMMARY.json.

  py -3 tools/render_source_audit.py          # перезаписать отчёт
  py -3 tools/render_source_audit.py --check  # проверить, что отчёт актуален
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "data" / "source_audit.json"
QC = ROOT / "docs" / "QC_SUMMARY.json"
RULES = ROOT / "data" / "transform_rules.json"
OUT = ROOT / "docs" / "SCIENTIFIC_SOURCES_AUDIT.md"

SCENARIOS = [("local_closed_prototype", "Локальный закрытый прототип"),
             ("genealogical_matching", "Сопоставление с профилями клиентов"),
             ("public_distribution", "Публичное распространение")]


def short(name: str) -> str:
    return name.replace("Scientific_", "")


def render() -> str:
    a = json.loads(AUDIT.read_text(encoding="utf-8"))
    qc = json.loads(QC.read_text(encoding="utf-8"))
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    L = []
    L.append("# Аудит научных источников кандидата `Nestor_scientific_YSTR.db`\n")
    L.append(f"Сгенерировано `tools/render_source_audit.py` из `data/source_audit.json` и "
             f"`docs/QC_SUMMARY.json`. Дата аудита: {a['audit_date']}. Не редактировать вручную.\n")
    c = a["candidate"]
    L.append(f"Кандидат: `{c['file']}`, {c['records']} записей, SHA-256 `{c['sha256']}`. {c['note']}\n")
    L.append("## Правила аудита\n")
    for v in a["rules"].values():
        L.append(f"* {v}")
    L.append("* Из сессии закрыты сайты издателей, PMC и NIST: условия установлены по вторичным "
             "записям; поле «подтверждено» везде `нет`, пока первичная страница не прочитана.\n")

    L.append("## Таблица решений\n")
    L.append("| Источник | Записей | Исходная таблица | Права на повторное использование набора | Атрибуция | Качество данных (QC) | Генеалогический поиск | Статус |")
    L.append("|---|---:|---|---|---|---|---|---|")
    for s in a["sources"]:
        terms = s["dataset"]["dataset_terms"]
        rights = terms["statement"] + (" Подтверждено: да." if terms["confirmed"] else " Подтверждено: нет.")
        q = qc["by_source"].get(s["source"], {})
        qc_txt = ", ".join(f"{k}: {v}" for k, v in q.get("records_affected", {}).items()) or "построчных находок нет"
        src_level = [f"{x['check']} {x['locus']}" for x in q.get("source_level", []) if x["check"] != "Q07"]
        if src_level:
            qc_txt += "; на уровне источника: " + ", ".join(src_level)
        match = s["scenarios"]["genealogical_matching"]
        L.append(f"| {short(s['source'])} | {s['records']} | {s['dataset']['table']} (`{s['dataset']['raw_file']}`) "
                 f"| {rights} | {s['attribution']} | {qc_txt} | {match['verdict']}: {match['basis']} | **{s['decision']}**{(' — ' + s['status_detail']) if s.get('status_detail') else ''} |")
    L.append("")
    summ = a["summary"]
    L.append("Итого: " + "; ".join(f"{k} — {v} записей" for k, v in summ.items()) + ". "
             "Ни один источник не подключён к пользовательскому поиску; импорт в справочник не выполнялся.\n")

    L.append("## Сценарии использования\n")
    L.append("| Источник | " + " | ".join(t for _, t in SCENARIOS) + " |")
    L.append("|---|" + "---|" * len(SCENARIOS))
    for s in a["sources"]:
        cells = [f"{s['scenarios'][k]['verdict']} — {s['scenarios'][k]['basis']}" for k, _ in SCENARIOS]
        L.append(f"| {short(s['source'])} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## По источникам\n")
    for s in a["sources"]:
        d = s["dataset"]
        L.append(f"### {short(s['source'])}\n")
        L.append(f"* **Публикация:** {s['citation']} doi:{s['doi']}")
        L.append(f"* **Набор данных:** {d['table']}, файл `{d['raw_file']}`; первичное место: {d['primary_location']}")
        if s.get("provenance"):
            pv = s["provenance"]
            L.append(f"* **Происхождение и состав:** {pv['statement']}")
            for e in pv["evidence"]:
                L.append(f"  * [{e['kind']}]({e['url']}): {e['text']}")
            if pv.get("group_totals"):
                g = pv["group_totals"]
                L.append("  * Численность групп (" + g["basis"] + "): "
                         + ", ".join(f"{k} {v}" for k, v in g["counts"].items()) + f"; всего {g['total']}. {g['level']}.")
            L.append(f"  * Построчная сверка: {pv['row_level_reconciliation']}")
        if s.get("catalog_level"):
            L.append(f"* **Уровень каталога:** {s['catalog_level']['statement']} ([Data.gov]({s['catalog_level']['url']}))")
        L.append(f"* **Условия набора:** {d['dataset_terms']['statement']}")
        for e in d["dataset_terms"].get("evidence", []):
            L.append(f"  * [{e['kind']}]({e['url']}): {e['text']}")
        L.append(f"  * Проверить: {d['dataset_terms']['to_confirm']}")
        at = s["article_terms"]
        L.append(f"* **Условия статьи** (не переносятся на набор автоматически): {at['statement']}")
        for e in at["evidence"]:
            L.append(f"  * [{e['kind']}]({e['url']}): «{e['text']}»")
        if at.get("primary_to_confirm"):
            L.append("  * Первичные страницы: " + ", ".join(at["primary_to_confirm"]))
        L.append(f"* **Атрибуция:** {s['attribution']}")
        L.append(f"* **Согласие доноров:** {s['consent_scope']}")
        L.append("* **Качество (сырые значения не менялись):**")
        for item in s["quality"]:
            L.append(f"  * {item}")
        detail = f" ({s['status_detail']})" if s.get("status_detail") else ""
        L.append(f"* **Решение:** {s['decision']}{detail}. Нужно: " + "; ".join(s["needed"]) + "\n")

    L.append("## QC: коды проверок\n")
    for code, name in qc["checks"].items():
        L.append(f"* `{code}` {name}")
    L.append("\nПострочные находки с исходными значениями генерируются локально "
             "(`tools/qc_reference.py --details var/qc_details.csv`) и в git не кладутся: "
             "они содержат данные источников, условия которых не подтверждены.\n")

    L.append("## Предложенные преобразования (не применены)\n")
    L.append("| Правило | Что делает | Основание | Статус |")
    L.append("|---|---|---|---|")
    for r in rules["rules"]:
        L.append(f"| `{r['rule_id']}` | {r['description']} | {r['basis']} | {r['status']} |")
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        if OUT.read_text(encoding="utf-8") != text:
            print("docs/SCIENTIFIC_SOURCES_AUDIT.md устарел: запустите tools/render_source_audit.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
