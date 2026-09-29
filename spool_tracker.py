#!/usr/bin/env python3
"""Snapmaker U1 spool inventory and OrcaSlicer preflight hook."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import ProxyHandler, Request, build_opener

from gcode import GCodeError, parse_u1_gcode
from accounting import create_plan
from moonraker import MoonrakerClient, MoonrakerError, PrinterMonitor
from preflight import check, has_problem
from storage import Store, StorageError, ValidationError, label, legacy_paths, printer_config, weight

APP_VERSION = "1.0.1"
WEB_PORT = 8765
STORE = Store(legacy_paths=legacy_paths())
LOGGER = logging.getLogger("snapmaker_tracker")


def configure_logging():
    if LOGGER.handlers:
        return
    STORE.directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(STORE.directory / "tracker.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)



I18N = {
    "en": {
        "dialog_title": "Snapmaker U1 Spool Tracker",
        "dialog_warn": "WARNING: FILAMENT RUNOUT DETECTED!",
        "dialog_desc": "One or more spools do not have enough filament for this print:",
        "dialog_cooling": "If the print pauses unattended, the heated bed may cool down, causing print detachment.",
        "btn_cancel": "Cancel Export",
        "btn_proceed": "Proceed Anyway",
        "slot_unassigned": "• Slot {slot}: No spool assigned! (Required: {req:.1f}g)",
        "slot_shortage": "• Slot {slot} ({name}): Left {rem:.1f}g / Needed {req:.1f}g (Short by {short:.1f}g)",
        "tray_title": "Snapmaker U1 (4 Toolheads)",
        "tray_slot": "Slot {slot} (T{idx}): {name} — {rem:.0f}g",
        "tray_empty": "Slot {slot} (T{idx}): [Empty]",
        "tray_open": "Configure Spools & Slots...",
        "tray_quit": "Quit"
    },
    "ru": {
        "dialog_title": "Snapmaker U1 Spool Tracker",
        "dialog_warn": "ВНИМАНИЕ: ЗАКОНЧИТСЯ ФИЛАМЕНТ!",
        "dialog_desc": "На одной или нескольких катушках остатка меньше, чем требуется:",
        "dialog_cooling": "При долгой паузе стол остынет, что приведет к отрыву детали и браку.",
        "btn_cancel": "Отменить экспорт",
        "btn_proceed": "Продолжить экспорт",
        "slot_unassigned": "• Слот {slot}: Катушка не привязана! (Нужно: {req:.1f}г)",
        "slot_shortage": "• Слот {slot} ({name}): Остаток {rem:.1f}г / Нужно {req:.1f}г (Не хватает {short:.1f}г)",
        "tray_title": "Snapmaker U1 (4 Головки)",
        "tray_slot": "Слот {slot} (T{idx}): {name} — {rem:.0f}г",
        "tray_empty": "Слот {slot} (T{idx}): [Пусто]",
        "tray_open": "Настроить катушки и слоты...",
        "tray_quit": "Выход"
    },
    "de": {
        "dialog_title": "Snapmaker U1 Spool Tracker",
        "dialog_warn": "WARNUNG: FILAMENT REICHT NICHT AUS!",
        "dialog_desc": "Auf einer oder mehreren Spulen ist nicht genug Filament vorhanden:",
        "dialog_cooling": "Bei längeren Pausen kühlt das Druckbett ab, wodurch sich das Druckteil lösen kann.",
        "btn_cancel": "Export abbrechen",
        "btn_proceed": "Trotzdem fortfahren",
        "slot_unassigned": "• Slot {slot}: Keine Spule zugewiesen! (Benötigt: {req:.1f}g)",
        "slot_shortage": "• Slot {slot} ({name}): Rest {rem:.1f}g / Benötigt {req:.1f}g (Fehlen {short:.1f}g)",
        "tray_title": "Snapmaker U1 (4 Druckköpfe)",
        "tray_slot": "Slot {slot} (T{idx}): {name} — {rem:.0f}g",
        "tray_empty": "Slot {slot} (T{idx}): [Leer]",
        "tray_open": "Spulen & Slots konfigurieren...",
        "tray_quit": "Beenden"
    },
    "uk": {
        "dialog_title": "Snapmaker U1 Spool Tracker",
        "dialog_warn": "УВАГА: ЗАКІНЧИТЬСЯ ФІЛАМЕНТ!",
        "dialog_desc": "На одній або кількох котушках залишку менше, ніж потрібно:",
        "dialog_cooling": "Під час довгої паузи стіл охолоне, що призведе до відриву деталі та браку.",
        "btn_cancel": "Скасувати експорт",
        "btn_proceed": "Продовжити експорт",
        "slot_unassigned": "• Слот {slot}: Котушку не прив'язано! (Потрібно: {req:.1f}г)",
        "slot_shortage": "• Слот {slot} ({name}): Залишок {rem:.1f}г / Потрібно {req:.1f}г (Не вистачає {short:.1f}г)",
        "tray_title": "Snapmaker U1 (4 Голівки)",
        "tray_slot": "Слот {slot} (T{idx}): {name} — {rem:.0f}г",
        "tray_empty": "Слот {slot} (T{idx}): [Порожньо]",
        "tray_open": "Налаштувати котушки та слоти...",
        "tray_quit": "Вихід"
    },
    "es": {
        "dialog_title": "Snapmaker U1 Spool Tracker",
        "dialog_warn": "¡ADVERTENCIA: FILAMENTO INSUFICIENTE!",
        "dialog_desc": "Una o varias bobinas no tienen suficiente filamento para esta impresión:",
        "dialog_cooling": "Si la impresión se pausa por mucho tiempo, la base se enfriará y la pieza puede despegarse.",
        "btn_cancel": "Cancelar exportación",
        "btn_proceed": "Continuar de todos modos",
        "slot_unassigned": "• Ranura {slot}: ¡Sin bobina asignada! (Requerido: {req:.1f}g)",
        "slot_shortage": "• Ranura {slot} ({name}): Restante {rem:.1f}g / Requerido {req:.1f}g (Faltan {short:.1f}g)",
        "tray_title": "Snapmaker U1 (4 Cabezales)",
        "tray_slot": "Ranura {slot} (T{idx}): {name} — {rem:.0f}g",
        "tray_empty": "Ranura {slot} (T{idx}): [Vacío]",
        "tray_open": "Configurar bobinas y ranuras...",
        "tray_quit": "Salir"
    }
}

ALERT_I18N = {
    "en": ("T{idx}: no spool assigned; required {req:.1f} g",
           "T{idx} ({name}): required {req:.1f} g + reserve {margin:.1f} g; remaining {rem:.1f} g",
           "G-code could not be checked: {error}\nExport cancelled."),
    "ru": ("T{idx}: катушка не назначена; требуется {req:.1f} г",
           "T{idx} ({name}): требуется {req:.1f} г + запас {margin:.1f} г; остаток {rem:.1f} г",
           "Не удалось проверить G-code: {error}\nЭкспорт отменён."),
    "de": ("T{idx}: keine Spule zugewiesen; benötigt {req:.1f} g",
           "T{idx} ({name}): benötigt {req:.1f} g + Reserve {margin:.1f} g; Rest {rem:.1f} g",
           "G-Code konnte nicht geprüft werden: {error}\nExport abgebrochen."),
    "uk": ("T{idx}: котушку не призначено; потрібно {req:.1f} г",
           "T{idx} ({name}): потрібно {req:.1f} г + запас {margin:.1f} г; залишок {rem:.1f} г",
           "Не вдалося перевірити G-code: {error}\nЕкспорт скасовано."),
    "es": ("T{idx}: sin bobina asignada; se necesitan {req:.1f} g",
           "T{idx} ({name}): se necesitan {req:.1f} g + reserva {margin:.1f} g; quedan {rem:.1f} g",
           "No se pudo comprobar G-code: {error}\nExportación cancelada."),
}


def _mac_dialog(title, message, buttons=None):
    # User supplied spool names are passed as argv, never interpolated into AppleScript.
    script = '''on run argv
set dialogTitle to item 1 of argv
set dialogText to item 2 of argv
if (count of argv) > 2 then
set cancelLabel to item 3 of argv
set proceedLabel to item 4 of argv
try
set resultButton to button returned of (display dialog dialogText with title dialogTitle buttons {cancelLabel, proceedLabel} default button cancelLabel with icon caution)
return resultButton
on error number -128
return cancelLabel
end try
else
display dialog dialogText with title dialogTitle buttons {"OK"} default button "OK" with icon caution
return "OK"
end if
end run'''
    args = ["osascript", "-e", script, title, message]
    if buttons:
        args.extend(buttons)
    return subprocess.check_output(args, text=True, timeout=120).strip()


def _windows_dialog(title, message, buttons=None):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        if not buttons:
            messagebox.showerror(title, message, parent=root)
            return "OK"
        result = {"choice": buttons[0]}
        window = tk.Toplevel(root)
        window.title(title)
        window.resizable(False, False)
        window.attributes("-topmost", True)
        tk.Label(window, text=message, justify="left", wraplength=580, padx=24, pady=20).pack()
        bar = tk.Frame(window)
        bar.pack(padx=20, pady=15)
        def choose(value):
            result["choice"] = value
            window.destroy()
        tk.Button(bar, text=buttons[0], command=lambda: choose(buttons[0]), width=19).pack(side="left", padx=6)
        tk.Button(bar, text=buttons[1], command=lambda: choose(buttons[1]), width=19).pack(side="left", padx=6)
        window.protocol("WM_DELETE_WINDOW", lambda: choose(buttons[0]))
        window.grab_set()
        root.wait_window(window)
        return result["choice"]
    finally:
        root.destroy()


def show_dialog(message, lang="en", allow_proceed=False):
    tr = I18N.get(lang, I18N["en"])
    buttons = (tr["btn_cancel"], tr["btn_proceed"]) if allow_proceed else None
    try:
        if sys.platform == "darwin":
            choice = _mac_dialog(tr["dialog_title"], message, buttons)
        elif sys.platform == "win32":
            choice = _windows_dialog(tr["dialog_title"], message, buttons)
        else:
            print(message, file=sys.stderr)
            return False
        return bool(buttons and choice == buttons[1])
    except Exception:
        LOGGER.exception("Native dialog failed")
        print(message, file=sys.stderr)
        return False


def _save_preflight(rows, summary):
    STORE.update(lambda db: db.__setitem__("last_preflight", {
        "summary": summary, "rows": rows, "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }))


def handle_slicer_hook(gcode_path):
    try:
        db = STORE.read()
    except StorageError as exc:
        LOGGER.error("Database error: %s", exc)
        show_dialog(f"Inventory database error: {exc}")
        return 1
    lang = db["language"]
    try:
        weights = parse_u1_gcode(gcode_path)
    except GCodeError as exc:
        LOGGER.error("G-code parse error: %s", exc)
        try:
            _save_preflight([], f"G-code parse failure: {exc}")
        except StorageError as storage_exc:
            LOGGER.error("Cannot save preflight result: %s", storage_exc)
        show_dialog(ALERT_I18N.get(lang, ALERT_I18N["en"])[2].format(error=exc), lang)
        return 1
    rows = check(weights, db)
    problem = has_problem(rows)
    summary = "Attention required" if problem else "OK"
    try:
        _save_preflight(rows, summary)
    except StorageError as exc:
        LOGGER.error("Cannot save preflight result: %s", exc)
        show_dialog(f"Inventory database error: {exc}", lang)
        return 1
    LOGGER.info("Preflight %s: %s", summary, ", ".join(f'{r["tool"]}={r["status"]}' for r in rows))
    if problem:
        tr = I18N.get(lang, I18N["en"])
        unassigned_text, shortage_text, _ = ALERT_I18N.get(lang, ALERT_I18N["en"])
        lines = []
        for row in rows:
            if row["status"] == "unassigned":
                lines.append(unassigned_text.format(idx=row["tool"][1:], req=row["required_g"]))
            elif row["status"] == "insufficient":
                lines.append(shortage_text.format(idx=row["tool"][1:], name=row["spool_name"],
                                                 req=row["required_g"], margin=db["safety_margin_g"],
                                                 rem=row["remaining_g"]))
        message = f'{tr["dialog_warn"]}\n{tr["dialog_desc"]}\n' + "\n".join(lines)
        if not show_dialog(message, lang, allow_proceed=True):
            return 1
    try:
        create_plan(STORE, gcode_path, os.environ.get("SLIC3R_PP_OUTPUT_NAME"), weights, db)
    except (OSError, StorageError, ValueError) as exc:
        LOGGER.error("Cannot save planned job: %s", exc)
        show_dialog(f"Cannot save planned job: {exc}", lang)
        return 1
    return 0



HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Snapmaker U1 — Spool Manager</title>
<style>
  :root { --bg: #0f172a; --card: #1e293b; --border: #334155; --accent: #38bdf8; --accent-btn: #0284c7; --text: #f8fafc; --muted: #94a3b8; --danger: #ef4444; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 32px 20px; margin: 0; }
  .container { max-width: 780px; margin: 0 auto; }
  .header-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
  h1 { font-size: 26px; margin: 0; font-weight: 700; }
  .lang-select { background: #1e293b; border: 1px solid var(--border); color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }
  p.subtitle { color: var(--muted); margin: 6px 0 0 0; font-size: 14px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 22px; margin-bottom: 24px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.4); }
  .card h2 { font-size: 14px; margin: 0 0 16px 0; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
  .slot-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 14px; }
  .slot-badge { font-weight: 600; width: 140px; font-size: 14px; }
  select, input { background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 9px 12px; border-radius: 8px; font-size: 14px; outline: none; }
  select:focus, input:focus { border-color: var(--accent); }
  select { flex: 1; }
  button { background: var(--accent-btn); color: #fff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; }
  button:hover { background: #0369a1; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; }
  th, td { text-align: left; padding: 12px 14px; border-bottom: 1px solid var(--border); font-size: 14px; }
  th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
  .table-scroll { overflow-x: auto; }
  .spool-inventory { min-width: 700px; table-layout: fixed; }
  .spool-inventory td:first-child code { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .spool-inventory td:nth-child(4), .spool-inventory td:nth-child(5) { white-space: nowrap; }
  .form-inline { display: flex; gap: 10px; margin-top: 14px; }
  .form-inline input { flex: 1; }
</style>
</head>
<body>
<div class="container">
  <div class="header-bar">
    <div>
      <h1 id="t-title">🎯 Snapmaker U1 Spool Tracker</h1>
      <p id="t-subtitle" class="subtitle">Smart 4-toolhead inventory and automatic runout protection</p>
    </div>
    <select id="lang-picker" class="lang-select" onchange="changeLang(this.value)">
      <option value="en">English (EN)</option>
      <option value="ru">Русский (RU)</option>
      <option value="de">Deutsch (DE)</option>
      <option value="uk">Українська (UK)</option>
      <option value="es">Español (ES)</option>
    </select>
  </div>

  <div class="card">
    <h2 id="t-slots-hdr">Active Slots Configuration (T0 – T3)</h2>
    <form id="slots-form">
      <div id="slots-container"></div>
      <div style="text-align: right; margin-top: 16px;">
        <button type="submit" id="t-save-slots">Save Slot Assignments</button>
      </div>
    </form>
  </div>

  <div class="card">
    <h2 id="t-spools-hdr">Spool Inventory</h2>
    <div class="table-scroll">
      <table class="spool-inventory">
        <colgroup><col style="width:36%"><col style="width:16%"><col style="width:12%"><col style="width:18%"><col style="width:18%"></colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th id="t-th-name">Spool Name</th>
            <th id="t-th-mat">Material</th>
            <th id="t-th-rem">Remaining</th>
            <th id="t-th-act">Action</th>
          </tr>
        </thead>
        <tbody id="spools-table"></tbody>
      </table>
    </div>

    <h2 id="t-add-hdr" style="margin-top: 26px;">Add New Spool</h2>
    <form id="add-spool-form" class="form-inline">
      <input type="text" id="new-name" placeholder="Spool name" required>
      <input type="text" id="new-mat" placeholder="Material" style="max-width: 130px;" required>
      <input type="number" id="new-weight" placeholder="Grams" value="1000" style="max-width: 100px;" required>
      <button type="submit" id="t-add-btn">+ Add Spool</button>
    </form>
  </div>
  <div class="card">
    <h2 id="printer-title">U1 printer monitor</h2>
    <p id="printer-help" class="subtitle">Successful matching prints update inventory automatically. Export and upload never deduct filament.</p>
    <form id="printer-form">
      <div class="form-inline">
        <input id="printer-host" type="text" placeholder="U1.local" aria-label="Printer hostname or IP" required>
        <input id="printer-port" type="number" min="1" max="65535" style="max-width: 100px;" aria-label="Moonraker port" required>
      </div>
      <div class="form-inline" style="align-items: center;">
        <label><input id="printer-enabled" type="checkbox" style="margin-right: 8px;"> <span id="printer-enable-label">Enable automatic accounting</span></label>
      </div>
      <div class="form-inline">
        <button id="printer-save" type="submit">Save printer settings</button>
        <button id="printer-test" type="button">Test Connection</button>
      </div>
    </form>
    <p id="printer-status" class="subtitle" aria-live="polite">Disconnected</p>
  </div>
  <div class="card">
    <h2 id="reserve-label">Safety reserve (g)</h2>
    <p id="reserve-help" class="subtitle">Added to each used toolhead for preflight only. It is not consumed.</p>
    <form id="reserve-form" class="form-inline">
      <input id="reserve-input" type="number" min="0" step="any" value="0" required>
      <button id="reserve-save" type="submit">Save reserve</button>
    </form>
  </div>
  <div class="card">
    <h2 id="preflight-title">Last preflight</h2>
    <div id="preflight-content"></div>
    <p id="accounting-status" class="subtitle"></p>
  </div>
</div>

<script>
const dict = {
  en: {
    slotLabel: "Slot",
    toolheadPrefix: "Toolhead T",
    subtitle: "Smart 4-toolhead inventory and automatic runout protection",
    slotsHdr: "Active Slots Configuration (T0 – T3)",
    saveSlots: "Save Slot Assignments",
    emptySlot: "-- Empty / Unassigned --",
    spoolsHdr: "Spool Inventory",
    thName: "Spool Name",
    thMat: "Material",
    thRem: "Remaining",
    thAct: "Action",
    addHdr: "Add New Spool",
    namePh: "Spool name (e.g. eSUN PLA Black)",
    matPh: "Material (PLA)",
    addBtn: "+ Add Spool",
    deleteBtn: "Delete",
    savedAlert: "Slot configuration updated successfully!"
  },
  ru: {
    slotLabel: "Слот",
    toolheadPrefix: "Сопло T",
    subtitle: "Управление 4 соплами (Toolchanger) и защита от остывания стола",
    slotsHdr: "Активные слоты сопел (T0 – T3)",
    saveSlots: "Сохранить привязку слотов",
    emptySlot: "-- Пусто / Не привязано --",
    spoolsHdr: "Библиотека катушек",
    thName: "Название катушки",
    thMat: "Материал",
    thRem: "Остаток",
    thAct: "Действие",
    addHdr: "Добавить новую катушку",
    namePh: "Название (напр. eSUN PLA Black)",
    matPh: "Материал (PLA)",
    addBtn: "+ Добавить катушку",
    deleteBtn: "Удалить",
    savedAlert: "Привязка слотов успешно сохранена!"
  },
  de: {
    slotLabel: "Slot",
    toolheadPrefix: "Druckkopf T",
    subtitle: "Intelligentes 4-Kopf-Inventar & Schutz vor Druckbett-Abkühlung",
    slotsHdr: "Aktive Slot-Konfiguration (T0 – T3)",
    saveSlots: "Slot-Zuweisung speichern",
    emptySlot: "-- Leer / Nicht zugewiesen --",
    spoolsHdr: "Spulen-Inventar",
    thName: "Spulenname",
    thMat: "Material",
    thRem: "Restgewicht",
    thAct: "Aktion",
    addHdr: "Neue Spule hinzufügen",
    namePh: "Spulenname (z.B. eSUN PLA Schwarz)",
    matPh: "Material (PLA)",
    addBtn: "+ Spule hinzufügen",
    deleteBtn: "Löschen",
    savedAlert: "Slot-Konfiguration erfolgreich aktualisiert!"
  },
  uk: {
    slotLabel: "Слот",
    toolheadPrefix: "Сопло T",
    subtitle: "Керування 4 соплами (Toolchanger) та захист від охолодження столу",
    slotsHdr: "Активні слоти сопел (T0 – T3)",
    saveSlots: "Зберегти прив'язку слотів",
    emptySlot: "-- Порожньо / Не прив'язано --",
    spoolsHdr: "Бібліотека котушок",
    thName: "Назва котушки",
    thMat: "Матеріал",
    thRem: "Залишок",
    thAct: "Дія",
    addHdr: "Додати нову котушку",
    namePh: "Назва (напр. eSUN PLA Black)",
    matPh: "Матеріал (PLA)",
    addBtn: "+ Додати котушку",
    deleteBtn: "Видалити",
    savedAlert: "Прив'язку слотів успішно збережено!"
  },
  es: {
    slotLabel: "Ranura",
    toolheadPrefix: "Cabezal T",
    subtitle: "Gestión de 4 cabezales y protección contra enfriamiento de la cama",
    slotsHdr: "Configuración de ranuras activas (T0 – T3)",
    saveSlots: "Guardar asignación de ranuras",
    emptySlot: "-- Vacío / Sin asignar --",
    spoolsHdr: "Inventario de bobinas",
    thName: "Nombre de bobina",
    thMat: "Material",
    thRem: "Restante",
    thAct: "Acción",
    addHdr: "Añadir nueva bobina",
    namePh: "Nombre de bobina (ej. eSUN PLA Negro)",
    matPh: "Material (PLA)",
    addBtn: "+ Añadir bobina",
    deleteBtn: "Eliminar",
    savedAlert: "¡Asignación de ranuras guardada con éxito!"
  }
};

let currentLang = 'en';
const extra = {
 en: {reserve:'Safety reserve (g)', reserveHelp:'Added to each used toolhead for preflight only. It is not consumed.', save:'Save reserve', latest:'Last preflight', none:'No G-code has been checked yet.', delete:'Delete spool', printer:'U1 printer monitor', printerHelp:'Matching successful prints update inventory automatically. Export and upload never deduct filament.', enable:'Enable automatic accounting', savePrinter:'Save printer settings', test:'Test Connection', connected:'Connected', disconnected:'Disconnected'},
 ru: {reserve:'Страховой запас (г)', reserveHelp:'Добавляется к требованию каждой используемой головки только для проверки. Не списывается.', save:'Сохранить запас', latest:'Последняя проверка', none:'G-код ещё не проверялся.', delete:'Удалить катушку', printer:'Монитор принтера U1', printerHelp:'Успешная печать совпадающего файла обновляет остаток. Экспорт и загрузка не списывают пластик.', enable:'Включить автоматический учёт', savePrinter:'Сохранить настройки принтера', test:'Проверить соединение', connected:'Подключён', disconnected:'Нет соединения'},
 de: {reserve:'Sicherheitsreserve (g)', reserveHelp:'Nur für die Prüfung pro aktivem Druckkopf; wird nicht abgezogen.', save:'Reserve speichern', latest:'Letzte Prüfung', none:'Noch kein G-Code geprüft.', delete:'Spule löschen', printer:'U1-Druckermonitor', printerHelp:'Erfolgreiche passende Drucke aktualisieren den Bestand automatisch. Export und Upload ziehen nichts ab.', enable:'Automatische Erfassung aktivieren', savePrinter:'Druckereinstellungen speichern', test:'Verbindung testen', connected:'Verbunden', disconnected:'Getrennt'},
 uk: {reserve:'Запас безпеки (г)', reserveHelp:'Додається до кожної активної голівки лише для перевірки. Не списується.', save:'Зберегти запас', latest:'Остання перевірка', none:'G-код ще не перевірено.', delete:'Видалити котушку', printer:'Монітор принтера U1', printerHelp:'Успішний друк відповідного файлу оновлює залишок. Експорт і завантаження не списують пластик.', enable:'Увімкнути автоматичний облік', savePrinter:'Зберегти налаштування принтера', test:'Перевірити з’єднання', connected:'Підключено', disconnected:'Немає з’єднання'},
 es: {reserve:'Reserva de seguridad (g)', reserveHelp:'Se añade por cabezal activo solo para comprobar; no se descuenta.', save:'Guardar reserva', latest:'Última comprobación', none:'Todavía no se ha comprobado G-code.', delete:'Eliminar bobina', printer:'Monitor de impresora U1', printerHelp:'Las impresiones completadas del archivo coincidente actualizan el inventario. Exportar o subir no descuenta.', enable:'Activar contabilidad automática', savePrinter:'Guardar impresora', test:'Probar conexión', connected:'Conectada', disconnected:'Desconectada'}
};
const el = id => document.getElementById(id);
const node = (tag, value, className) => {
  const item = document.createElement(tag);
  if (value !== undefined) item.textContent = value;
  if (className) item.className = className;
  return item;
};
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
async function act(fn) {
  try { await fn(); } catch (error) { alert(error.message); }
}
function applyTexts(lang) {
  const t = dict[lang] || dict.en;
  el('t-subtitle').textContent = t.subtitle;
  el('t-slots-hdr').textContent = t.slotsHdr;
  el('t-save-slots').textContent = t.saveSlots;
  el('t-spools-hdr').textContent = t.spoolsHdr;
  el('t-th-name').textContent = t.thName;
  el('t-th-mat').textContent = t.thMat;
  el('t-th-rem').textContent = t.thRem;
  el('t-th-act').textContent = t.thAct;
  el('t-add-hdr').textContent = t.addHdr;
  el('new-name').placeholder = t.namePh;
  el('new-mat').placeholder = t.matPh;
  el('t-add-btn').textContent = t.addBtn;
  const x = extra[lang] || extra.en;
  el('reserve-label').textContent = x.reserve;
  el('reserve-help').textContent = x.reserveHelp;
  el('reserve-save').textContent = x.save;
  el('preflight-title').textContent = x.latest;
  el('printer-title').textContent = x.printer;
  el('printer-help').textContent = x.printerHelp;
  el('printer-enable-label').textContent = x.enable;
  el('printer-save').textContent = x.savePrinter;
  el('printer-test').textContent = x.test;
}
function updateMonitor(data) {
  const x = extra[currentLang] || extra.en;
  const status = data.monitor;
  const text = `${status.connected ? x.connected : x.disconnected} · ${status.state}` +
    (status.filename ? ` · ${status.filename}` : '') + (status.error ? ` · ${status.error}` : '');
  if (el('printer-status').textContent !== text) el('printer-status').textContent = text;
}
let preflightSignature = null;
let liveRequest = null;
let fullLoadInFlight = false;

function renderPreflight(data, force = false) {
  const signature = JSON.stringify(data.last_preflight);
  if (!force && signature === preflightSignature) return;
  preflightSignature = signature;
  const preflight = el('preflight-content');
  preflight.replaceChildren();
  if (!data.last_preflight) {
    preflight.textContent = (extra[currentLang] || extra.en).none;
    return;
  }
  const last = data.last_preflight;
  preflight.append(node('p', `${last.time || ''} — ${last.summary}`));
  if (!last.rows.length) return;
  const report = node('table');
  const head = node('tr');
  for (const heading of ['Tool', 'Spool', 'Required', 'Remaining', 'Status']) head.append(node('th', heading));
  report.append(head);
  for (const item of last.rows) {
    const tr = node('tr');
    for (const value of [item.tool, item.spool_name || '—', `${item.required_g} g`, item.remaining_g === null ? '—' : `${item.remaining_g} g`, item.status]) tr.append(node('td', value));
    report.append(tr);
  }
  preflight.append(report);
}

function renderAccounting(data) {
  const plans = Object.entries(data.plans || {}).sort((a,b) => b[1].created_at - a[1].created_at);
  const recentPlan = plans.length ? plans[0] : null;
  const recentRuns = Object.values(data.runs || {}).filter(run => recentPlan && run.plan_id === recentPlan[0]);
  const text = recentPlan ?
    `Planned file: ${recentPlan[1].filename} · ${recentPlan[1].status}` +
    (recentRuns.length ? ` · Printer job: ${recentRuns.sort((a,b) => b.start_time - a.start_time)[0].status}` : '') : '';
  if (el('accounting-status').textContent !== text) el('accounting-status').textContent = text;
}

function updateLiveState(data) {
  updateMonitor(data);
  renderPreflight(data);
  renderAccounting(data);
  const spools = data.spools || {};
  for (const row of el('spools-table').rows) {
    const spool = spools[row.dataset.spoolId];
    const input = row.querySelector('input');
    if (spool && input && document.activeElement !== input && input.dataset.dirty !== '1') {
      const value = String(spool.remaining_g);
      if (input.value !== value) input.value = value;
    }
  }
  for (const select of el('slots-container').querySelectorAll('select')) {
    for (const option of select.options) {
      const spool = spools[option.value];
      if (!spool) continue;
      const text = `${spool.name} (${spool.remaining_g}g, ${spool.material})`;
      if (option.textContent !== text) option.textContent = text;
    }
  }
}

async function pollLive() {
  if (liveRequest || fullLoadInFlight) return;
  liveRequest = api('/api/data');
  try { updateLiveState(await liveRequest); }
  catch (error) { console.warn('Dashboard live update failed:', error); }
  finally { liveRequest = null; }
}
async function changeLang(lang) {
  await act(async () => { await api('/api/lang', {language:lang}); await loadData(); });
}
async function loadData() {
  fullLoadInFlight = true;
  try {
    if (liveRequest) { try { await liveRequest; } catch (_) {} }
    const data = await api('/api/data');
    currentLang = data.language || 'en';
    el('lang-picker').value = currentLang;
    applyTexts(currentLang);
    el('reserve-input').value = data.safety_margin_g;
    el('printer-host').value = data.printer.host;
    el('printer-port').value = data.printer.port;
    el('printer-enabled').checked = data.printer.enabled;
    updateMonitor(data);
    const t = dict[currentLang] || dict.en;
    const x = extra[currentLang] || extra.en;
    const slots = el('slots-container');
    slots.replaceChildren();
    for (let i = 1; i <= 4; i++) {
      const row = node('div', undefined, 'slot-row');
      row.append(node('span', `${t.slotLabel} ${i} (${t.toolheadPrefix}${i-1}):`, 'slot-badge'));
      const select = node('select');
      select.name = `slot_${i}`;
      const empty = node('option', t.emptySlot);
      empty.value = '';
      select.append(empty);
      for (const [id, spool] of Object.entries(data.spools)) {
        const option = node('option', `${spool.name} (${spool.remaining_g}g, ${spool.material})`);
        option.value = id;
        select.append(option);
      }
      select.value = data.slots[i] || '';
      row.append(select);
      slots.append(row);
    }
    const table = el('spools-table');
    table.replaceChildren();
    for (const [id, spool] of Object.entries(data.spools)) {
      const row = node('tr');
      row.dataset.spoolId = id;
      const idCell = node('td'); const idText = node('code', id); idText.title = id; idCell.append(idText); row.append(idCell);
      const nameCell = node('td'); nameCell.append(node('strong', spool.name)); row.append(nameCell);
      row.append(node('td', spool.material));
      const weightCell = node('td');
      const input = node('input'); input.type='number'; input.min='0'; input.step='any'; input.value=spool.remaining_g;
      input.style.width='80px';
      input.addEventListener('input', () => { input.dataset.dirty = '1'; });
      input.addEventListener('change', () => act(async () => { await api('/api/spools/update', {id, remaining_g:input.value}); await loadData(); }));
      weightCell.append(input, document.createTextNode(' g')); row.append(weightCell);
      const actionCell = node('td'); const button = node('button', t.deleteBtn);
      button.style.background='var(--danger)'; button.style.padding='5px 10px';
      button.addEventListener('click', () => act(async () => { if (confirm(`${x.delete}: ${spool.name}?`)) { await api('/api/spools/delete', {id}); await loadData(); } }));
      actionCell.append(button); row.append(actionCell); table.append(row);
    }
    renderPreflight(data, true);
    renderAccounting(data);
  } finally { fullLoadInFlight = false; }
}
el('slots-form').addEventListener('submit', event => act(async () => {
  event.preventDefault(); const form = new FormData(event.target); const slots = {};
  for (let i=1; i<=4; i++) slots[i] = form.get(`slot_${i}`);
  await api('/api/slots', slots); await loadData();
}));
el('add-spool-form').addEventListener('submit', event => act(async () => {
  event.preventDefault();
  await api('/api/spools/add', {name:el('new-name').value, material:el('new-mat').value, remaining_g:el('new-weight').value});
  event.target.reset(); await loadData();
}));
el('reserve-form').addEventListener('submit', event => act(async () => {
  event.preventDefault(); await api('/api/settings', {safety_margin_g:el('reserve-input').value}); await loadData();
}));
function printerFields() {
  return {host:el('printer-host').value.trim(), port:Number(el('printer-port').value), enabled:el('printer-enabled').checked};
}
el('printer-form').addEventListener('submit', event => act(async () => {
  event.preventDefault(); await api('/api/printer/config', printerFields()); await loadData();
}));
el('printer-test').addEventListener('click', () => act(async () => {
  const result = await api('/api/printer/test', printerFields());
  const x = extra[currentLang] || extra.en;
  el('printer-status').textContent = `${x.connected} · ${result.result.state}`;
}));
setInterval(pollLive, 2500);
act(loadData);
</script>
</body>
</html>
"""


