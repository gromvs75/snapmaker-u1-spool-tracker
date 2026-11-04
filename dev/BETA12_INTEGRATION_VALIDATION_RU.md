# Основной Tracker 1.2.0-beta.1: интеграционная проверка

Дата: 4 ноября 2026. Исторический протокол до переименования в 1.2 beta. Актуальные пакеты и результаты: [проверка итоговых сборок](BETA12_RENAME_AND_CI_RU.md). Записи ниже сохраняют порядок испытаний, включая промежуточные состояния CI.

## Реализация

- Общий расчёт вынесен в forecast.py; Lab использует тот же модуль.
- ForecastService подключён к TrayApp и /api/forecast. Он читает результаты Snorca и текущий Store, не списывает филамент и не обращается к принтеру.
- Основное окно получает автопоказ через DashboardWindow.show_forecast. Закрытие/скрытие штатного окна сохраняет работу в меню.
- Во время printing/paused прогноз не заменяет расчёт запущенной печати на головках.
- Есть RU/DE/EN строки прогноза, для остальных языков — EN.
- Чтение файлов больше не требует POSIX-only флагов os.O_NOFOLLOW/O_NONBLOCK; сохранены проверки типа, размера и изменения файла.
- Обычная beta использует отдельную пустую базу SnapmakerSpoolTracker-Beta12. Установленная база не импортируется автоматически.

## Изоляция

Основной собранный исполняемый файл запущен с `--isolated-root /private/tmp/tracker-beta12-integration` через отдельную тестовую оболочку. Это не Forecast Lab: использованы основной TrayApp, WebHandler и DashboardWindow.

Маркер: ISOLATED_TRACKER_TEST, содержимое `offline-only\n`. База: inventory. Результаты: slices. Случайный loopback-порт. PrinterMonitor и MotionStreamRecorder не запускаются. Маршруты принтера, отправки и списания возвращают 403. Импорт в изоляции отключает конфигурацию принтера.

## Проверка окна

1. Две синтетические завершённые пластины обнаружены одной пачкой: auto_shows=1. Окно появилось.
2. Пластина 2: T1, расход 10 г, остаток после печати 113,25 г.
3. Переключение на пластину 1: T0, расход 3,28 г, остаток после печати 74,22 г.
4. Окно скрыто. Недописанный .gcode.tmp не изменил revision=1 и auto_shows=1.
5. После завершения файла и rename: revision=2, auto_shows=2. Окно появилось повторно. T0: расход 80 г, остаток 77,5 г, резерв 5 г, дефицит 7,5 г; красное ✕.
6. Катушки и назначения полностью совпали с исходными; изменился только язык тестовой базы RU→DE. Автоматического списания нет.

Процесс изолированной beta затем завершён SIGTERM для окончательной пересборки. Обычный выход через меню и повторный запуск итогового пакета этим опытом не подтверждены. Восстановление прогнозов после нового ForecastService проверено автоматическим тестом.

## Артефакты

Локальный macOS-пакет: output/1.2-beta-candidate/SnapmakerSpoolTracker-1.2.0-beta.1-macOS-arm64-local.zip. Архитектура arm64, ad-hoc подпись, без нотариализации. Встроенный --self-test и codesign --verify --deep --strict прошли.

CI-ветка v1.2-beta-integration-build подготовлена в отдельном /tmp checkout; рабочая ветка пользователя не переключалась. В CI переданы только исходники, тесты и сборочные файлы, без тестовых баз и output. Main не изменён, GitHub Release не опубликован.

Windows GUI и настоящая нарезка Snorca на Windows ещё требуют отдельной проверки. Успех CI-сборки не равнозначен этой проверке.

## Final snapshot and restart

CI commit: 54a15e8d9f4ca5b0c38900e0060959652e1b7cfc. 425 tests passed, 3 skipped. After port change: 24 HTTP/core and 19 window/integration checks passed. Beta port: 8766; bundle: local.snapmaker-spool-tracker.v12beta1.

Final package restarted without --resume with the same isolated store. API verified two plates, latest usage 80 g, one reveal callback, unchanged spools and assignments. CUA could not bind the new bundle ID, so the final restart window was not visually verified. Earlier native auto-show and reslice UI checks passed.

Windows CI run 41879543206 and macOS run 41879543212 are queued; no runner steps yet. No Windows executable is available. Cancelling superseded runs returned a contradictory completed-state error while their status remained queued; cancellation is unconfirmed.

## Build results

macOS CI job 126748176047 (run 41879543212) succeeded: 425 passed, 4 skipped; arm64 application packaged, self-test and codesign verification passed. Artifact downloaded and SHA-256 verified.

First Windows run found a POSIX-only os.mkfifo test. Fixed by skipping only that FIFO test on Windows, with an additional cross-platform special-file rejection test. Final Windows job 126754376210 (run 41881362494) succeeded: 405 passed, 25 skipped; x86_64 EXE packaged and self-tested on Windows. Artifact and contained EXE SHA-256 verified. Windows GUI/Snorca slicing still requires a dedicated Windows test.

Available packages and instructions: output/1.2-beta-candidate. Mac artifact commit 54a15e8 and Windows artifact commit fa7b9ed differ only in tests/test_slice_observer.py; packaged application source files are identical. Main and published releases remain unchanged.
