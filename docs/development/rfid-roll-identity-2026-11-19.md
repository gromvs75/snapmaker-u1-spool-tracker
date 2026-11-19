# Общий ID катушки: исследование и стенд 19.11.2026

Рабочая копия: `output/rfid-bambu-2.1`. Реальный принтер, установленный Tracker и
пользовательские настройки не использовались. Публикации и сборки приложения нет.

## Проверенные источники

Bespok3d/material-tags проверен на актуальной ревизии
`504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9`. Это та же ревизия, на которой изучались
декодеры ранее. OpenPrintTag specification:
`060e420892d66c062c8af440c97701aab96bac79`.
Локальные исследовательские копии и SHA-256 новых загрузок:
`output/research/roll-identity/manifest.json`. Исходники декодеров Bespok3d в продукт
не копировались; дополнение реализовано по публичной карте CBOR.

- [Bambu: общий блок 9 у двух сторон](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-bambu/doc/README.md).
- [Библиотека Bambu: фиксированная ревизия дампов](https://github.com/queengooborg/Bambu-Lab-RFID-Library/tree/6ce13422f449ae83f035818ab29610a435551e39).
- [OpenPrintTag: instance_uuid и отдельно package_uuid](https://github.com/OpenPrintTag/openprinttag-specification/blob/060e420892d66c062c8af440c97701aab96bac79/data/main_fields.yaml).
- [OpenPrintTag: тип UUID и правила его получения](https://github.com/OpenPrintTag/openprinttag-specification/blob/060e420892d66c062c8af440c97701aab96bac79/docs_src/nfc_data_format.md).
- [OpenTag3D: Serial Number / Batch ID](https://opentag3d.info/spec.html).
- [TigerTag: pairing timestamp, §2.9 и индекс/count, §2.11](https://github.com/TigerTag-Project/TigerTag-RFID-Guide#29-timestamp--unique-pairing-identifier).
- [QIDI: три байта свойств](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-qidi/doc/README.md).
- [Anycubic: прочитанные поля и неизвестные байты](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-anycubic/doc/README.md).
- [Creality: неподтверждённая семантика serial](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-creality/files/klipper/klippy/extras/rfid-tags/creality/creality_fields.py).
- [Elegoo: подтверждённые и неизвестные поля](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-elegoo/files/klipper/klippy/extras/rfid-tags/elegoo/elegoo_fields.py).
- [Generic JSON: SPOOL_ID/id aliases](https://github.com/Bespok3d/material-tags/blob/504ef25a17ce81dd81e42ea3cbfbc66fab76dfd9/rfid-generic-ndef/files/klipper/klippy/extras/rfid-tags/generic-ndef/generic_ndef_fields.py).

TigerTag документирует timestamp как pairing ID. Отказ от безусловного автоматического
объединения — наша консервативная политика: документ не задаёт глобальное распределение
секунд между записывающими устройствами. Ни индекс 1/2, ни общий product ID не исключают
коллизию двух одинаковых катушек. OpenTag3D прямо допускает ID партии.

## Изменения

- Модуль `0.8.0-roll-identity-bench` читает key 0 main CBOR OpenPrintTag как 16 байт.
  Экспортирует необязательный `instance_uuid`; отсутствие сохраняет прежний формат
  данных, неправильный тип/размер/нулевой/FF UUID отклоняется.
- `roll_key()` допускает только Bambu block 9 и явный OpenPrintTag instance UUID.
  Product UUID, GTIN, JSON spool_id, timestamp и SKU не участвуют в объединении.
- Дополнительная таблица `uid_rfid_roll_keys`: уникальный общий ID ↔ локальная катушка.
  Старая запись Spoolman и её marker не меняются при повторном чтении уже известного
  UID с новым декодером. Каталог и проверка размещения видят общий ID до добавления UID.
- Новая регистрация OpenPrintTag использует общий ID также в marker Spoolman. Потеря
  подтверждения POST с последующим чтением другой стороны не приводит к второму POST:
  найденная запись сверяется, неизвестный результат удерживается.
- Противоречия ID, материала, существующей привязки, расположения, незавершённого
  создания блокируются. Нет автоматического слияния двух записей инвентаря.
- Общие ID и UID-алиасы входят в резервную копию. Старый backup получает пустую
  добавочную таблицу только в проверяемой копии; восстановление не включает RFID само.
- Изменения GUI отсутствуют. Новые EXE/.app и архив установки не собирались;
  старые пакеты сохраняют прежнее содержимое.

## Проверки финального кода

**284 passed**, без ошибок и пропусков:
`output/roll-identity-regression-final.xml` и `.log`.
Включены 27 новых сценариев/параметризованных случаев: shared UUID, разные экземпляры
одного изделия, пустой/повреждённый UUID, product UUID вместо instance UUID, слабые ID,
смена ID, другая привязка, два канала, metadata mismatch, старый chip-only учёт,
потерянный POST, незавершённый расход, перезапуск, backup/restore и миграция старой схемы.
Также регрессия Bambu, остальных форматов, подтверждений, SpoolmanDB, UID/alias,
старых бэкапов и офлайн-установки/отката. Первый общий запуск был ограничен sandbox
при открытии локального HTTP-порта; окончательный запуск с разрешённым loopback прошёл.

Сквозной сценарий: `dev/labs/uid_live_bench/roll_identity_run.py`.
Отчёт: `output/roll-identity-live-final/results.json`; процесс завершён с кодом 0.
Настоящий Klippy и официальный Spoolman 0.27.1, штатный reader U1 2.1.0.157,
имитация RF/SPI/GPIO/MCU, временные SQLite, только Unix socket/loopback.

| Формат | Первая / вторая метка | Общий ID | Результат |
|---|---|---|---|
| Bambu, публичные дампы | `0DF58A36` / `9D1A8636` | `63183A92E6C54600B8E30C6EE7BC3C14` | Одна катушка, PLA C12E1F, 820,123 г |
| OpenPrintTag, синтетическая пара | `04052233445501` / `04052233445502` | `73646F54D4754C33A89C15C14AFA9D11` | Одна катушка, PLA 778899, 820,123 г |

Первая сторона подтверждена через сервис регистрации с остатком 840,123 г; расход
20 г прошёл motion/history → ledger → Sender, повтор истории не списал второй раз.
Вторая сторона обработана интерактивным worker без повторного подтверждения.
Дополнительно зарегистрированы две катушки того же материала и цвета, но с другими
ID, обе остались отдельными с 840,123 г. Всего в Spoolman четыре записи.
Перезапуск сохранил четыре привязки сторон; резервная копия реально восстановлена
в отдельный отключённый профиль. 400 AUTH/READ, **0 WRITE**. OFF → Klippy ready без
модуля → rollback. Все процессы этого сквозного сценария завершены.

Это не аппаратная проверка и не подтверждение заводских OpenPrintTag на U1:
заводской Prusa ISO15693 reader U1 не поддерживает. Новый Windows GUI не проверялся.
SHA-256 модуля: `d692443119be56ec02f795bd9906a30a45f827c9848de8ae9b7effb906d73e22`.

[Инструкция и поведение по всем форматам](../guides/rfid-common-roll-id-ru.md).