class WebHandler(BaseHTTPRequestHandler):
    store = STORE
    window_controller = None

    def log_message(self, fmt, *args):
        LOGGER.info("HTTP %s", fmt % args)

    def _response(self, status, data, content_type="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Snapmaker-Tracker", "1")
        self.end_headers()
        self.wfile.write(body)

    def _allowed_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{WEB_PORT}", f"localhost:{WEB_PORT}")

    def do_GET(self):
        if not self._allowed_host():
            return self._response(403, {"error": "Invalid host"})
        try:
            if self.path in ("/", "/index.html"):
                return self._response(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/api/data":
                return self._response(200, self.store.read())
            return self._response(404, {"error": "Not found"})
        except StorageError as exc:
            LOGGER.error("Database error: %s", exc)
            return self._response(500, {"error": str(exc)})
        except Exception:
            LOGGER.exception("HTTP GET error")
            return self._response(500, {"error": "Internal server error"})

    def do_POST(self):
        if not self._allowed_host():
            return self._response(403, {"error": "Invalid host"})
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{WEB_PORT}", f"http://localhost:{WEB_PORT}"):
            return self._response(403, {"error": "Invalid origin"})
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._response(403, {"error": "Cross-site request blocked"})
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self._response(415, {"error": "Content-Type must be application/json"})
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= 65536:
                return self._response(413, {"error": "Request body too large or empty"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValidationError("JSON body must be an object")
            if self.path == "/api/printer/test":
                config = printer_config({"host": body.get("host"), "port": body.get("port"), "enabled": True})
                try:
                    status = MoonrakerClient(config["host"], config["port"]).status()
                except MoonrakerError as exc:
                    return self._response(502, {"error": f"Printer unavailable: {exc}"})
                return self._response(200, {"status": "ok", "result": status})
            if self.path == "/api/window/show":
                if self.window_controller is None:
                    return self._response(503, {"error": "Dashboard window is unavailable"})
                self.window_controller.show()
                return self._response(200, {"status": "ok"})
            result = self.store.update(lambda db: self._change(db, body))
            return self._response(200, {"status": "ok", "result": result})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            return self._response(400, {"error": str(exc)})
        except StorageError as exc:
            LOGGER.error("Database error: %s", exc)
            return self._response(500, {"error": str(exc)})
        except Exception:
            LOGGER.exception("HTTP POST error")
            return self._response(500, {"error": "Internal server error"})

    def _change(self, db, body):
        if self.path == "/api/lang":
            lang = body.get("language")
            if lang not in I18N:
                raise ValidationError("Unsupported language")
            db["language"] = lang
        elif self.path == "/api/settings":
            db["safety_margin_g"] = weight(body.get("safety_margin_g"))
        elif self.path == "/api/printer/config":
            db["printer"] = printer_config(body)
        elif self.path == "/api/slots":
            if set(body) != set(db["slots"]):
                raise ValidationError("Exactly four slots are required")
            for slot, spool_id in body.items():
                if not isinstance(spool_id, str) or (spool_id and spool_id not in db["spools"]):
                    raise ValidationError(f"Invalid spool ID for slot {slot}")
            db["slots"] = body
        elif self.path == "/api/spools/add":
            spool_id = f"spool_{uuid.uuid4().hex}"
            db["spools"][spool_id] = {"name": label(body.get("name"), "Name"),
                "material": label(body.get("material"), "Material"),
                "remaining_g": weight(body.get("remaining_g"))}
            return spool_id
        elif self.path == "/api/spools/update":
            spool_id = body.get("id")
            if spool_id not in db["spools"]:
                raise ValidationError("Unknown spool ID")
            db["spools"][spool_id]["remaining_g"] = weight(body.get("remaining_g"))
        elif self.path == "/api/spools/delete":
            spool_id = body.get("id")
            if spool_id not in db["spools"]:
                raise ValidationError("Unknown spool ID")
            del db["spools"][spool_id]
            for slot, assigned in db["slots"].items():
                if assigned == spool_id:
                    db["slots"][slot] = ""
        else:
            raise ValidationError("Unknown API endpoint")


def create_tray_icon():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    for box, color in zip([(6, 6, 26, 26), (36, 6, 56, 26), (6, 36, 26, 56), (36, 36, 56, 56)],
                          [(240, 80, 80), (80, 160, 240), (80, 210, 120), (250, 190, 50)]):
        dc.ellipse(box, fill=color)
    return image


class DashboardWindow:
    """One pywebview window driven by the process's main GUI loop."""

    def __init__(self, webview_module=None):
        if webview_module is None:
            import webview
            webview_module = webview
        self.webview = webview_module
        self.window = webview_module.create_window(
            "Snapmaker U1 Spool Tracker", f"http://127.0.0.1:{WEB_PORT}",
            width=900, height=750, min_size=(760, 560), hidden=True)
        self.window.events.shown += self._on_shown
        self.window.events.closing += self._on_closing
        self.ready = False
        self.pending_show = False
        self.quitting = False

    def _on_shown(self):
        self.ready = True
        if self.quitting:
            self.window.destroy()
        elif self.pending_show:
            self.show()

    def _on_closing(self):
        if self.quitting:
            return True
        # The close event blocks the GUI thread. Hiding from a worker lets
        # pywebview dispatch to Cocoa/WinForms after the close is cancelled.
        threading.Thread(target=self.window.hide, daemon=True).start()
        return False

    def show(self):
        if self.quitting:
            return
        if not self.ready:
            self.pending_show = True
            return
        self.pending_show = False
        self.window.show()
        self.window.restore()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        if self.ready:
            self.window.destroy()

    def run(self):
        self.webview.start()


class TrayApp:
    def __init__(self):
        self.icon = None
        self.server = None
        self.window_controller = None
        self.stop_event = threading.Event()
        self.monitor = PrinterMonitor(STORE)

    def build_menu(self):
        import pystray
        db = STORE.read()
        tr = I18N.get(db["language"], I18N["en"])
        items = [pystray.MenuItem(tr["tray_title"], self._open_dashboard), pystray.Menu.SEPARATOR]
        for i in range(1, 5):
            spool = db["spools"].get(db["slots"][str(i)])
            title = (tr["tray_slot"].format(slot=i, idx=i-1, name=spool["name"], rem=spool["remaining_g"])
                     if spool else tr["tray_empty"].format(slot=i, idx=i-1))
            items.append(pystray.MenuItem(title, self._open_dashboard))
        items.extend([pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr["tray_open"], self._open_dashboard),
            pystray.MenuItem(tr["tray_quit"], self._quit)])
        return pystray.Menu(*items)

    def _open_dashboard(self, icon=None, item=None):
        if self.window_controller is not None:
            self.window_controller.show()

    def _quit(self, icon=None, item=None):
        if self.window_controller is not None:
            self.window_controller.quit()

    @staticmethod
    def _show_tray_icon(icon):
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(setattr, icon, "visible", True)
        else:
            icon.visible = True

    @staticmethod
    def _activate_existing():
        opener = build_opener(ProxyHandler({}))
        url = f"http://127.0.0.1:{WEB_PORT}"
        try:
            with opener.open(url + "/api/data", timeout=2) as response:
                if response.headers.get("X-Snapmaker-Tracker") != "1":
                    return False
        except Exception as exc:
            LOGGER.info("Existing tracker could not be identified: %s", exc)
            return False
        try:
            request = Request(url + "/api/window/show", data=b"{}",
                              headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(request, timeout=2):
                pass
        except Exception as exc:
            LOGGER.info("Existing tracker dashboard could not be activated: %s", exc)
        return True

    def _refresh(self):
        last = None
        while not self.stop_event.wait(1):
            try:
                stamp = STORE.path.stat().st_mtime_ns
                if stamp != last:
                    self._schedule_menu_refresh()
                    last = stamp
            except (OSError, StorageError):
                LOGGER.exception("Tray refresh failed")

    def _schedule_menu_refresh(self):
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._refresh_menu)
        else:
            self._refresh_menu()

    def _refresh_menu(self):
        if self.stop_event.is_set() or self.icon is None:
            return
        try:
            # Setting pystray's menu invokes NSStatusItem.setMenu_ on macOS.
            # AppKit requires this to run on the main application thread.
            self.icon.menu = self.build_menu()
        except (OSError, StorageError):
            LOGGER.exception("Tray refresh failed")

    def run(self):
        try:
            STORE.read()
            class DashboardHandler(WebHandler):
                pass
            self.server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), DashboardHandler)
        except OSError as exc:
            if exc.errno in (48, 98, 10048):
                if self._activate_existing():
                    return 0
            LOGGER.error("Cannot start local server: %s", exc)
            return 1
        except StorageError as exc:
            LOGGER.error("Database error: %s", exc)
            show_dialog(f"Inventory database error: {exc}")
            return 1
        server_started = False
        try:
            import pystray
            self.window_controller = DashboardWindow()
            DashboardHandler.window_controller = self.window_controller
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            server_started = True
            self.monitor.start()
            options = {}
            if sys.platform == "darwin":
                import AppKit
                options["darwin_nsapplication"] = AppKit.NSApplication.sharedApplication()
            self.icon = pystray.Icon("SnapmakerU1Tracker", create_tray_icon(),
                                    "Snapmaker U1 Tracker", menu=self.build_menu(), **options)
            threading.Thread(target=self._refresh, daemon=True).start()
            self.icon.run_detached(setup=self._show_tray_icon)
            self.window_controller.run()
            return 0
        finally:
            self.stop_event.set()
            self.monitor.stop()
            if self.icon is not None:
                self.icon.stop()
            if server_started:
                self.server.shutdown()
            self.server.server_close()


def main():
    configure_logging()
    LOGGER.info("Starting Snapmaker Spool Tracker %s", APP_VERSION)
    if len(sys.argv) > 1:
        return handle_slicer_hook(sys.argv[1])
    return TrayApp().run()


if __name__ == "__main__":
    sys.exit(main())
