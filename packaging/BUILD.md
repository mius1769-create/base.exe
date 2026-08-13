# Сборка GENOPOISK CRM в Windows EXE

## Автоматически (рекомендуется) — GitHub Actions

1. Создайте репозиторий на GitHub и запушьте туда содержимое этой папки целиком
   (включая `.github/workflows/build-windows.yml`).
2. Любой push в ветку `main` (или тег `v*`, или ручной запуск через вкладку
   **Actions → Build Windows installer → Run workflow**) автоматически:
   - установит зависимости и прогонит `pytest` (20 тестов бизнес-логики);
   - соберёт onedir-бандл через PyInstaller;
   - **запустит собранный EXE и проверит, что он не падает сразу** (smoke-test);
   - соберёт `GENOPOISK_CRM_Setup.exe` через Inno Setup 6 (уже установлен на
     раннере `windows-latest`);
   - выложит оба артефакта (`GENOPOISK_CRM-portable` и `GENOPOISK_CRM-Setup`)
     во вкладке Actions → конкретный запуск → Artifacts.
3. Скачайте `GENOPOISK_CRM_Setup.exe` из артефактов и раздайте пользователю.

Локально Windows-машина не нужна — вся сборка происходит на GitHub-раннере.

## Вручную на Windows-машине

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python -m pytest tests\ -v

pyinstaller packaging\genopoisk_crm.spec --distpath dist --workpath build --noconfirm

# Проверьте, что dist\GENOPOISK_CRM\GENOPOISK_CRM.exe запускается вручную.

# Затем соберите инсталлятор (нужен Inno Setup 6: https://jrsoftware.org/isinfo.php):
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Готовый инсталлятор появится в `dist_installer\GENOPOISK_CRM_Setup.exe`.

## Что уже проверено в этой Linux-песочнице

Нативный Windows EXE здесь собрать нельзя, но конфигурация PyInstaller
(`packaging/genopoisk_crm.spec`) проверена **реальной сборкой под Linux** по
тому же spec-файлу — она поймала бы (и поймала — см. ниже) ошибки вроде
отсутствующих hidden imports или неправильной точки входа:

- найдена и исправлена ошибка относительного импорта при прямом запуске
  `app/main.py` как entry-point → добавлен `run_app.py` вне пакета `app`;
- найдена и исправлена ошибка конфигурации onefile/onedir (installer.iss
  ожидает папку `dist\GENOPOISK_CRM\`, а не один файл) → добавлен `COLLECT()`
  в spec;
- собранный Linux-бинарник по этому же spec реально запущен, создал и
  проинициализировал БД (7 типов тестов из справочника) и не упал за 6+ секунд
  работы под Xvfb.

Единственное, что нельзя проверить без Windows-раннера — итоговую сборку под
Windows и работу `installer.iss` через Inno Setup. Это произойдёт при первом
запуске workflow на GitHub.
