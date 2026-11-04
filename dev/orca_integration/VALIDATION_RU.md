# Результат испытаний — 2026-11-04

**83 passed in 3.32s**, без пропусков, на macOS.

Запущены tests/test_orca_offline_integration.py, tests/test_presend.py,
tests/test_material_guard.py и tests/test_tool_mapping.py. Использован
sandbox-exec с deny network* и deny file-write* для /Users/viktor;
TRACKER_ASSERT_OS_ISOLATION=1. Запреты сети и записи подтверждены тестом.
Все временные исходники, бинарник стенда и тестовые данные размещены вне
домашнего каталога. Полная команда приведена в README_RU.md.

- 22 интеграционных теста, включая проверку ОС; 61 тест alpha/материалов/mapping.
- C++-мост собран clang++ с -std=c++17 -Wall -Wextra -Werror.
- Патч применён к Plater.cpp, SHA-256 которого совпал с source_pin.json.
- Header из применённого патча побайтово совпал с header стенда.
- Проверено расположение безусловного return перед gateway, WebPreprintDialog
  и сохранением настройки для перехваченной ветки U1.
- В официальном PrintHostDialogs.hpp подтверждён тип filename():
  boost::filesystem::path, соответствующий использованному filename().string().
- В сценариях отказа checker upload=0/start=0. При отказе самого bridge
  offline endpoint не вызван, отчёт отсутствует. Положительный Send имеет один
  записанный upload, Print — один записанный upload и один start.

Исходная Snorca, пользовательский inventory и реальный U1 не использовались.
В установленном приложении ничего не менялось. Транспорт стенда только записывает
действия в память; полученные отчёты не являются заданиями печати.

Граница: не собраны и не испытаны весь Plater.cpp, wxWidgets GUI и настоящий
Snapmaker gateway. Патч — offline integration candidate; испытание C++-моста
не является доказательством работы всей пропатченной Snorca. Реальная финальная
проверка после выбора device/mapping и атомарные резервы остаются следующими этапами.

