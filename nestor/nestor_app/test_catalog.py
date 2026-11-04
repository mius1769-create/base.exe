"""Локальный тестовый научный каталог NeSToR (только для локального тестирования).

Собирается из двух научных снимков: кандидата Nestor_scientific_YSTR.db и
reference/scientific.sqlite из проверенного архива. Хранится в отдельной базе
var/test_catalog/nestor_test_catalog.db — не в пользовательской базе и не в
научном справочнике (data/MANIFEST.json не создаётся). Включается отдельным
флагом var/test_catalog/ENABLED; выключается и удаляется командами
tools/build_test_catalog.py disable / remove.

Правила сборки:
  * только научные неперсональные записи; личные профили, FTDNA-выгрузки и
    GenopoiskGD не используются (их нет во входных снимках, источники проверяются);
  * у каждой записи — снимок, источник, публикация, sample ID, файл/лист/строка,
    шкала аллелей, лицензия, статус проверки; у непроверенных — пометка
    «локальное тестирование; право на повторное использование не подтверждено»;
  * user_scientific_since_20261008 — агрегированные гаплотипные наблюдения
    (record_kind = aggregated, observed_n = N из источника), а не отдельные люди;
    пересечения с публикациями помечаются;
  * совпадение гаплотипов не повод сливать строки; общие источники обоих снимков
    (Purps 2014, NIST 1032) берутся один раз — из архива (подробнее происхождение),
    только если наборы профилей совпадают полностью; иначе обе копии остаются
    с пометкой; коллизии ID и все разные наблюдения сохраняются;
  * сравнение с каталогом всегда помечается предварительным: шкалы источников
    не откалиброваны (T15), и непроверенные данные маркируются в результатах.
"""

from __future__ import annotations

import collections
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import markers as mk
from .gd import gd_view, genetic_distance

CATALOG_DIRNAME = "test_catalog"
CATALOG_FILE = "nestor_test_catalog.db"
FLAG_FILE = "ENABLED"
PURPOSE = "локальное тестирование; не публикуется; не научный справочник NeSToR"
UNVERIFIED_NOTE = "локальное тестирование; право на повторное использование не подтверждено"
AGGREGATED_SOURCES = {"user_scientific_since_20261008"}
SHARED = {"Scientific_Purps2014_PPY23": "purps2014", "Scientific_NIST1032_UAS24": "nist2022"}
SINCE_LABEL_TO_CANDIDATE = {"Balanovsky 2011": "Scientific_Balanovsky2011_Caucasus",
                            "Roewer 2008": "Scientific_Roewer2008_WesternRussia"}
NIST_BLUE = "FF0070C0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
    source_id          TEXT PRIMARY KEY,
    snapshot           TEXT NOT NULL,          -- candidate | archive
    title              TEXT,
    publication        TEXT,
    doi                TEXT,
    url                TEXT,
    license            TEXT,
    verification_status TEXT NOT NULL,
    reuse_note         TEXT NOT NULL,
    record_kind        TEXT NOT NULL CHECK (record_kind IN ('individual','aggregated')),
    records            INTEGER NOT NULL,
    observed_total     INTEGER NOT NULL,
    dedup_note         TEXT,
    metadata_json      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    id               INTEGER PRIMARY KEY,
    source_id        TEXT NOT NULL REFERENCES sources(source_id),
    snapshot         TEXT NOT NULL,
    source_sample_id TEXT NOT NULL,
    source_file      TEXT,
    source_sheet     TEXT,
    source_row       INTEGER,
    population       TEXT,
    country          TEXT,
    haplogroup       TEXT,
    marker_scale     TEXT,
    record_kind      TEXT NOT NULL CHECK (record_kind IN ('individual','aggregated')),
    observed_n       INTEGER NOT NULL,
    raw_markers_json TEXT NOT NULL,            -- как в снимке
    positions_json   TEXT NOT NULL,            -- {локус: [значение, статус]} для сравнения
    flags_json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_records_source ON records(source_id);
