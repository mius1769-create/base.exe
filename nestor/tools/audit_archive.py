"""Аудит архива экспертного приложения (только чтение исходного архива).

  py -3 tools/audit_archive.py АРХИВ(.tar.gz|.tar.zip|.zip) --expected-sha256 745CA9CD... \
      --workdir var/archive_audit --out docs/ARCHIVE_AUDIT.json

Шаги:
  1. SHA-256 исходного файла; если это .zip с вложенным .tar.gz — SHA-256 вложенного
     и сравнение с ожидаемой суммой;
  2. распаковка в отдельную пустую папку --workdir (пути с '..' и абсолютные отклоняются);
  3. поиск manifest.json и проверка перечисленных в нём файлов (размер, SHA-256);
  4. для каждого *.sqlite / *.db: PRAGMA integrity_check, таблицы и число строк
     (открытие mode=ro).
Код архива не исполняется. Базы не копируются в NeSToR и не импортируются.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts


def locate_tar_gz(archive: Path) -> tuple[str, bytes | None, dict]:
    """Возвращает (имя, байты .tar.gz или None если архив сам .tar.gz, сведения)."""
    info = {"file": archive.name, "sha256": sha256_file(archive), "size": archive.stat().st_size}
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            info["zip_entries"] = names
            inner = [n for n in names if n.endswith((".tar.gz", ".tgz"))]
            if len(inner) != 1:
                raise SystemExit(f"в zip ожидается ровно один .tar.gz, найдено: {inner}")
            data = z.read(inner[0])
            info["inner"] = {"file": inner[0], "sha256": sha256_bytes(data), "size": len(data)}
            return inner[0], data, info
    return archive.name, None, info


def extract(tar_bytes: bytes | None, archive: Path, workdir: Path) -> list[dict]:
    workdir.mkdir(parents=True, exist_ok=True)
    if any(workdir.iterdir()):
        raise SystemExit(f"папка {workdir} не пуста — нужна отдельная пустая папка")
    fobj = io.BytesIO(tar_bytes) if tar_bytes is not None else open(archive, "rb")
    listing = []
    with tarfile.open(fileobj=fobj, mode="r:*") as tar:
        for m in tar.getmembers():
            if not _safe(m.name) or m.issym() or m.islnk() or m.isdev():
                listing.append({"path": m.name, "skipped": "небезопасный путь или ссылка"})
                continue
            if m.isfile():
                data = tar.extractfile(m).read()
                dest = workdir / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                listing.append({"path": m.name, "size": len(data), "sha256": sha256_bytes(data)})
    return listing


def _manifest_entries(manifest) -> list[tuple[str, str | None, int | None]]:
    """Поддерживает {'files': [{path, sha256, size}]}, [{...}], {path: sha256}."""
    items = manifest.get("files", manifest) if isinstance(manifest, dict) else manifest
    out = []
    if isinstance(items, dict):
        for k, v in items.items():
            if isinstance(v, dict):
                out.append((k, v.get("sha256"), v.get("size") or v.get("bytes")))
            else:
                out.append((k, str(v), None))
    else:
        for it in items:
            out.append((it.get("path") or it.get("file") or it.get("name"),
                        it.get("sha256") or it.get("hash"), it.get("size") or it.get("bytes")))
    return out


def check_manifests(workdir: Path, listing: list[dict]) -> list[dict]:
    by_rel = {x["path"]: x for x in listing if "sha256" in x}
    results = []
    for mpath in sorted(workdir.rglob("manifest.json")):
        base = mpath.parent
        try:
            entries = _manifest_entries(json.loads(mpath.read_text(encoding="utf-8")))
        except (ValueError, AttributeError, TypeError) as e:
            results.append({"manifest": str(mpath.relative_to(workdir)), "error": f"не разобран: {e}"})
            continue
        ok, bad, missing = 0, [], []
        for rel, sha, size in entries:
            key = str((base / rel).relative_to(workdir)).replace("\\", "/")
            item = by_rel.get(key)
            if item is None:
                missing.append(rel)
            elif (sha and sha.lower() != item["sha256"]) or (size and int(size) != item["size"]):
                bad.append(rel)
            else:
                ok += 1
        results.append({"manifest": str(mpath.relative_to(workdir)), "entries": len(entries),
                        "ok": ok, "mismatch": bad, "missing": missing})
    return results


def check_sqlite(workdir: Path) -> list[dict]:
    out = []
    for p in sorted(list(workdir.rglob("*.sqlite")) + list(workdir.rglob("*.db"))):
        rec = {"path": str(p.relative_to(workdir)), "sha256": sha256_file(p)}
        try:
            conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
            rec["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            rec["tables"] = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                             for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
            conn.close()
        except sqlite3.DatabaseError as e:
            rec["error"] = str(e)
        out.append(rec)
    return out


def audit(archive: Path, workdir: Path, expected: str | None) -> dict:
    name, tar_bytes, info = locate_tar_gz(archive)
    tar_sha = info.get("inner", info)["sha256"]
    result = {"archive": info, "tar_gz": name,
              "expected_sha256": expected.lower() if expected else None,
              "sha256_matches": (tar_sha == expected.lower()) if expected else None}
    listing = extract(tar_bytes, archive, workdir)
    result["files"] = listing
    result["file_count"] = sum(1 for x in listing if "sha256" in x)
    result["manifests"] = check_manifests(workdir, listing)
    result["sqlite"] = check_sqlite(workdir)
    return result


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--expected-sha256")
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    res = audit(a.archive, a.workdir, a.expected_sha256)
    text = json.dumps(res, ensure_ascii=False, indent=2) + "\n"
    (a.out.write_text(text, encoding="utf-8") if a.out else sys.stdout.write(text))
    return 0 if res["sha256_matches"] in (True, None) else 2


if __name__ == "__main__":
    raise SystemExit(main())
