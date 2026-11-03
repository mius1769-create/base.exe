"""Воспроизводимая сборка локального тестового каталога из исходных файлов заказчика.

Входы (только чтение, не меняются):
  * исходный архив экспертного приложения Genopoisk_expert_linux_2026-10-14.tar.gz
    (или .tar, или .zip, внутри которого лежит этот .tar.gz / .tar);
  * Nestor_scientific_YSTR.db.

Шаги: SHA-256 обоих входов → извлечение одного файла reference/scientific.sqlite во
временный файл внутри var/test_catalog (проверка его SHA-256) → сборка во временную базу
→ сверка ожидаемых количеств → только при полном успехе замена каталога. При любой
ошибке прежний каталог и флаг включения не меняются, временные файлы удаляются.
Сеть не используется; каталог никуда не отправляется.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from . import test_catalog as tc

# Значения для исходных файлов заказчика (SHA256SUMS.txt; docs/TEST_CATALOG.md).
EXPECTED = {
    "release_sha256": "745ca9cdc715c73ff351adee554a7e6259d92d952cfdd0580ac0356cd624d9b5",
    "candidate_sha256": "c6f713b1a0db0966fbabbfaae8fc926934ddd3131fccb591d7686719a7ba7d7d",
    "sqlite_sha256": "98a9941661d1461bdda478fed77426fca19c1fca80e85fa899ee1a8b1906be9e",
    "sqlite_member": "reference/scientific.sqlite",
    "records": 60011,
    "individual_records": 51985,
    "aggregated_records": 8026,
    "aggregated_observations": 8612,
    "sources": 33,
    "skipped_duplicate_copies": 20662,
    # эталонная сборка (Python 3.10 и 3.13): совпадение — сверка, а не условие успеха
    "catalog_content_sha256": "4ba60e299c0e15db325ddcb24da3c6c9bf2bd67713d9dd085a69186b1e054f36",
}
COUNT_KEYS = ("records", "individual_records", "aggregated_records", "aggregated_observations",
              "sources", "skipped_duplicate_copies")
REPORT_FILE = "BUILD_REPORT.json"


class ReleaseError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _HashingReader:
    """Обёртка потока: считает SHA-256 того, что прочитано (внутренний .tar.gz в .zip)."""

    def __init__(self, f):
        self.f, self.h = f, hashlib.sha256()

    def read(self, n=-1):
        b = self.f.read(n)
        self.h.update(b)
        return b

    def drain(self):
        while self.read(1 << 20):
            pass
        return self.h.hexdigest()


def _member_matches(name: str, wanted: str) -> bool:
    name = name.replace("\\", "/").lstrip("./")
    return name == wanted or name.endswith("/" + wanted)


def _extract_from_tar(stream, wanted: str, dest: Path) -> str:
    """Извлечь ровно один обычный файл wanted из потока tar[.gz] в dest; вернуть имя члена."""
    found = None
    with tarfile.open(fileobj=stream, mode="r|*") as tar:
        for m in tar:
            if m.isfile() and _member_matches(m.name, wanted):
                if found:
                    raise ReleaseError(f"в архиве несколько файлов {wanted}: {found}, {m.name}")
                src = tar.extractfile(m)
                with open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                found = m.name
    if not found:
        raise ReleaseError(f"в архиве нет файла {wanted}")
    return found


def extract_sqlite(release: Path, dest: Path, expected: dict) -> dict:
    """Проверить архив и извлечь scientific.sqlite. Возвращает сведения о проверке."""
    info = {"release_file": release.name, "release_file_sha256": sha256_file(release)}
    low = release.name.lower()
    if low.endswith(".rar"):
        raise ReleaseError("RAR не читается без внешних программ: распакуйте части .rar (7-Zip / WinRAR) "
                           "и укажите полученный .tar.gz")
    if zipfile.is_zipfile(release):
        with zipfile.ZipFile(release) as z:
            inner = [n for n in z.namelist() if n.lower().endswith((".tar.gz", ".tgz", ".tar"))]
            if len(inner) != 1:
                raise ReleaseError(f"в .zip ожидается один .tar.gz / .tar, найдено: {inner or 'ничего'}")
            with z.open(inner[0]) as raw:
                hr = _HashingReader(raw)
                member = _extract_from_tar(hr, expected["sqlite_member"], dest)
                inner_sha = hr.drain()
        info.update({"inner_archive": inner[0], "release_sha256": inner_sha})
    else:
        with open(release, "rb") as raw:
            member = _extract_from_tar(raw, expected["sqlite_member"], dest)
        info["release_sha256"] = info["release_file_sha256"]
    if info["release_sha256"] != expected["release_sha256"]:
        raise ReleaseError(f"SHA-256 архива {info['release_sha256']} ≠ ожидаемому {expected['release_sha256']}")
    info["sqlite_member"] = member
    info["sqlite_sha256"] = sha256_file(dest)
    if info["sqlite_sha256"] != expected["sqlite_sha256"]:
        raise ReleaseError(f"SHA-256 {member} {info['sqlite_sha256']} ≠ ожидаемому {expected['sqlite_sha256']}")
    return info


def content_sha256(catalog: Path) -> str:
    """SHA-256 содержимого каталога (источники и записи по порядку) — не зависит от версии SQLite."""
    import sqlite3
    con = sqlite3.connect(f"{Path(catalog).resolve().as_uri()}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        for sql in ("SELECT * FROM sources ORDER BY source_id", "SELECT * FROM records ORDER BY id"):
            for row in con.execute(sql):
                h.update(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
        return h.hexdigest()
    finally:
        con.close()


def load_expected(path: Path | None) -> dict:
    exp = dict(EXPECTED)
    if path:
        exp.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return exp


def build_release(release: Path, candidate: Path, var_dir: Path, audit_path: Path, *,
                  expected: dict | None = None, enable: bool = False) -> dict:
    exp = expected or dict(EXPECTED)
    d = tc.catalog_dir(var_dir)
    d.mkdir(parents=True, exist_ok=True)
    tmp_sqlite = d / "_extract_scientific.sqlite.tmp"
    tmp_db = d / "_build.db.tmp"
    report: dict = {"purpose": tc.PURPOSE, "ok": False}
    try:
        cand_sha = sha256_file(candidate)
        report["candidate_file"], report["candidate_sha256"] = candidate.name, cand_sha
        if cand_sha != exp["candidate_sha256"]:
            raise ReleaseError(f"SHA-256 {candidate.name} {cand_sha} ≠ ожидаемому {exp['candidate_sha256']}")
        report.update(extract_sqlite(release, tmp_sqlite, exp))
        stats = tc.build(candidate, tmp_sqlite, tmp_db, audit_path)
        got = {k: stats.get(k) for k in COUNT_KEYS}
        want = {k: exp[k] for k in COUNT_KEYS}
        report["counts"], report["expected_counts"] = got, want
        if got != want:
            diff = {k: (got[k], want[k]) for k in COUNT_KEYS if got[k] != want[k]}
            raise ReleaseError(f"количества не совпали (получено, ожидалось): {diff}")
        report["sources_status"] = {s: {"records": v["records"], "observations": v["observations"],
                                        "kind": v["kind"], "status": v["status"]}
                                    for s, v in stats["by_source"].items()}
        report["unverified_sources"] = len(stats["unverified_sources"])
        was_enabled = tc.is_enabled(var_dir)
        tc.disable(var_dir)
        os.replace(tmp_db, tc.catalog_path(var_dir))
        report["catalog_file_sha256"] = sha256_file(tc.catalog_path(var_dir))   # зависит от версии SQLite
        report["catalog_content_sha256"] = content_sha256(tc.catalog_path(var_dir))
        if exp.get("catalog_content_sha256"):
            report["content_matches_reference_build"] = report["catalog_content_sha256"] == exp["catalog_content_sha256"]
        if enable or was_enabled:
            tc.enable(var_dir)
        report["enabled"] = tc.is_enabled(var_dir)
        report["ok"] = True
    except (ReleaseError, tarfile.TarError, zipfile.BadZipFile, OSError) as e:
        report["error"] = str(e)
    finally:
        for p in (tmp_sqlite, tmp_db, tmp_db.with_name(tmp_db.name + "-wal"), tmp_db.with_name(tmp_db.name + "-shm")):
            if p.exists():
                p.unlink()
    (d / REPORT_FILE).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


# ---------- проверка в локальном интерфейсе (отдельные процессы run_nestor.py) ----------

def _sample_queries(var_dir: Path) -> dict:
    """Запросы из самого каталога: одна индивидуальная запись и одно агрегированное наблюдение."""
    import sqlite3
    con = sqlite3.connect(f"{tc.catalog_path(var_dir).resolve().as_uri()}?mode=ro", uri=True)
    try:
        out = {}
        for kind in ("individual", "aggregated"):
            best = None
            for (pj,) in con.execute("SELECT positions_json FROM records WHERE record_kind=? LIMIT 500", (kind,)):
                ok = {k: v for k, (v, st) in json.loads(pj).items() if st == "ok"}
                if best is None or len(ok) > len(best):
                    best = ok
            if best:
                out[kind] = "\n".join(f"{k}={v}" for k, v in best.items())
        return out
    finally:
        con.close()


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_app_once(python: str, app_root: Path, var_dir: Path, queries: dict, timeout: float = 120.0) -> dict:
    """Запустить NeSToR отдельным процессом, открыть главную и выполнить гостевой поиск, остановить."""
    import subprocess
    import time
    import urllib.parse
    import urllib.request
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([python, str(app_root / "run_nestor.py"), "--no-browser", "--port", str(port),
                             "--var-dir", str(var_dir)], cwd=str(app_root), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + timeout
        home = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ReleaseError(f"NeSToR завершился при запуске (код {proc.returncode})")
            try:
                with urllib.request.urlopen(base + "/", timeout=timeout) as r:
                    home = r.read().decode("utf-8")
                break
            except OSError:
                time.sleep(0.5)
        if home is None:
            raise ReleaseError("NeSToR не ответил на http://127.0.0.1")
        res = {"status_enabled": "Научный тестовый каталог: <b>включён</b>" in home,
               "status_disabled": "Научный тестовый каталог: <b>выключен</b>" in home}
        for kind, text in queries.items():
            body = urllib.parse.urlencode({"markers": text, "max_gd": "0", "min_common": "5",
                                           "panel": "CUSTOM"}).encode()
            req = urllib.request.Request(base + "/guest/search", data=body, headers={"Origin": base})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                page = r.read().decode("utf-8")
            res[kind] = {"catalog_section": "ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ" in page,
                         "unverified_note": tc.UNVERIFIED_NOTE in page,
                         "preliminary_gd": "(предварительно)" in page,
                         "aggregate_with_n": "агрегированное наблюдение, N=" in page,
                         "individual_row": "индивидуальная запись" in page}
        return res
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001
            proc.kill()
            proc.wait(timeout=30)


def verify_ui(var_dir: Path, app_root: Path, python: str, *, leave_enabled: bool = True) -> dict:
    """Включён → перезапуск → всё ещё включён → выключение → нет в интерфейсе → (снова включить)."""
    if not tc.catalog_path(var_dir).exists():
        raise ReleaseError("каталог не собран")
    queries = _sample_queries(var_dir)
    if set(queries) != {"individual", "aggregated"}:
        raise ReleaseError("в каталоге нет индивидуальных или агрегированных записей для проверки")
    tc.enable(var_dir)
    first = _run_app_once(python, app_root, var_dir, queries)
    second = _run_app_once(python, app_root, var_dir, queries)          # новый процесс: состояние из var/
    tc.disable(var_dir)
    off = _run_app_once(python, app_root, var_dir, queries)
    if leave_enabled:
        tc.enable(var_dir)

    def shown(r):
        return (r["status_enabled"] and r["individual"]["catalog_section"] and r["individual"]["individual_row"]
                and r["individual"]["unverified_note"] and r["individual"]["preliminary_gd"]
                and r["aggregated"]["aggregate_with_n"])

    checks = {
        "enabled_shown_in_ui": shown(first),
        "state_kept_after_restart": shown(second),
        "disabled_hidden_in_ui": off["status_disabled"] and not any(off[k]["catalog_section"] for k in queries),
    }
    return {"ok": all(checks.values()), "checks": checks, "runs": {"enabled": first, "restarted": second,
                                                                    "disabled": off},
            "final_enabled": tc.is_enabled(var_dir)}