"""


class CatalogError(RuntimeError):
    pass


def catalog_dir(var_dir: Path) -> Path:
    return Path(var_dir) / CATALOG_DIRNAME


def catalog_path(var_dir: Path) -> Path:
    return catalog_dir(var_dir) / CATALOG_FILE


def is_enabled(var_dir: Path) -> bool:
    d = catalog_dir(var_dir)
    return (d / FLAG_FILE).exists() and (d / CATALOG_FILE).exists()


def enable(var_dir: Path) -> None:
    if not catalog_path(var_dir).exists():
        raise CatalogError("каталог не собран: сначала tools/build_test_catalog.py build")
    (catalog_dir(var_dir) / FLAG_FILE).write_text(PURPOSE + "\n", encoding="utf-8")


def disable(var_dir: Path) -> None:
    flag = catalog_dir(var_dir) / FLAG_FILE
    if flag.exists():
        flag.unlink()


def remove(var_dir: Path) -> None:
    """Полностью удалить каталог (база, WAL, флаг) из папки приложения."""
    d = catalog_dir(var_dir)
    if d.exists():
        shutil.rmtree(d)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _canon(name: str) -> str:
    try:
        return mk.canonical_name(name)[0]
    except mk.MarkerError:
        return name


def _positions_from_candidate(markers: dict) -> dict:
    out = {}
    for k, v in markers.items():
        name = _canon(k)
        vals = v if isinstance(v, list) else [v]
        if vals and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in vals):
            out[name] = tuple(sorted(float(x) for x in vals))
        elif not vals or vals == [None]:
            out[name] = None
        else:
            out[name] = mk.Invalid(json.dumps(v, ensure_ascii=False))   # строки, нули — не сравниваются
    return out


def _positions_from_archive(calls: list) -> dict:
    out = {}
    for marker, alleles_json, status in calls:
        name = _canon(marker)
        if status == "observed":
            vals = json.loads(alleles_json) if alleles_json else None
            out[name] = tuple(sorted(float(x) for x in vals)) if vals else None
        elif status == "not_read":
            out[name] = None
        else:
            out[name] = mk.Invalid(status)
    return out


def _storage(positions: dict) -> str:
    return json.dumps({k: list(mk.to_storage(v)) for k, v in positions.items()}, ensure_ascii=False)


def _fingerprint(positions: dict) -> str:
    return mk.canonical_string({k: v for k, v in positions.items() if mk.is_observed(v)})


def _raw_fingerprint(raw: dict) -> str:
    """Отпечаток опубликованных значений (без QC-статусов) — для проверки, что копии источника одинаковы."""
    norm = {}
    for k, v in raw.items():
        if v is None:
            continue
        vals = v if isinstance(v, list) else [v]
        norm[_canon(k)] = sorted(json.dumps(x) for x in vals)
    return json.dumps(norm, sort_keys=True)


def _audit_status(audit: dict) -> dict:
    out = {}
    for s in audit.get("sources", []):
        status = s.get("decision", "не проверено")
        if s.get("status_detail"):
            status += f" ({s['status_detail']})"
        out[s["source"]] = {"status": status,
                            "license": s.get("dataset", {}).get("dataset_terms", {}).get("statement", "")}
    return out


def build(candidate_db: Path, archive_db: Path, out_path: Path, audit_path: Path | None = None) -> dict:
    """Собрать каталог. Входные снимки открываются только на чтение. Возвращает сводку."""
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8")) if audit_path and Path(audit_path).exists() else {}
    status_by_candidate = _audit_status(audit)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    cand, arch = _ro(candidate_db), _ro(archive_db)
    try:
        # ---------- чтение кандидата ----------
        cand_meta = {r["source"]: dict(r) for r in cand.execute("SELECT * FROM source_metadata")}
        cand_rows = collections.defaultdict(list)
        for r in cand.execute("SELECT id, name, haplogroup, country, source, markers FROM samples"):
            raw = json.loads(r["markers"])
            cand_rows[r["source"]].append((dict(r), raw, _positions_from_candidate(raw)))
        # ---------- чтение архива ----------
        arch_meta = {r["source_id"]: json.loads(r["metadata_json"]) for r in arch.execute("SELECT * FROM sources")}
        calls = collections.defaultdict(list)
        for pid, marker, alleles, status in arch.execute("SELECT profile_id, marker, alleles_json, status FROM marker_calls"):
            calls[pid].append((marker, alleles, status))
        arch_rows = collections.defaultdict(list)
        for r in arch.execute("SELECT * FROM profiles"):
            arch_rows[r["source_id"]].append((dict(r), _positions_from_archive(calls.get(r["id"], []))))
        labels = {}
        for r in arch.execute("SELECT source_id, reference_label, verification_status FROM source_reference_labels"):
            labels[(r["source_id"], r["reference_label"])] = r["verification_status"]
    finally:
        cand.close()
        arch.close()

    # ---------- общие источники: снять повторное копирование ----------
    dedup = {}
    for c_src, a_src in SHARED.items():
        if c_src in cand_rows and a_src in arch_rows:
            # одинаковость копий — по опубликованным значениям; QC-статусы архива (например
            # copy_count_requires_review) на сравнение копий не влияют, но остаются в позициях сравнения
            fa = collections.Counter(_raw_fingerprint(json.loads(r["markers_json"])) for r, _ in arch_rows[a_src])
            fc = collections.Counter(_raw_fingerprint(raw) for _, raw, _ in cand_rows[c_src])
            dedup[c_src] = {"archive_source": a_src, "identical": fa == fc,
                            "candidate_records": len(cand_rows[c_src]), "archive_records": len(arch_rows[a_src])}

    # ---------- пересечения Since с публикациями кандидата ----------
    cand_fp = {src: {_fingerprint(p) for _, _, p in rows} for src, rows in cand_rows.items()}

    def since_overlap(label: str, positions: dict) -> str | None:
        c_src = SINCE_LABEL_TO_CANDIDATE.get(label)
        if not c_src or c_src not in cand_rows:
            return None
        keys = [k for k, v in positions.items() if mk.is_observed(v)]
        target = mk.canonical_string({k: positions[k] for k in keys})
        for _, _, p in cand_rows[c_src]:
            view = dict(p)
            if "DYS389B" not in view and mk.is_observed(view.get("DYS389II")) and mk.is_observed(view.get("DYS389I")):
                view["DYS389B"] = (view["DYS389II"][0] - view["DYS389I"][0],)
            if all(k in view for k in keys) and mk.canonical_string({k: view[k] for k in keys}) == target:
                return c_src
        return None

    con = sqlite3.connect(out_path)
    con.executescript(SCHEMA)
    stats = {"sources": 0, "records": 0, "individual_records": 0, "aggregated_records": 0, "aggregated_observations": 0,
             "dedup": dedup, "skipped_duplicate_copies": 0, "id_collisions": 0, "since_overlaps": collections.Counter(),
             "unverified_sources": [], "by_source": {}}

    def add_source(source_id, snapshot, meta, kind, rows_n, obs_n, status, dedup_note=None):
        verified = status.startswith(("допущен",))
        note = PURPOSE if verified else UNVERIFIED_NOTE
        if not verified:
            stats["unverified_sources"].append(source_id)
        con.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            source_id, snapshot, meta.get("title"), meta.get("publication") or meta.get("citation"),
            meta.get("doi"), meta.get("article_url") or meta.get("url"), meta.get("license"),
            status, note, kind, rows_n, obs_n, dedup_note, json.dumps(meta, ensure_ascii=False, default=str)))
        stats["sources"] += 1
        stats["by_source"][source_id] = {"snapshot": snapshot, "records": rows_n, "observations": obs_n,
                                         "kind": kind, "status": status}

    # архив: все источники
    for a_src, rows in arch_rows.items():
        meta = arch_meta.get(a_src, {})
        kind = "aggregated" if a_src in AGGREGATED_SOURCES else "individual"
        cand_equiv = next((c for c, a in SHARED.items() if a == a_src), None)
        status = status_by_candidate.get(cand_equiv, {}).get("status") if cand_equiv else None
        status = status or "не проверено"
        obs_total = 0
        for r, positions in rows:
            m = json.loads(r["metadata_json"] or "{}")
            flags = []
            if m.get("source_identifier_collision_requires_review"):
                flags.append("коллизия ID в источнике: запись сохранена отдельно")
                stats["id_collisions"] += 1
            if (m.get("sample_font_colour") or {}).get("value") == NIST_BLUE:
                flags.append("father_son_substitution: вызовы отца вместо сына (T08)")
            n = 1
            if kind == "aggregated":
                try:
                    n = int(float(m.get("source_N") or 1))
                except (TypeError, ValueError):
                    n = 1
                label = m.get("source_reference", "")
                ver = labels.get((a_src, label))
                flags.append(f"агрегированное наблюдение: N={n}; ссылка «{label}» ({ver or 'статус ссылки неизвестен'})")
                hit = since_overlap(label, positions)
                if hit:
                    flags.append(f"гаплотип совпадает с записью источника {hit} в каталоге — возможное пересечение публикаций")
                    stats["since_overlaps"][hit] += 1
            obs_total += n
            con.execute("""INSERT INTO records(source_id, snapshot, source_sample_id, source_file, source_sheet, source_row,
                           population, country, haplogroup, marker_scale, record_kind, observed_n, raw_markers_json,
                           positions_json, flags_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                a_src, "archive", r["source_sample_id"], r["source_file"], r["source_sheet"], r["source_row"],
                r["population"], r["country"], r["haplogroup"], r["marker_scale"], kind, n, r["markers_json"],
                _storage(positions), json.dumps(flags, ensure_ascii=False)))
            stats["records"] += 1
            stats["aggregated_records" if kind == "aggregated" else "individual_records"] += 1
            if kind == "aggregated":
                stats["aggregated_observations"] += n
        note = None
        if cand_equiv and dedup.get(cand_equiv, {}).get("identical"):
            note = f"копия этого источника в снимке-кандидате ({cand_equiv}) совпадает полностью и не добавлена повторно"
        add_source(a_src, "archive", meta, kind, len(rows), obs_total, status, note)

    # кандидат: источники, которых нет в архиве (и общие — если копии различаются)
    for c_src, rows in cand_rows.items():
        if c_src in dedup and dedup[c_src]["identical"]:
            stats["skipped_duplicate_copies"] += len(rows)
            continue
        meta = dict(cand_meta.get(c_src, {}))
        meta.setdefault("title", c_src)
        status = status_by_candidate.get(c_src, {}).get("status", "не проверено")
        note = None
        if c_src in dedup:
            note = f"копия отличается от {dedup[c_src]['archive_source']} в архиве — обе сохранены"
        for r, raw, positions in rows:
            con.execute("""INSERT INTO records(source_id, snapshot, source_sample_id, source_file, source_sheet, source_row,
                           population, country, haplogroup, marker_scale, record_kind, observed_n, raw_markers_json,
                           positions_json, flags_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                c_src, "candidate", r["id"], meta.get("raw_file"), None, None, r["country"], r["country"],
                r["haplogroup"], "as published (кандидат)", "individual", 1, json.dumps(raw, ensure_ascii=False),
                _storage(positions), json.dumps(["лист и строка в снимке-кандидате не хранятся"], ensure_ascii=False)))
            stats["records"] += 1
            stats["individual_records"] += 1
        add_source(c_src, "candidate", meta, "individual", len(rows), len(rows), status, note)

    stats["since_overlaps"] = dict(stats["since_overlaps"])
    meta = {"purpose": PURPOSE, "candidate_sha256": _sha256(candidate_db), "archive_sha256": _sha256(archive_db),
            "summary": json.dumps({k: v for k, v in stats.items() if k != "by_source"}, ensure_ascii=False)}
    con.executemany("INSERT INTO catalog_meta VALUES (?,?)", meta.items())
    con.commit()
    con.close()
    stats["candidate_sha256"], stats["archive_sha256"] = meta["candidate_sha256"], meta["archive_sha256"]
    return stats


# ---------- поиск ----------

@dataclass(frozen=True)
class CatalogMatch:
    source_id: str
    sample_id: str
    population: str | None
    record_kind: str
    observed_n: int
    gd: int
    compared: int
    panel_overlap: int
    verification_status: str
    reuse_note: str
    flags: tuple
    license: str = ""
    quality: tuple = ()        # позиции записи, не вошедшие в сравнение: (локус, причина / QC-статус)
    preliminary: bool = True   # шкалы источников не откалиброваны (T15)
    haplogroup: str | None = None
    country: str | None = None
    differences: tuple = ()    # (локус, значение запроса, значение записи, шаги | причина) — вклад в GD и исключённые
    not_compared: dict = field(default_factory=dict, compare=False)   # категория → число позиций
    source_title: str = ""
    publication: str = ""
    doi: str = ""


@dataclass(frozen=True)
class _Rec:
    source_id: str
    sample_id: str
    population: str | None
    kind: str
    n: int
    positions: dict
    flags: tuple
    haplogroup: str | None
    country: str | None


def _fmt(v) -> str:
    return mk.format_value(v) if mk.is_observed(v) else ("—" if v is None else str(v))


class Catalog:
    """Каталог, загруженный в память для поиска (только чтение)."""

    def __init__(self, path: Path):
        con = _ro(path)
        try:
            if con.execute("SELECT value FROM catalog_meta WHERE key='purpose'").fetchone()[0] != PURPOSE:
                raise CatalogError("файл не является локальным тестовым каталогом NeSToR")
            self.sources = {r["source_id"]: dict(r) for r in con.execute("SELECT * FROM sources")}
            self.records: list[_Rec] = []
            for r in con.execute("SELECT source_id, source_sample_id, population, record_kind, observed_n, "
                                 "positions_json, flags_json, haplogroup, country FROM records ORDER BY id"):
                pos = {k: mk.from_storage(v, st) for k, (v, st) in json.loads(r["positions_json"]).items()}
                self.records.append(_Rec(r["source_id"], r["source_sample_id"], r["population"], r["record_kind"],
                                         r["observed_n"], pos, tuple(json.loads(r["flags_json"])),
                                         r["haplogroup"], r["country"]))
            self.counts = {"records": len(self.records),
                           "individual_records": sum(1 for x in self.records if x.kind != "aggregated"),
                           "aggregated_records": sum(1 for x in self.records if x.kind == "aggregated"),
                           "aggregated_observations": sum(x.n for x in self.records if x.kind == "aggregated"),
                           "sources": len(self.sources)}
        finally:
            con.close()

    def facets(self) -> dict:
        """Значения для фильтров: страны и источники (с числом записей)."""
        countries = collections.Counter(r.country for r in self.records if r.country)
        sources = collections.Counter(r.source_id for r in self.records)
        return {"countries": sorted(countries.items(), key=lambda x: (-x[1], x[0])),
                "sources": [(s, self.sources[s].get("title") or s, n)
                            for s, n in sorted(sources.items(), key=lambda x: (-x[1], x[0]))]}

    def compare(self, query: dict, *, limit: int = 200, **kw) -> tuple[list[CatalogMatch], int]:
        """Сравнение профиля с каталогом. Возвращает (первые limit совпадений, всего совпадений)."""
        out = self._compare_all(query, **kw)
        return out[:limit], len(out)

    def compare_summary(self, query: dict, *, limit: int = 200, **kw) -> tuple[list[CatalogMatch], dict]:
        """Как compare(), но со сводкой по ВСЕМ найденным (а не только по показанным)."""
        out = self._compare_all(query, **kw)
        agg = [m for m in out if m.record_kind == "aggregated"]
        return out[:limit], {"total": len(out), "individual": len(out) - len(agg), "aggregated": len(agg),
                             "aggregated_n": sum(m.observed_n for m in agg)}

    def _compare_all(self, query: dict, *, max_gd: int, min_common: int, excluded=(), country: str | None = None,
                     source: str | None = None, kind: str | None = None, text: str | None = None) -> list[CatalogMatch]:
        """Все совпадения, отсортированные по GD. Фильтры применяются до расчёта GD."""
        needle = (text or "").strip().lower()
        qview = gd_view(query)[0]
        out = []
        for r in self.records:
            if (country and r.country != country) or (source and r.source_id != source) or (kind and r.kind != kind):
                continue
            if needle and needle not in " ".join(str(x or "") for x in (r.sample_id, r.population, r.country,
                                                                        r.haplogroup, r.source_id,
                                                                        self.sources[r.source_id].get("title"))).lower():
                continue
            res = genetic_distance(query, r.positions, excluded=excluded)
            if res.compared < min_common or res.gd > max_gd:
                continue
            s = self.sources[r.source_id]
            rview = gd_view(r.positions)[0]
            diffs = []
            for locus, (cat, steps) in sorted(res.per_locus.items()):
                if cat == "compared" and steps:
                    diffs.append((locus, _fmt(qview.get(locus)), _fmt(rview.get(locus)), steps))
                elif cat == "copy_count":
                    diffs.append((locus, _fmt(qview.get(locus)), _fmt(rview.get(locus)), "разное число копий"))
                elif cat == "fractional":
                    diffs.append((locus, _fmt(qview.get(locus)), _fmt(rview.get(locus)), "дробное, без шагов"))
            not_compared = {"нет значения / не распознано": len(res.missing_or_invalid),
                            "разное число копий": len(res.copy_count_differences),
                            "дробные различия": len(res.allele_differences),
                            "исключены вами": len(res.user_excluded)}
            quality = tuple((k, str(v)) for k, v in sorted(r.positions.items()) if isinstance(v, mk.Invalid))
            out.append(CatalogMatch(r.source_id, r.sample_id, r.population, r.kind, r.n, res.gd, res.compared,
                                    res.panel_overlap, s["verification_status"], s["reuse_note"], r.flags,
                                    license=s.get("license") or "", quality=quality, haplogroup=r.haplogroup,
                                    country=r.country, differences=tuple(diffs),
                                    not_compared={k: v for k, v in not_compared.items() if v},
                                    source_title=s.get("title") or "", publication=s.get("publication") or "",
                                    doi=s.get("doi") or ""))
        out.sort(key=lambda m: (m.gd, -m.compared, m.source_id, m.sample_id))
        return out

    def search(self, query: dict, *, max_gd: int, min_common: int, excluded=(), limit: int = 200) -> list[CatalogMatch]:
        return self.compare(query, max_gd=max_gd, min_common=min_common, excluded=excluded, limit=limit)[0]


def load_if_enabled(var_dir: Path) -> Catalog | None:
    return Catalog(catalog_path(var_dir)) if is_enabled(var_dir) else None
