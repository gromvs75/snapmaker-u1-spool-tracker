# RFID 2.1.0.157 · репетиция установки из архива

Архив предназначен для подготовленной модели BootModel на компьютере.
Распакуйте его в новый каталог вне модели. Из него выполните команды ниже,
подставив абсолютный путь к существующему стенду. Команда plan показывает
ревизию и состояние общего системного слоя. Сохраните ревизию до установки.

```sh
python3 -I launch.py plan --simulator-root "$BENCH_ROOT"
python3 -I launch.py install --simulator-root "$BENCH_ROOT" --reviewed-revision "$REVISION" --accept-whole-overlay
```

При расхождениях системного слоя с исходным сначала проверьте изменения.
Для принятия просмотренных изменений предусмотрен флаг
`--accept-existing-changes`. Для отката на остановленном стенде используйте
копию из каталога восстановления. Исходный ZIP и Tracker при этом не нужны.

```sh
python3 -I "$BENCH_ROOT/persistent/tracker-deployment/debug-loader-kit/launch.py" rollback --simulator-root "$BENCH_ROOT"
```

## Что известно о физическом U1 по сохранённой диагностике

В klippy-head.txt зафиксированы сборка 2.1.0.157_20261028045538, Python 3.11.8 и
/home/lava/printer_data/config/printer.cfg. В config-preflight.json для этого
файла указаны fluidd.cfg и xyz_offset_calibration.cfg, оба без вложенных include.
Отпечаток штатного драйвера совпадает с поддерживаемым модулем.
S60klipper запускается раньше S90lmd. Его штатный restart вызывает собственные
stop и start. Порядок и вызовы MCU существенны для физической установки.

На стенде используется отдельный startup-файл. Для реального U1 остаются
проверка его парсера конфигурации, резервная копия overlay с метаданными Linux,
проверка восстановления и согласованное управление службами.
Архив не предназначен для копирования в init.d принтера.

На стенде проверены сохранение калибровки SAVE_CONFIG и разбор optional include
реальным ConfigFileReader. Используйте Python 3.11 для репетиции. Системный
Python 3.9.6 на проверенном Mac обрезает заголовок include до первой закрывающей
квадратной скобки. CLI отвергает такой интерпретатор при подготовке плана.

Для сверки с принтером сверьте отпечаток парсера и разбор заголовка в системном Python.
Ключи -I -B изолируют интерпретатор и отключают запись байткода. Пароль вводится локально в Terminal.

```sh
ssh -T -o StrictHostKeyChecking=yes -o HostKeyAlgorithms=ssh-ed25519 lava@192.168.2.133 '/usr/bin/python3 -I -B -' <<'PYTHON'
import configparser, hashlib, pathlib
path = pathlib.Path('/home/lava/klipper/klippy/configfile.py')
header = 'include /extras/[t]racker_uid_boot.cfg'
print('configfile_sha256', hashlib.sha256(path.read_bytes()).hexdigest())
print('full_include_header', configparser.RawConfigParser.SECTCRE.match('[' + header + ']').group('header') == header)
PYTHON
```

SHA-256 проверенного стендового configfile.py:
`c4049b906b5341ad492105901515c6d9a4504d980098f9ce346df48388c53cf4`.
При другом отпечатке потребуется сравнить исходники. Совпадение подтверждает
идентичность файла, поведение также зависит от версии стандартной библиотеки.
