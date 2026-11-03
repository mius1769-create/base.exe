"""Проверка NeSToR под обычными (не администраторы) учётными записями Windows — для CI.

  main  — запускается от первой обычной учётной записи: проверяет, что она не
          администратор, создаёт каталог временных загрузок в СВОЁМ Local AppData,
          задаёт и проверяет ACL, выполняет короткий цикл staging и импорта,
          оставляет один временный файл для второго сценария;
  other — запускается от второй обычной учётной записи: пытается прочитать
          оставленный файл и перечислить каталог (ожидается отказ в доступе).

  py -3 tools/ci_windows_probe.py main  --out C:\\nestor_ci
  py -3 tools/ci_windows_probe.py other --out C:\\nestor_ci

Результаты — out/main.json и out/other.json; код возврата 0 только при успехе.
Временные каталоги процесса (TEMP) не используются: окружение может принадлежать
запустившей учётной записи.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADMINISTRATORS = "S-1-5-32-544"
SYSTEM = "S-1-5-18"


def identity() -> dict:
    user = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    name, sid = [x.strip().strip('"') for x in user.strip().split(",")]
    groups_csv = subprocess.run(["whoami", "/groups", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    group_sids = sorted({line.split('","')[2].strip('"') for line in groups_csv.splitlines() if line.count('","') >= 3})
    import ctypes
    return {"name": name, "sid": sid, "rid": sid.rsplit("-", 1)[-1],
            "in_administrators_group": ADMINISTRATORS in group_sids,
            "is_user_an_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
            "groups": group_sids}


def require_unprivileged(ident: dict) -> list[str]:
    problems = []
    if ident["in_administrators_group"] or ident["is_user_an_admin"]:
        problems.append("учётная запись входит в Administrators")
    if ident["rid"] == "500":
        problems.append("встроенный Administrator (RID 500)")
    return problems


def run_main(out: Path) -> dict:
    from nestor_app import db, secure_dir, staging
    from nestor_app import user_import as ui
    from nestor_app.config import default_staging_dir, windows_local_appdata

    res: dict = {"scenario": "main", "identity": identity()}
    res["problems"] = require_unprivileged(res["identity"])
    var = out / f"var-{res['identity']['rid']}"
    var.mkdir(parents=True, exist_ok=True)
    local = windows_local_appdata()
    stg = default_staging_dir(var)
    res.update({"local_appdata": str(local), "env_localappdata": os.environ.get("LOCALAPPDATA"), "staging_dir": str(stg)})
    if local is None or not str(stg).lower().startswith(str(local).lower()):
        res["problems"].append("каталог загрузок не в Local AppData текущего пользователя")

    chk = secure_dir.prepare_private_dir(stg)
    res["acl_check"] = {"ok": chk.ok, "principals": chk.principals, "problems": chk.problems,
                        "icacls": secure_dir.windows_acl_text(stg)}
    if not chk.ok:
        res["problems"].append("проверка ACL не пройдена")
    if set(chk.principals) != {res["identity"]["sid"], SYSTEM}:
        res["problems"].append(f"разрешения не только пользователю и SYSTEM: {chk.principals}")

    # короткий цикл staging
    st = staging.put(stg, 1, "cycle.csv", b"cycle", "AUTO")
    _, data = staging.get(stg, 1, st.upload_id)
    staging.sweep(stg)
    still = (stg / f"{st.upload_id}.bin").exists()
    staging.delete(stg, st.upload_id)
    gone = not (stg / f"{st.upload_id}.bin").exists()
    res["staging_cycle"] = {"read_back": data == b"cycle", "kept_by_sweep": still, "deleted": gone}
    if not (data == b"cycle" and still and gone):
        res["problems"].append("цикл staging не выполнен")

    # короткий цикл импорта (временная загрузка → просмотр → сохранение / отмена)
    conn = db.connect(var / "nestor_users.db")
    try:
        from nestor_app import accounts
        uid = accounts.register(conn, "main@example.test", "password-123")
        y12 = "DYS393;DYS390;DYS19;DYS391;DYS385;DYS426;DYS388;DYS439;DYS389I;DYS392;DYS389II"
        csv = f"Kit;{y12}\nK1;13;24;14;11;11-14;12;12;12;13;13;29\n".encode()
        upload, prev = ui.stage(conn, stg, uid, "k.csv", csv)
        commit = ui.commit(conn, stg, uid, upload, [("CSV", 2)], consent_basis="own_test", consent_confirmed=True)
        upload2, _ = ui.stage(conn, stg, uid, "k.csv", csv)
        ui.discard(stg, uid, upload2)
        res["import_cycle"] = {"profiles": len(commit.profile_ids), "checkpoint": commit.checkpoint.status,
                               "staging_empty_after": not any(stg.iterdir())}
        if len(commit.profile_ids) != 1 or any(stg.iterdir()):
            res["problems"].append("цикл импорта не выполнен")
    finally:
        conn.close()

    # оставить файл для второго сценария — в каталоге по умолчанию (профиль пользователя)
    left = staging.put(stg, 1, "left.csv", b"SECRET-FOR-OTHER-USER", "AUTO")
    res["leftover"] = str(stg / f"{left.upload_id}.bin")

    # решающий случай: каталог в ОБЩЕЙ папке, где группе Users разрешено изменение
    # (как при NESTOR_STAGING_DIR вне профиля) — доступ закрывает только DACL NeSToR
    shared = out / "shared" / f"staging-{res['identity']['rid']}"
    chk2 = secure_dir.prepare_private_dir(shared)
    res["shared_acl_check"] = {"ok": chk2.ok, "principals": chk2.principals, "problems": chk2.problems,
                               "parent_icacls": secure_dir.windows_acl_text(shared.parent),
                               "icacls": secure_dir.windows_acl_text(shared)}
    if not chk2.ok or set(chk2.principals) != {res["identity"]["sid"], SYSTEM}:
        res["problems"].append("проверка ACL в общей папке не пройдена")
    left2 = staging.put(shared, 1, "left.csv", b"SECRET-FOR-OTHER-USER", "AUTO")
    res["shared_staging_dir"] = str(shared)
    res["shared_leftover"] = str(shared / f"{left2.upload_id}.bin")
    res["ok"] = not res["problems"]
    return res


def run_other(out: Path) -> dict:
    main = json.loads((out / "main.json").read_text(encoding="utf-8"))   # контроль: общий файл читается
    res: dict = {"scenario": "other", "identity": identity(), "control_read_main_json": True}
    res["problems"] = require_unprivileged(res["identity"])
    if res["identity"]["sid"] == main["identity"]["sid"]:
        res["problems"].append("вторая учётная запись совпадает с первой")
    attempts = {}
    control = Path(main["shared_staging_dir"]).parent / "control.txt"   # общая папка доступна
    try:
        control.write_text("other-user-can-write-shared-parent", encoding="utf-8")
        res["control_write_shared_parent"] = True
    except OSError as e:
        res["control_write_shared_parent"] = False
        res["problems"].append(f"контроль: нет записи в общую папку ({e}) — проверка некорректна")
    for name, fn in (("profile_read_file", lambda: Path(main["leftover"]).read_bytes()),
                     ("profile_list_dir", lambda: list(Path(main["staging_dir"]).iterdir())),
                     ("shared_read_file", lambda: Path(main["shared_leftover"]).read_bytes()),
                     ("shared_list_dir", lambda: list(Path(main["shared_staging_dir"]).iterdir()))):
        try:
            fn()
            attempts[name] = "ДОСТУП ПОЛУЧЕН"
            res["problems"].append(f"{name}: доступ получен")
        except PermissionError as e:
            attempts[name] = f"отказано (PermissionError, winerror={getattr(e, 'winerror', None)})"
        except FileNotFoundError as e:
            attempts[name] = f"не найдено ({e})"
            res["problems"].append(f"{name}: файл не найден — сценарий main не оставил файл")
    res["attempts"] = attempts
    res["ok"] = not res["problems"]
    return res


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=["main", "other"])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if os.name != "nt":
        print("только Windows", file=sys.stderr)
        return 2
    try:
        res = run_main(a.out) if a.scenario == "main" else run_other(a.out)
    except Exception as e:  # noqa: BLE001 — записать причину для лога CI
        res = {"scenario": a.scenario, "ok": False, "problems": [f"{type(e).__name__}: {e}"]}
    (a.out / f"{a.scenario}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
