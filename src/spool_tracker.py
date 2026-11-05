#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
from pathlib import Path

from gcode import GCodeError, parse_u1_gcode
from accounting import create_plan, reconcile_completed_review
from moonraker import MoonrakerClient, MoonrakerError, PrinterMonitor, decide_guard
from preflight import check, has_problem
from storage import IsolatedTestStore, Store, StorageError, ValidationError, data_directory, label, legacy_paths, printer_config, spool_color, weight
from backup import import_backup, write_backup
from tool_mapping import physical_weights
from print_statistics import summarize_prints
from spool_identity import calibration
from motion_stream import MotionStreamRecorder

APP_VERSION = "1.2.1-spoolman-preview1"
WEB_PORT = 8771
ISOLATED_ROOT = None
SLICE_ROOT = None
_normal_data = data_directory()
STORE = Store(_normal_data.parent / "SnapmakerSpoolTracker-SpoolmanPreview1", legacy_paths=())
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
        "slot_unassigned": "• Слот {slot}: Катушка не привязана! (Нужно: {req:.1f} гр.)",
        "slot_shortage": "• Слот {slot} ({name}): Остаток {rem:.1f} гр. / Нужно {req:.1f} гр. (Не хватает {short:.1f} гр.)",
        "tray_title": "Snapmaker U1 (4 Головки)",
        "tray_slot": "Слот {slot} (T{idx}): {name} — {rem:.0f} гр.",
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
    "ru": ("T{idx}: катушка не назначена; требуется {req:.1f} гр.",
           "T{idx} ({name}): требуется {req:.1f} гр. + запас {margin:.1f} гр.; остаток {rem:.1f} гр.",
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


EXPORT_MAPPING_NOTE = {
    "en": "Export check assumes T0–T3 match physical slots. The printer's final tool mapping is checked only when the print starts.",
    "ru": "При экспорте проверка предполагает прямое соответствие T0–T3 и слотов. Фактическая карта U1 проверяется при запуске печати.",
    "de": "Beim Export wird eine direkte T0–T3-Zuordnung angenommen. Die tatsächliche Zuordnung wird erst beim Druckstart geprüft.",
    "uk": "Під час експорту перевірка припускає пряме зіставлення T0–T3 і слотів. Фактична карта U1 перевіряється на старті друку.",
    "es": "Al exportar se supone una correspondencia directa T0–T3. La asignación real se comprueba al iniciar la impresión.",
}


def _save_preflight(rows, summary, reason=""):
    STORE.update(lambda db: db.__setitem__("last_preflight", {
        "summary": summary, "rows": rows, "reason": reason, "time": time.strftime("%Y-%m-%d %H:%M:%S")
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
    summary = "Export check: provisional attention required" if problem else "Export check: mapping unverified"
    mapping_note = EXPORT_MAPPING_NOTE.get(lang, EXPORT_MAPPING_NOTE["en"])
    try:
        _save_preflight(rows, summary, mapping_note)
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
        message = f'{tr["dialog_warn"]}\n{tr["dialog_desc"]}\n' + "\n".join(lines) + "\n\n" + mapping_note
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
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b1426; color: var(--text); padding: 22px; margin: 0; }
  .container { max-width: 1440px; margin: 0 auto; }
  .header-bar { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: center; padding: 0 2px 18px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
  .header-bar > div { flex: 1 1 280px; min-width: 0; }
  h1 { font-size: 21px; margin: 0; font-weight: 700; }
  .top-nav { display: flex; flex-wrap: wrap; gap: 4px; }
  .top-nav button { background: transparent; color: #aebbd0; border: 1px solid transparent; padding: 8px 12px; }
  .top-nav button[aria-current="page"] { color: #53c7f5; background: #172b42; border-color: #284967; }
  .top-nav button:hover { color: #fff; background: #223550; }
  .workspace { display: grid; grid-template-columns: minmax(205px, 260px) minmax(0, 1fr); gap: 16px; align-items: start; }
  .sidebar { position: sticky; top: 16px; border: 1px solid #293b56; background: #111f34; border-radius: 14px; padding: 18px 14px; }
  .sidebar h2 { color: #65cef8; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; margin: 0; }
  .sidebar .subtitle { line-height: 1.45; margin: 7px 0 15px; }
  .sidebar-slot { display: flex; align-items: center; gap: 14px; background: linear-gradient(135deg, #1b304b, #17283e); border: 1px solid #304865; border-radius: 10px; padding: 14px 12px; margin-top: 8px; overflow-wrap: anywhere; }
  .sidebar-slot.selected-head { border-color: #51ccfa; background: linear-gradient(135deg, #204761, #18344b); box-shadow: 0 0 0 1px #38bdf844; }
  .selected-label { display: block; color: #8ae2ff; font-weight: 700; font-size: 12px; margin-top: 6px; }
  .sidebar-status { color: #a7bdce; font-size: 12px; line-height: 1.4; margin: 10px 0 0; }
  .toolhead { position: relative; flex: 0 0 43px; height: 57px; display: grid; place-items: center; border-radius: 10px 10px 8px 8px; border: 1px solid #62758c; background: linear-gradient(150deg, #53677c, #2d4055); box-shadow: inset 0 1px 0 #8191a3, 0 3px 8px #0a142288; }
  .toolhead::before { content: ''; position: absolute; width: 13px; height: 7px; top: -8px; border: 1px solid #62758c; border-radius: 3px 3px 0 0; background: #41566c; }
  .toolhead::after { content: ''; position: absolute; bottom: -9px; width: 13px; height: 8px; background: #6b7f92; clip-path: polygon(0 0, 100% 0, 65% 100%, 35% 100%); }
  .toolhead strong { display: grid; place-items: center; width: 29px; height: 29px; border-radius: 50%; background: #10253a; border: 1px solid #7bd4f766; color: #8edfff; font-size: 11px; }
  .slot-info { min-width: 0; }
  .spool-heading { display: flex; align-items: center; gap: 7px; }
  .spool-icon { position: relative; flex: 0 0 15px; height: 15px; border: 2px solid #86a9c4; border-radius: 50%; box-shadow: inset 0 0 0 3px #294662; }
  .spool-icon::after { content: ''; position: absolute; inset: 4px; border-radius: 50%; background: #9db9cc; }
  .sidebar-slot .spool-name { margin-top: 0; }
  .sidebar-slot .spool-name { display: block; font-size: 14px; font-weight: 600; margin-top: 5px; }
  .sidebar-slot .spool-detail { display: block; color: #b0bed0; font-size: 12px; margin-top: 4px; }
  .main-content { min-width: 0; }
  .workspace.single-view { grid-template-columns: minmax(0, 1fr); }
  .workspace.single-view .main-content { max-width: 1000px; width: 100%; margin: 0 auto; }
  .overview-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .overview-heading h2 { margin-bottom: 8px; }
  .overview-status { font-size: 18px; font-weight: 700; margin: 6px 0; overflow-wrap: anywhere; }
  .overview-connection { color: #b4c9d9; background: #14273a; border: 1px solid #334a60; border-radius: 20px; padding: 7px 12px; font-size: 12px; }
  .overview-details { margin-top: 18px; border-top: 1px solid #34465e; padding-top: 16px; }
  .overview-details summary { cursor: pointer; color: #80d8fb; font-weight: 600; }
  #preflight-content { overflow-x: auto; }
  #preflight-content table { min-width: 600px; }
  #accounting-status { overflow-wrap: anywhere; }
  .spools-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .spools-actions h2 { margin-bottom: 0; }
  .inventory-add { margin-top: 20px; padding-top: 18px; border-top: 1px solid #34465e; }
  .inventory-add > summary { color: #80d8fb; font-weight: 700; cursor: pointer; }

  .lang-select { flex: 0 0 145px; width: 145px; max-width: 100%; box-sizing: border-box; background: #1e293b; border: 1px solid var(--border); color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }
  p.subtitle { color: var(--muted); margin: 6px 0 0 0; font-size: 14px; }
  .card { background: #19273b; border: 1px solid #30425d; border-radius: 14px; padding: 22px; margin-bottom: 16px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.22); }
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
  .color-picker { margin: 14px 0 0; }
  .color-picker summary { cursor: pointer; color: #bfe9fb; font-weight: 600; font-size: 13px; }
  .color-grid { display: grid; grid-template-columns: repeat(8, 28px); gap: 6px; margin-top: 10px; }
  .spool-inventory .color-grid { grid-template-columns: repeat(4, 28px); }
  .color-choice { width: 28px; height: 28px; padding: 0; border-radius: 7px; border: 1px solid #ffffff66; box-shadow: inset 0 0 0 1px #0002; }
  .color-choice:hover { filter: brightness(1.18); }
  .color-choice[aria-pressed="true"] { outline: 2px solid #76dcff; outline-offset: 2px; }
  .color-choice[aria-pressed="true"]::after { content: "✓"; color: white; font-size: 18px; font-weight: 800; text-shadow: 0 1px 3px #000, 0 0 3px #000; }
  .color-clear { margin-top: 10px; padding: 6px 9px; background: #314760; font-size: 12px; }
  .color-dot { display: inline-block; vertical-align: middle; width: 14px; height: 14px; border-radius: 50%; border: 1px solid #ffffff99; margin-right: 8px; }
  .spool-inventory { min-width: 560px; }
  .spool-inventory td:first-child code { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .spool-inventory td:nth-child(3), .spool-inventory td:nth-child(4) { white-space: nowrap; }
  .form-inline { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
  .form-inline input { flex: 1; min-width: 90px; }
  #view-settings .card { max-width: 860px; }
  #view-settings .card .subtitle { line-height: 1.5; }
  #printer-form { margin-top: 20px; }
  .printer-address { display: grid; grid-template-columns: minmax(0, 360px) minmax(80px, 105px); gap: 10px; }
  .printer-address input { width: 100%; min-width: 0; }
  .printer-toggle { display: flex; align-items: center; gap: 10px; margin: 20px 0; width: fit-content; cursor: pointer; }
  .printer-toggle input { flex: none; width: 17px; height: 17px; margin: 0; padding: 0; accent-color: var(--accent-btn); }
  .guard-control { display: grid; gap: 8px; max-width: 480px; }
  .guard-control label { font-weight: 600; font-size: 14px; }
  .guard-control select { width: 100%; min-width: 0; }
  #guard-mode-help { max-width: 650px; margin-top: 10px; }
  .printer-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
  #printer-status { margin-top: 18px; overflow-wrap: anywhere; }
  #heads-read { margin-top: 14px; }
  #reserve-form input { flex: 0 1 140px; min-width: 80px; }
  #latest-accounting:not(:empty) { background: #163347; border: 1px solid #2c6880; border-radius: 10px; padding: 4px 14px; margin: 16px 0; }
  #latest-accounting p { line-height: 1.5; }
  #review-content:not(:empty) { border-top: 1px solid #34465e; margin-top: 20px; padding-top: 20px; }
  button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid #66d0ff; outline-offset: 2px; }
  @media (max-width: 760px) { body { padding: 14px; } .workspace { grid-template-columns: 1fr; } .sidebar { position: static; } #sidebar-slots { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } .sidebar-slot { margin-top: 0; } .header-bar > div { flex-basis: 100%; } }
  @media (max-width: 560px) { .card { padding: 16px; } }

  /* Visual system from the supplied four-page reference. */
  :root { --bg:#0d1117; --card:#161d2b; --border:#243049; --accent:#8b97ad; --accent-btn:#2f6fd6; --text:#e6edf7; --muted:#8b97ad; --danger:#3a1d22; }
  body { background:#0d1117; color:#e6edf7; padding:0 24px 56px; font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; font-size:14px; }
  .container { max-width:1120px; }
  .header-bar { padding:24px 0; margin-bottom:28px; gap:16px; border-bottom:1px solid #1f2a40; }
  .header-bar .brand-logo { flex:0 0 40px; width:40px; height:40px; border-radius:11px; background:linear-gradient(135deg,#3b82f6,#22d3ee); display:grid; place-items:center; color:#06101f; font-weight:800; }
  .header-bar .brand-text { flex:1 1 320px; }
  h1 { font-size:18px; } p.subtitle { font-size:13px; }
  #t-subtitle,#build-label { display:inline; } #build-label { color:#8b97ad; } #test-badge { white-space:nowrap; font-size:12px; color:#fbbf24; background:#3a2c0d; border-radius:99px; padding:3px 10px; }
  .top-nav { margin-left:auto; gap:4px; } .top-nav button { padding:12px 11px; min-height:44px; border-radius:10px; color:#8b97ad; }
  .top-nav button[aria-current="page"] { background:#1d2a44; color:#9cc4ff; border-color:transparent; }
  .lang-select { flex:0 0 136px; width:136px; min-height:44px; background:#0d1117; }
  .workspace, .workspace.single-view { display:block; } .workspace.single-view .main-content { max-width:none; }
  .card { background:#161d2b; border:1px solid #243049; border-radius:14px; padding:20px; margin-bottom:16px; box-shadow:none; }
  .card h2, .inventory-add > summary, .calibration-details > summary { color:#8b97ad; font-size:12px; letter-spacing:.08em; font-weight:600; text-transform:uppercase; margin:0 0 14px; }
  .overview-card .overview-status { font-size:22px; margin:0; } .overview-card h2 { margin-bottom:6px; }
  .overview-connection { padding:3px 10px; color:#a3aec2; background:#222b3d; border:0; } .overview-connection.is-connected { color:#6ee7a0; background:#12301f; }
  .sidebar { position:static; background:none; border:0; padding:0; margin:0 0 16px; }
  #sidebar-slots { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
  .sidebar-slot { display:block; background:#161d2b; border:1px solid #243049; border-radius:14px; padding:20px; margin:0; min-width:0; }
  .sidebar-slot.selected-head { background:#161d2b; border-color:#6aa8ff; }
  .head-card-top { display:flex; justify-content:space-between; gap:6px; align-items:center; }
  .head-chip,.head-status { border-radius:99px; font-size:12px; padding:3px 10px; }
  .head-chip { background:#1d2a44; color:#9cc4ff; } .status-ok { background:#12301f; color:#6ee7a0; } .status-muted { background:#222b3d; color:#a3aec2; }
  .spool-heading { margin:14px 0 2px; } .spool-heading .color-dot { margin:0 5px 0 0; }
  .spool-name { font-size:15px; } .sidebar-slot .spool-detail { margin:2px 0 0; color:#8b97ad; font-size:13px; }
  .head-weight { font-size:26px; font-weight:700; margin:12px 0 8px; overflow-wrap:anywhere; }
  .head-bar { height:6px; background:#243049; border-radius:9px; }
  .head-required { color:#8b97ad; font-size:13px; margin-top:10px; }
  .overview-grid,.settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; } .overview-grid .card,.settings-grid .card { margin:0 0 16px; }
  #latest-accounting:not(:empty) { background:none; border:0; padding:0; margin:0; } #latest-accounting p { margin:0; }
  #review-content:not(:empty) { border:1px solid #243049; padding:20px; margin:0 0 16px; }
  #review-content:empty::before { content:'—'; color:#8b97ad; }
  .unaccounted-print { border-top:1px solid #1f2a40; padding:14px 0 0; }
  .overview-details { border-top:1px solid #243049; padding:20px; margin-top:0; }
  #slots-container { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
  .slot-row { display:block; margin:0; } .slot-badge { display:block; width:auto; font-size:13px; color:#8b97ad; font-weight:400; margin-bottom:6px; } .slot-row select { width:100%; }
  input,select { background:#0d1117; border:1px solid #2d3b57; border-radius:10px; min-height:44px; }
  button { background:#2f6fd6; min-height:44px; border-radius:10px; padding:12px 18px; } button:hover { background:#2863bf; }
  .spool-inventory { min-width:560px; } .spool-inventory thead { display:none; } .spool-inventory td { border-top:1px solid #1f2a40; border-bottom:0; }
  .spool-inventory .delete-spool { color:#ff9a9a; background:#3a1d22; padding:10px 16px; }
  .inventory-add { border:0; margin:0; padding:0; } .inventory-add > summary, .calibration-details > summary { list-style:none; cursor:pointer; }
  .color-grid { display:flex; flex-wrap:wrap; gap:8px; } .color-choice { width:32px; height:32px; min-height:32px; border-radius:9px; padding:0; }
  .color-clear,#printer-test,#backup-export,#backup-import,#cal-read,#heads-read { background:#222b3d; color:#e6edf7; }
  .printer-toggle input { min-height:0; }
  .printer-card { position:relative; } #printer-status { position:absolute; top:72px; right:20px; margin:0; max-width:38%; padding:3px 10px; border-radius:99px; color:#a3aec2; background:#222b3d; }
  #printer-status.is-connected { color:#6ee7a0; background:#12301f; }
  .head-counters-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin-top:10px; }
  .counter-card { background:#0d1117; border:1px solid #243049; border-radius:14px; padding:20px; }
  .counter-number { font-size:22px; font-weight:700; margin:6px 0; }
  #view-settings .card { max-width:none; } .printer-address { grid-template-columns:minmax(0,260px) 110px; } .guard-control { max-width:320px; }
  .history-card details > summary { list-style:none; text-transform:uppercase; letter-spacing:.08em; color:#8b97ad; font-size:12px; font-weight:600; }
  .history-card details > p:not(.subtitle) { border-top:1px solid #1f2a40; padding:14px 0; margin:0; }
  .history-row { display:flex; align-items:center; gap:12px; } .history-date { flex:0 0 150px; color:#8b97ad; font-size:13px; } .history-name { flex:1; overflow-wrap:anywhere; } .history-usage { text-align:right; } .history-row .head-status { white-space:nowrap; }
  #cal-form { display:grid; grid-template-columns:1fr 1fr; gap:16px; } #cal-form .form-inline { margin:0; } #cal-form .form-inline:nth-child(4) { display:flex; } #cal-form .form-inline:nth-child(4) input { min-width:0; } #cal-form .form-inline:last-child { grid-column:1 / -1; }
  @media(max-width:560px) { #printer-status { position:static; max-width:none; margin-top:16px; } .head-counters-grid { grid-template-columns:1fr 1fr; } #cal-form { grid-template-columns:1fr; } #cal-form .form-inline:last-child { grid-column:auto; } .history-row { flex-wrap:wrap; } .history-date { flex-basis:100%; } }
  .visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; }
  @media(max-width:800px) { #sidebar-slots,#slots-container { grid-template-columns:repeat(2,minmax(0,1fr)); } .header-bar .brand-text { flex:1 1 220px; } }
  @media(max-width:560px) { .overview-grid,.settings-grid { grid-template-columns:1fr; gap:0; } #sidebar-slots,#slots-container { grid-template-columns:1fr 1fr; } .header-bar { gap:12px; } .top-nav button { padding:9px; } .color-grid { gap:6px; } }


  .slot-select-wrap { display:flex; align-items:center; gap:8px; }
  .slot-select-wrap select { min-width:0; }
  .slot-selected-color { flex:0 0 16px; width:16px; height:16px; border-radius:50%; border:1px solid #a1adc4; }
  .slot-color-choices { margin-top:8px; position:relative; }
  .slot-color-choices summary { color:#9cc4ff; font-size:12px; cursor:pointer; }
  .slot-color-option { display:flex; align-items:center; width:100%; text-align:left; min-height:36px; padding:6px 8px; margin-top:4px; background:#222b3d; font-size:12px; font-weight:500; }
  .slot-color-option span:last-child { overflow-wrap:anywhere; }
  .sidebar-slot,.sidebar-slot.selected-head { background:transparent; border:0; box-shadow:none; text-align:center; padding:16px 10px 12px; }
  .printhead-visual { position:relative; width:80px; height:125px; margin:14px auto 20px; border:1px solid #777; border-radius:19px 19px 13px 13px; background:linear-gradient(#e1e1e1,#c9c9c9); display:flex; flex-direction:column; align-items:center; padding:14px 6px; gap:9px; }
  .printhead-visual::before { content:''; position:absolute; top:-21px; width:20px; height:20px; background:linear-gradient(#eeeeee,#a9a9a9); border-left:1px solid #999; border-right:1px solid #999; }
  .printhead-visual::after { content:''; position:absolute; bottom:-18px; width:25px; height:18px; background:#a5a5a5; clip-path:polygon(0 0,100% 0,100% 38%,68% 38%,50% 100%,32% 38%,0 38%); }
  .printhead-color { width:44px; height:44px; display:grid; place-items:center; border-radius:50%; background:#6f7c8a; color:#fff; font-size:14px; border:1px solid #0003; }
  .printhead-material { width:100%; background:#858585; color:#fff; border-radius:99px; padding:3px 5px; font-weight:700; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .selected-head .printhead-visual { box-shadow:0 0 0 3px #6aa8ff,0 0 20px #6aa8ff66; }
  .head-name { display:flex; justify-content:center; align-items:center; gap:0; overflow-wrap:anywhere; }
  .head-remaining { font-size:18px; font-weight:700; margin:5px 0; }
  .head-state,.head-required { font-size:12px; color:#a3aec2; margin:4px 0; }

</style>
</head>
<body>
<div class="container">
  <div class="header-bar">
    <div class="brand-logo">U1</div>
    <div class="brand-text">
      <h1 id="t-title">Snapmaker U1 Spool Tracker</h1>
      <p id="t-subtitle" class="subtitle">Filament inventory and print-start checks for four toolheads</p>
      <span id="build-label" class="subtitle">1.1.0-beta.1</span> · <span id="test-badge">TEST DATA</span>
    </div>
    <nav class="top-nav" aria-label="Main navigation">
      <button type="button" data-view="overview" aria-current="page" id="nav-overview">Overview</button>
      <button type="button" data-view="spools" id="nav-spools">Spools</button>
      <button type="button" data-view="history" id="nav-history">History</button>
      <button type="button" data-view="settings" id="nav-settings">Settings</button>
    </nav>
    <select id="lang-picker" class="lang-select" onchange="changeLang(this.value)">
      <option value="en">English (EN)</option>
      <option value="ru">Русский (RU)</option>
      <option value="de">Deutsch (DE)</option>
      <option value="uk">Українська (UK)</option>
      <option value="es">Español (ES)</option>
    </select>
  </div>

  <div class="workspace">
    <main class="main-content">
      <section id="view-overview" aria-labelledby="nav-overview">
  <div class="card overview-card">
    <div class="overview-heading"><div><h2 id="overview-title">Print overview</h2>
      <p id="overview-result" class="overview-status" aria-live="polite"></p>
      <p id="overview-file" class="subtitle"></p></div>
      <span id="overview-connection" class="overview-connection"></span></div>
    <div id="guard-content" aria-live="polite"></div>
  </div>
  <aside class="sidebar" aria-labelledby="sidebar-title">
    <h2 id="sidebar-title" class="visually-hidden">Toolheads and spools</h2>
    <p id="sidebar-help" class="visually-hidden">Assigned in Tracker</p>
    <div id="sidebar-slots"></div>
  </aside>
  <div class="overview-grid">
    <div class="card"><h2 id="latest-heading">Latest accounted print</h2><div id="latest-accounting" aria-live="polite"></div></div>
    <div id="review-content" class="card" aria-live="polite"></div>
  </div>
  <div hidden><span id="preflight-details-label"></span><span id="preflight-title"></span><div id="preflight-content"></div><p id="accounting-status"></p></div>
      </section>
      <section id="view-spools" aria-labelledby="nav-spools" hidden>
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
        <colgroup><col style="width:40%"><col style="width:16%"><col style="width:23%"><col style="width:21%"></colgroup>
        <thead>
          <tr>
            <th id="t-th-name">Spool Name</th>
            <th id="t-th-mat">Material</th>
            <th id="t-th-rem">Remaining</th>
            <th id="t-th-act">Action</th>
          </tr>
        </thead>
        <tbody id="spools-table"></tbody>
      </table>
    </div>

  </div><div class="card">
    <details class="inventory-add" open><summary id="t-add-hdr">Add New Spool</summary>
    <form id="add-spool-form" class="form-inline">
      <input type="text" id="new-name" placeholder="Spool name" required>
      <input type="text" id="new-mat" placeholder="Material" style="max-width: 130px;" required>
      <input type="number" id="new-weight" placeholder="Grams" value="1000" style="max-width: 100px;" required>
      <button type="submit" id="t-add-btn">+ Add Spool</button>
    </form>
    <details class="color-picker" id="new-color-picker" open>
      <summary id="new-color-title">Spool color: not set</summary>
      <input type="hidden" id="new-color" form="add-spool-form" value="">
      <div id="new-color-grid"></div>
      <button type="button" class="color-clear" id="new-color-clear">Clear color</button>
    </details>
    </details>
  </div><div class="card">
    <details class="calibration-details" open>
      <summary id="cal-title">Spool identification and weight estimate</summary>
      <p id="cal-help" class="subtitle">Tag and material parameters are optional. Weight calculated from commanded movement is an estimate, not a scale measurement. Automatic replenishment tracking is still experimental.</p>
      <form id="cal-form">
        <div class="form-inline"><select id="cal-spool" aria-label="Spool to calibrate" required></select></div>
        <div class="form-inline"><select id="cal-mode" aria-label="Spool identification mode">
          <option value="unverified">Identity not verified</option>
          <option value="tag">RFID tag</option>
          <option value="manual_confirmed">Manually confirmed, no tag (experimental)</option>
        </select></div>
        <div class="form-inline"><input id="cal-uid" type="text" aria-label="RFID tag UID" placeholder="RFID tag UID (optional)"></div>
        <div class="form-inline">
          <input id="cal-diameter" type="number" min="0.5" max="4" step="any" aria-label="Filament diameter, mm" placeholder="Diameter, mm">
          <input id="cal-density" type="number" min="0.1" max="5" step="any" aria-label="Density, g/cm³" placeholder="Density, g/cm³">
        </div>
        <div class="form-inline"><button id="cal-save" type="submit">Save spool settings</button><button id="cal-read" type="button">Read U1 tags</button></div>
      </form>
      <div id="cal-tags" aria-live="polite"></div>
    </details>
  </div>
      </section>
      <section id="view-history" aria-labelledby="nav-history" hidden>
        <div class="card history-card"><div id="history-content"></div></div>
      </section>
      <section id="view-settings" aria-labelledby="nav-settings" hidden>
  <div class="card printer-card">
    <h2 id="printer-title">U1 printer monitor</h2>
    <p id="printer-help" class="subtitle">Successful matching prints update inventory automatically. Export and upload never deduct filament.</p>
    <form id="printer-form">
      <div class="printer-address">
        <input id="printer-host" type="text" placeholder="U1.local" aria-label="Printer hostname or IP" required>
        <input id="printer-port" type="number" min="1" max="65535" aria-label="Moonraker port" required>
      </div>
      <label class="printer-toggle"><input id="printer-enabled" type="checkbox"> <span id="printer-enable-label">Enable automatic accounting</span></label>
      <div class="guard-control">
        <label id="guard-mode-label" for="guard-mode">Print start guard</label>
        <select id="guard-mode" aria-label="Print start guard">
          <option value="off">Off</option>
          <option value="warn">Warn only</option>
          <option value="strict">Pause on risk (experimental)</option>
        </select>
      </div>
      <p id="guard-mode-help" class="subtitle">Strict mode may pause after printing has already begun. Check the printer directly.</p>
      <div class="printer-actions">
        <button id="printer-save" type="submit">Save printer settings</button>
        <button id="printer-test" type="button">Test Connection</button>
      </div>
    </form>
    <p id="printer-status" class="subtitle" aria-live="polite">Disconnected</p>
    <button id="heads-read" type="button">Read head counters</button>
    <div id="heads-content" aria-live="polite"></div>
  </div>
  <div class="settings-grid"><div class="card">
    <h2 id="reserve-label">Safety reserve (g)</h2>
    <p id="reserve-help" class="subtitle">Added to each used toolhead for preflight only. It is not consumed.</p>
    <form id="reserve-form" class="form-inline">
      <input id="reserve-input" type="number" min="0" step="any" value="0" required>
      <button id="reserve-save" type="submit">Save reserve</button>
    </form>
  </div>
  <div class="card">
    <h2 id="backup-title">Backup &amp; Restore</h2>
    <p id="backup-help" class="subtitle"></p>
    <div class="form-inline">
      <button id="backup-export" type="button">Export Backup</button>
      <button id="backup-import" type="button">Import Backup</button>
    </div>
    <p id="backup-availability" class="subtitle" aria-live="polite"></p>
  </div></div>
      </section>
    </main>
  </div>
</div>

<script>
const dict = {
  en: {
    slotLabel: "Slot",
    toolheadPrefix: "Toolhead T",
    subtitle: "Filament inventory and print-start checks for four toolheads",
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
    subtitle: "Учёт филамента и проверка запуска печати для четырёх головок",
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
    subtitle: "Filamentbestand und Druckstartprüfung für vier Druckköpfe",
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
    subtitle: "Облік філаменту та перевірка старту друку для чотирьох голівок",
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
    subtitle: "Inventario de filamento y revisión del inicio para cuatro cabezales",
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
const gramUnit = () => currentLang === 'ru' ? 'гр.' : 'g';
const extra = {
 en: {reserve:'Safety reserve (g)', reserveHelp:'Added to each used toolhead for preflight only. It is not consumed.', save:'Save reserve', latest:'Last G-code check', none:'No G-code has been checked yet.', delete:'Delete spool', printer:'U1 printer monitor', printerHelp:'Matching successful prints update inventory automatically. Export and upload never deduct filament.', enable:'Enable automatic accounting', savePrinter:'Save printer settings', test:'Test Connection', connected:'Connected', disconnected:'Disconnected', backupTitle:'Backup & Restore', backupHelp:'Save a portable copy outside the app data folder before upgrading or uninstalling.', exportBackup:'Export Backup', importBackup:'Import Backup', backupUnavailable:'Backup and Restore are available in the desktop application window.', exportDone:'Backup saved.', importDone:'Backup restored. The dashboard is up to date.', importConfirm:'Importing a backup replaces your current inventory, settings, and accounting history. A local safety copy will be created. Continue?'},
 ru: {reserve:'Страховой запас (гр.)', reserveHelp:'Добавляется к требованию каждой используемой головки только для проверки. Не списывается.', save:'Сохранить запас', latest:'Последняя проверка G-кода', none:'G-код ещё не проверялся.', delete:'Удалить катушку', printer:'Монитор принтера U1', printerHelp:'Успешная печать совпадающего файла обновляет остаток. Экспорт и загрузка не списывают пластик.', enable:'Включить автоматический учёт', savePrinter:'Сохранить настройки принтера', test:'Проверить соединение', connected:'Подключён', disconnected:'Нет соединения', backupTitle:'Резервная копия и восстановление', backupHelp:'Сохраните переносимую копию вне папки данных приложения перед обновлением или удалением.', exportBackup:'Экспорт копии', importBackup:'Импорт копии', backupUnavailable:'Резервное копирование доступно в окне приложения.', exportDone:'Резервная копия сохранена.', importDone:'Данные восстановлены. Панель обновлена.', importConfirm:'Импорт заменит текущие катушки, настройки и историю учёта. Перед заменой будет создана локальная копия. Продолжить?'},
 de: {reserve:'Sicherheitsreserve (g)', reserveHelp:'Nur für die Prüfung pro aktivem Druckkopf; wird nicht abgezogen.', save:'Reserve speichern', latest:'Letzte G-Code-Prüfung', none:'Noch kein G-Code geprüft.', delete:'Spule löschen', printer:'U1-Druckermonitor', printerHelp:'Erfolgreiche passende Drucke aktualisieren den Bestand automatisch. Export und Upload ziehen nichts ab.', enable:'Automatische Erfassung aktivieren', savePrinter:'Druckereinstellungen speichern', test:'Verbindung testen', connected:'Verbunden', disconnected:'Getrennt', backupTitle:'Sichern & Wiederherstellen', backupHelp:'Vor Update oder Deinstallation eine portable Kopie außerhalb des App-Datenordners speichern.', exportBackup:'Backup exportieren', importBackup:'Backup importieren', backupUnavailable:'Backup und Wiederherstellung sind im App-Fenster verfügbar.', exportDone:'Backup gespeichert.', importDone:'Backup wiederhergestellt. Die Ansicht ist aktualisiert.', importConfirm:'Der Import ersetzt Spulen, Einstellungen und Abrechnungsverlauf. Zuvor wird eine lokale Sicherung erstellt. Fortfahren?'},
 uk: {reserve:'Запас безпеки (г)', reserveHelp:'Додається до кожної активної голівки лише для перевірки. Не списується.', save:'Зберегти запас', latest:'Остання перевірка G-коду', none:'G-код ще не перевірено.', delete:'Видалити котушку', printer:'Монітор принтера U1', printerHelp:'Успішний друк відповідного файлу оновлює залишок. Експорт і завантаження не списують пластик.', enable:'Увімкнути автоматичний облік', savePrinter:'Зберегти налаштування принтера', test:'Перевірити з’єднання', connected:'Підключено', disconnected:'Немає з’єднання', backupTitle:'Резервна копія та відновлення', backupHelp:'Збережіть переносиму копію поза текою даних застосунку перед оновленням чи видаленням.', exportBackup:'Експорт копії', importBackup:'Імпорт копії', backupUnavailable:'Резервне копіювання доступне у вікні застосунку.', exportDone:'Резервну копію збережено.', importDone:'Дані відновлено. Панель оновлена.', importConfirm:'Імпорт замінить котушки, налаштування та історію обліку. Спершу буде створено локальну копію. Продовжити?'},
 es: {reserve:'Reserva de seguridad (g)', reserveHelp:'Se añade por cabezal activo solo para comprobar; no se descuenta.', save:'Guardar reserva', latest:'Última comprobación de G-code', none:'Todavía no se ha comprobado G-code.', delete:'Eliminar bobina', printer:'Monitor de impresora U1', printerHelp:'Las impresiones completadas del archivo coincidente actualizan el inventario. Exportar o subir no descuenta.', enable:'Activar contabilidad automática', savePrinter:'Guardar impresora', test:'Probar conexión', connected:'Conectada', disconnected:'Desconectada', backupTitle:'Copia de seguridad y restauración', backupHelp:'Guarde una copia portátil fuera de la carpeta de datos antes de actualizar o desinstalar.', exportBackup:'Exportar copia', importBackup:'Importar copia', backupUnavailable:'La copia y restauración están disponibles en la ventana de la aplicación.', exportDone:'Copia guardada.', importDone:'Copia restaurada. El panel está actualizado.', importConfirm:'La importación reemplazará bobinas, ajustes e historial. Antes se creará una copia local. ¿Continuar?'}
};
const guardText = {
 en: {title:'Print start guard', off:'Off', warn:'Warn only', strict:'Pause on risk (experimental)', help:'Strict may pause after printing has begun. Check the printer directly.', confirm:'Strict mode can pause a running print after the file is checked. It has not yet been tested on a physical U1. Enable it?', ok:'Latest print start checked.', warning:'Attention needed. The print was not paused.', pause_requested:'Pause result is uncertain. Check the printer directly.', paused:'Tracker paused this print. Check the printer before deciding.', pause_failed:'Pause could not be verified. Check the printer directly.', resumed:'Print resumed after your decision.', cancelled:'Print cancelled after your decision.', resume:'Resume Anyway', cancel:'Cancel Print', resumeConfirm:'Resume this paused print despite the warning?', cancelConfirm:'Cancel this paused print?', recentPlan:'Previous planned file (separate from current G-code check)', job:'Printer job'},
 ru: {title:'Защита при запуске печати', off:'Выключена', warn:'Только предупреждать', strict:'Пауза при риске (экспериментально)', help:'Строгий режим может поставить на паузу уже начавшуюся печать. Проверяйте состояние на принтере.', confirm:'Строгий режим может поставить текущую печать на паузу после проверки файла. На физическом U1 пауза ещё не испытана. Включить?', ok:'Последний запуск проверен.', warning:'Нужна проверка. Печать не остановлена.', pause_requested:'Результат паузы неизвестен. Проверьте принтер напрямую.', paused:'Tracker поставил печать на паузу. Проверьте принтер перед решением.', pause_failed:'Пауза не подтверждена. Проверьте принтер напрямую.', resumed:'Печать продолжена по вашему решению.', cancelled:'Печать отменена по вашему решению.', resume:'Продолжить несмотря на риск', cancel:'Отменить печать', resumeConfirm:'Продолжить эту печать несмотря на предупреждение?', cancelConfirm:'Отменить эту печать?', recentPlan:'Предыдущий план (отдельно от текущей проверки G-кода)', job:'Задание принтера'},
 de: {title:'Schutz beim Druckstart', off:'Aus', warn:'Nur warnen', strict:'Bei Risiko pausieren (experimentell)', help:'Der strenge Modus kann nach Druckbeginn pausieren. Drucker direkt prüfen.', confirm:'Der strenge Modus kann einen laufenden Druck nach Dateiprüfung pausieren. Auf einem echten U1 noch nicht getestet. Aktivieren?', ok:'Letzter Druckstart geprüft.', warning:'Prüfung nötig. Druck nicht pausiert.', pause_requested:'Pause wird geprüft. Drucker kontrollieren.', paused:'Tracker hat diesen Druck pausiert. Drucker vor der Entscheidung prüfen.', pause_failed:'Pause nicht bestätigt. Drucker direkt prüfen.', resumed:'Druck nach Ihrer Entscheidung fortgesetzt.', cancelled:'Druck nach Ihrer Entscheidung abgebrochen.', resume:'Trotzdem fortsetzen', cancel:'Druck abbrechen', resumeConfirm:'Diesen pausierten Druck trotz Warnung fortsetzen?', cancelConfirm:'Diesen pausierten Druck abbrechen?', recentPlan:'Vorherige Planung (getrennt von aktueller G-Code-Prüfung)', job:'Druckauftrag'},
 uk: {title:'Захист на старті друку', off:'Вимкнено', warn:'Лише попереджати', strict:'Пауза за ризику (експериментально)', help:'Суворий режим може зупинити друк після його початку. Перевіряйте принтер.', confirm:'Суворий режим може зупинити поточний друк після перевірки файлу. На фізичному U1 ще не перевірено. Увімкнути?', ok:'Останній старт перевірено.', warning:'Потрібна перевірка. Друк не зупинено.', pause_requested:'Перевіряється пауза. Звіртеся з принтером.', paused:'Tracker зупинив цей друк. Перевірте принтер перед рішенням.', pause_failed:'Паузу не підтверджено. Перевірте принтер.', resumed:'Друк продовжено за вашим рішенням.', cancelled:'Друк скасовано за вашим рішенням.', resume:'Продовжити попри ризик', cancel:'Скасувати друк', resumeConfirm:'Продовжити цей друк попри попередження?', cancelConfirm:'Скасувати цей друк?', recentPlan:'Попередній план (окремо від поточної перевірки G-коду)', job:'Завдання принтера'},
 es: {title:'Protección al iniciar impresión', off:'Desactivada', warn:'Solo avisar', strict:'Pausar si hay riesgo (experimental)', help:'El modo estricto puede pausar tras iniciar la impresión. Compruebe la impresora.', confirm:'El modo estricto puede pausar una impresión en curso tras verificar el archivo. Aún no se ha probado en una U1 física. ¿Activarlo?', ok:'Último inicio verificado.', warning:'Se requiere revisión. La impresión no se pausó.', pause_requested:'Comprobando la pausa. Revise la impresora.', paused:'Tracker pausó esta impresión. Revise la impresora antes de decidir.', pause_failed:'No se pudo confirmar la pausa. Revise la impresora.', resumed:'Impresión reanudada por su decisión.', cancelled:'Impresión cancelada por su decisión.', resume:'Reanudar de todos modos', cancel:'Cancelar impresión', resumeConfirm:'¿Reanudar esta impresión pese al aviso?', cancelConfirm:'¿Cancelar esta impresión?', recentPlan:'Plan anterior (separado de la revisión actual de G-code)', job:'Trabajo de impresión'}
};
const guardPendingText = {
 en: {pause_requested:'Waiting for the U1 to process the pause. Check the printer and do not start another job.', pause_uncertain:'Pause outcome is unknown. Check the U1; do not retry or start another job until resolved. Strict mode was disabled.', resume_requested:'Waiting for the U1 to resume.', cancel_requested:'Waiting for the U1 to cancel.', action_uncertain:'Command outcome is unknown. Check the U1; do not retry or start another job until resolved. Strict mode was disabled.'},
 ru: {pause_requested:'Ожидается выполнение паузы на U1. Проверьте принтер и не запускайте другое задание.', pause_uncertain:'Результат паузы неизвестен. Проверьте U1; не повторяйте команду и не запускайте новое задание до выяснения. Строгий режим отключён.', resume_requested:'Ожидается продолжение печати на U1.', cancel_requested:'Ожидается отмена печати на U1.', action_uncertain:'Результат команды неизвестен. Проверьте U1; не повторяйте команду и не запускайте новое задание до выяснения. Строгий режим отключён.'},
 de: {pause_requested:'Warte auf Pause am U1. Drucker prüfen.', pause_uncertain:'Pause ungewiss. U1 prüfen, Befehl nicht wiederholen. Strenger Modus deaktiviert.', resume_requested:'Warte auf Fortsetzung am U1.', cancel_requested:'Warte auf Abbruch am U1.', action_uncertain:'Befehlsergebnis ungewiss. U1 prüfen, nicht wiederholen. Strenger Modus deaktiviert.'},
 uk: {pause_requested:'Очікується пауза на U1. Перевірте принтер.', pause_uncertain:'Результат паузи невідомий. Перевірте U1 і не повторюйте команду. Суворий режим вимкнено.', resume_requested:'Очікується продовження друку на U1.', cancel_requested:'Очікується скасування друку на U1.', action_uncertain:'Результат команди невідомий. Перевірте U1 і не повторюйте команду. Суворий режим вимкнено.'},
 es: {pause_requested:'Esperando la pausa en la U1. Revise la impresora.', pause_uncertain:'Resultado de pausa desconocido. Revise la U1 y no repita el comando. Modo estricto desactivado.', resume_requested:'Esperando la reanudación en la U1.', cancel_requested:'Esperando la cancelación en la U1.', action_uncertain:'Resultado desconocido. Revise la U1 y no repita el comando. Modo estricto desactivado.'}
};
for (const lang of Object.keys(guardPendingText)) Object.assign(guardText[lang], guardPendingText[lang]);
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
const PALETTE = ['#ffffff','#ea3323','#69504b','#ff7f26','#f2dfd0','#c5a48a','#c8c8c8','#795438',
  '#c78c65','#fff3da','#ffca2c','#ffed00','#d9ee23','#9dbd34','#315c3f','#2b9c70',
  '#8cb9a6','#53c5bc','#58b5cd','#9cbdc9','#008ac6','#46565a','#dce1e4','#116bd0',
  '#124a80','#151a1c','#989ba3','#d4cee6','#705bb4','#76147e','#e5007e','#ee4982','#ffc2d0','#951c35'];
function validColor(value) { return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value); }
function colorDot(value) {
  const dot = node('span', undefined, 'color-dot');
  dot.setAttribute('aria-hidden', 'true');
  if (validColor(value)) dot.style.backgroundColor = value;
  return dot;
}
function makePalette(selected, choose) {
  const group = node('div');
  const grid = node('div', undefined, 'color-grid');
  for (const color of PALETTE) {
    const button = node('button', undefined, 'color-choice'); button.type = 'button';
    button.style.backgroundColor = color; button.setAttribute('aria-label', color);
    button.setAttribute('aria-pressed', String(color === selected));
    button.addEventListener('click', () => choose(color)); grid.append(button);
  }
  group.append(grid);
  const clear = node('button', currentLang === 'ru' ? 'Убрать цвет' : 'Clear color', 'color-clear');
  clear.type = 'button'; clear.addEventListener('click', () => choose('')); group.append(clear);
  return group;
}
function renderNewColorPicker() {
  const input = el('new-color');
  const selected = validColor(input.value) ? input.value : '';
  el('new-color-title').textContent = (currentLang === 'ru' ? 'Цвет катушки: ' : 'Spool color: ') + (selected || (currentLang === 'ru' ? 'не выбран' : 'not set'));
  const root = el('new-color-grid'); root.replaceChildren();
  // Reuse the same palette for new and existing spools.
  const palette = makePalette(selected, color => { input.value = color; renderNewColorPicker(); });
  root.append(palette);
  el('new-color-clear').hidden = true;
}
function applyTexts(lang) {
  const t = dict[lang] || dict.en;
  const nav = ({ru:['Катушки','История','Настройки','Головки и катушки','Назначены в Tracker'],
    en:['Spools','History','Settings','Toolheads and spools','Assigned in Tracker'],
    de:['Spulen','Verlauf','Einstellungen','Druckköpfe und Spulen','Im Tracker zugewiesen'],
    uk:['Котушки','Історія','Налаштування','Головки й котушки','Призначено в Tracker'],
    es:['Bobinas','Historial','Ajustes','Cabezales y bobinas','Asignadas en Tracker']})[lang] || ['Spools','History','Settings','Toolheads and spools','Assigned in Tracker'];
  ['nav-spools','nav-history','nav-settings','sidebar-title','sidebar-help'].forEach((id, i) => { el(id).textContent = nav[i]; });
  el('nav-overview').textContent = ({ru:'Обзор', en:'Overview', de:'Übersicht', uk:'Огляд', es:'Resumen'})[lang] || 'Overview';
  el('overview-title').textContent = lang === 'ru' ? 'Состояние печати' : 'Print overview';
  el('latest-heading').textContent = lang === 'ru' ? 'Последняя учтённая печать' : 'Latest accounted print';
  el('preflight-details-label').textContent = lang === 'ru' ? 'Подробности проверки' : 'Check details';
  el('t-subtitle').textContent = lang === 'ru' ? 'Учёт филамента для четырёх головок' : t.subtitle;
  el('build-label').textContent = ' · 1.1.0-beta.1';
  el('test-badge').textContent = ({en:'test data', ru:'тестовая копия данных', de:'Testdaten', uk:'тестова копія даних', es:'datos de prueba'})[lang] || 'test data';
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
  renderNewColorPicker();
  el('t-add-btn').textContent = t.addBtn;
  const x = extra[lang] || extra.en;
  el('reserve-label').textContent = x.reserve;
  el('reserve-help').textContent = x.reserveHelp;
  el('reserve-save').textContent = x.save;
  el('preflight-title').textContent = x.latest;
  el('printer-title').textContent = x.printer;
  el('printer-help').textContent = x.printerHelp;
  el('printer-enable-label').textContent = x.enable;
  const g = guardText[lang] || guardText.en;
  el('guard-mode-label').textContent = g.title;
  el('guard-mode').options[0].textContent = g.off;
  el('guard-mode').options[1].textContent = g.warn;
  el('guard-mode').options[2].textContent = g.strict;
  el('guard-mode-help').textContent = g.help;
  el('printer-save').textContent = x.savePrinter;
  el('printer-test').textContent = x.test;
  el('backup-title').textContent = x.backupTitle;
  el('backup-help').textContent = x.backupHelp;
  el('backup-export').textContent = x.exportBackup;
  el('backup-import').textContent = x.importBackup;
  updateBackupAvailability();
}
function updateBackupAvailability() {
  const ready = Boolean(window.pywebview && window.pywebview.api);
  el('backup-export').disabled = !ready || backupBusy;
  el('backup-import').disabled = !ready || backupBusy;
  el('backup-availability').textContent = ready ? '' : (extra[currentLang] || extra.en).backupUnavailable;
}
window.addEventListener('pywebviewready', updateBackupAvailability);
function updateMonitor(data) {
  const x = extra[currentLang] || extra.en;
  const status = data.monitor;
  const text = `${status.connected ? x.connected : x.disconnected} · ${status.state}` +
    (status.filename ? ` · ${status.filename}` : '') + (status.error ? ` · ${status.error}` : '');
  if (el('printer-status').textContent !== text) el('printer-status').textContent = text;
  if (el('printer-status').classList) el('printer-status').classList.toggle('is-connected', !!status.connected);
}
let preflightSignature = null;
let guardSignature = null;
let liveRequest = null;
let fullLoadInFlight = false;

function renderPreflight(data, force = false) {
  const signature = JSON.stringify([data.last_preflight, data.spools, currentLang]);
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
  if (last.filename) preflight.append(node('p', last.filename, 'subtitle'));
  if (last.reason) preflight.append(node('p', last.reason, 'subtitle'));
  if (!last.rows.length) return;
  const report = node('table');
  const head = node('tr');
  for (const heading of ['Tool', 'Spool', 'Required', 'Remaining', 'Status']) head.append(node('th', heading));
  report.append(head);
  for (const item of last.rows) {
    const tr = node('tr');
    tr.append(node('td', item.tool));
    const spoolCell = node('td');
    const spool = (data.spools || {})[item.spool_id];
    if (spool && spool.color) spoolCell.append(colorDot(spool.color));
    spoolCell.append(node('span', item.spool_name || '—')); tr.append(spoolCell);
    for (const value of [`${item.required_g} ${gramUnit()}`, item.remaining_g === null ? '—' : `${item.remaining_g} ${gramUnit()}`, item.status]) tr.append(node('td', value));
    report.append(tr);
  }
  preflight.append(report);
}

function renderGuard(data, force = false) {
  const signature = JSON.stringify([data.last_guard, data.monitor.state, data.monitor.filename, currentLang]);
  if (!force && signature === guardSignature) return;
  guardSignature = signature;
  const content = el('guard-content');
  content.replaceChildren();
  const guard = data.last_guard;
  if (!guard || guard.state === 'ok') return;
  const g = guardText[currentLang] || guardText.en;
  content.append(node('p', `${guard.filename} — ${g[guard.state] || guard.state}`));
  if (guard.reason) content.append(node('p', guard.reason, 'subtitle'));
  if (guard.state !== 'paused' || !data.monitor.connected ||
      data.monitor.state !== 'paused' || data.monitor.filename !== guard.filename) return;
  const actions = node('div', undefined, 'form-inline');
  for (const [action, label, question] of [
    ['cancel', g.cancel, g.cancelConfirm], ['resume', g.resume, g.resumeConfirm]]) {
    const button = node('button', label);
    button.type = 'button';
    if (action === 'cancel') button.style.background = 'var(--danger)';
    button.addEventListener('click', () => act(async () => {
      if (!confirm(question)) return;
      await api('/api/guard/decision', {action});
      await loadData();
    }));
    actions.append(button);
  }
  content.append(actions);
}

function renderAccounting(data) {
  const g = guardText[currentLang] || guardText.en;
  const plans = Object.entries(data.plans || {}).sort((a,b) => b[1].created_at - a[1].created_at);
  const recentPlan = plans.length ? plans[0] : null;
  const recentRuns = Object.values(data.runs || {}).filter(run => recentPlan && run.plan_id === recentPlan[0]).sort((a,b) => b.start_time - a.start_time);
  const lastRun = recentRuns[0];
  const text = recentPlan ?
    `${g.recentPlan}: ${recentPlan[1].filename} · ${recentPlan[1].status}` +
    (lastRun ? ` · ${g.job}: ${lastRun.status}` + (lastRun.review_reason ? ` · ${lastRun.review_reason}` : '') : '') : '';
  if (el('accounting-status').textContent !== text) el('accounting-status').textContent = text;
}

let reviewSignature = '';
function renderReviews(data, force = false) {
  const content = el('review-content');
  if (!content) return;
  const entries = Object.values(data.runs || {})
    .filter(run => (run.status === 'review' && ['completed', 'cancelled'].includes(run.terminal_status)) || run.status === 'cancelled')
    .sort((a, b) => b.start_time - a.start_time);
  const signature = JSON.stringify([entries, currentLang]);
  if (!force && signature === reviewSignature) return;
  reviewSignature = signature;
  content.replaceChildren();
  if (!entries.length) return;
  const ru = currentLang === 'ru';
  content.append(node('h2', ru ? 'Неучтённые печати' : 'Unaccounted prints'));
  content.append(node('p', ru
    ? 'Для этих завершённых или отменённых печатей расход не удалось надёжно определить автоматически. Остатки катушек не изменены.'
    : 'Usage for these completed or cancelled prints could not be determined reliably. Spool balances were not changed.', 'subtitle'));
  for (const run of entries.slice(0, 3)) {
    const cancelled = run.status === 'cancelled' || run.terminal_status === 'cancelled';
    content.append(node('p', `${run.filename} · ${new Date(run.start_time * 1000).toLocaleString(currentLang)}${cancelled ? (ru ? ' · отменена' : ' · cancelled') : ''}`, 'unaccounted-print'));
  }
  if (entries.length > 3) content.append(node('p', ru ? `Ещё ${entries.length - 3} — во вкладке «История».` : `${entries.length - 3} more in History.`, 'subtitle'));
}

let historySignature = '';
function renderHistory(data, force = false) {
  const content = el('history-content');
  if (!content) return;
  const entries = Object.values(data.runs || {}).sort((a, b) => b.start_time - a.start_time).slice(0, 20);
  const signature = JSON.stringify([entries, data.spools, currentLang]);
  if (!force && signature === historySignature) return;
  const old = content.querySelector('details');
  const wasOpen = old ? old.open : true;
  historySignature = signature;
  content.replaceChildren();
  const latestBox = el('latest-accounting');
  latestBox.replaceChildren();
  if (!entries.length) {
    content.append(node('p', currentLang === 'ru' ? 'Записей о печати пока нет.' : 'No print records yet.', 'subtitle'));
    return;
  }
  const ru = currentLang === 'ru';
  const latestAuto = entries.find(run => run.status === 'committed' &&
    (run.accounting_method === 'motion_estimate' || (!run.accounting_method && Array.isArray(run.physical_weights))));
  if (latestAuto) {
    let amounts = [];
    if (latestAuto.accounting_method === 'motion_estimate') {
      amounts = Object.entries(latestAuto.motion_consumption || {}).map(([id, grams]) =>
        `${(data.spools[id] || {}).name || id}: ${grams} ${gramUnit()}`);
    } else {
      amounts = latestAuto.physical_weights.map((grams, i) => [grams, (latestAuto.physical_spool_ids || [])[i]])
        .filter(([grams]) => Number.isFinite(grams) && grams > 0)
        .map(([grams, id]) => `${(data.spools[id] || {}).name || id || '—'}: ${grams} ${gramUnit()}`);
    }
    const method = latestAuto.accounting_method === 'motion_estimate'
      ? (ru ? 'оценка по движению' : 'motion estimate')
      : (ru ? 'оценка по G-коду' : 'G-code estimate');
    latestBox.append(node('strong', latestAuto.filename));
    for (const amount of amounts) latestBox.append(node('p', amount, 'latest-amount'));
    latestBox.append(node('p', method, 'subtitle'));
  }
  const statusLabels = ru ? {active: 'выполняется', committed: 'учтено', review: 'расход не учтён', cancelled: 'отменено', error: 'ошибка'} : {};
  const details = node('details'); details.open = !!wasOpen;
  details.append(node('summary', ru ? 'История учёта (последние 20)' : 'Accounting history (last 20)'));
  details.append(node('p', ru ? 'Только задания, замеченные Tracker. Расход из G-code — оценка.' : 'Only jobs observed by Tracker. G-code usage is an estimate.', 'subtitle'));
  const headTotals = [0, 0, 0, 0];
  for (const run of Object.values(data.runs || {})) {
    if (run.status === 'committed' && !run.accounting_method && Array.isArray(run.physical_weights) && run.physical_weights.length === 4) {
      run.physical_weights.forEach((grams, i) => { if (Number.isFinite(grams) && grams >= 0) headTotals[i] += grams; });
    }
  }
  details.append(node('p', (ru ? 'Учтённая оценка из G-code по головкам: ' : 'Booked G-code estimates by head: ') +
    headTotals.map((grams, i) => `T${i}: ${Math.round(grams * 1000) / 1000} ${gramUnit()}`).join(', '), 'subtitle'));
  for (const run of entries) {
    const entry = node('p', undefined, 'history-row');
    const stamp = new Date(run.start_time * 1000).toLocaleString(currentLang);
    let text = `${stamp} · ${run.filename} · ${statusLabels[run.status] || run.status}`;
    if (run.status === 'committed' && run.accounting_method === 'manual_review') {
      text += (ru ? ' · подтверждено вручную: ' : ' · confirmed manually: ') + Object.entries(run.manual_consumption || {})
        .map(([id, grams]) => `${(data.spools[id] || {}).name || id}: ${grams} ${gramUnit()}${(run.manual_measurements || {})[id] ? (ru ? ' (по весам)' : ' (scale readings)') : ''}`).join(', ');
    } else if (run.status === 'committed' && run.accounting_method === 'motion_estimate') {
      text += (ru ? ' · оценка по движению: ' : ' · motion estimate: ') + Object.entries(run.motion_consumption || {})
        .map(([id, grams]) => `${(data.spools[id] || {}).name || id}: ${grams} ${gramUnit()}`).join(', ');
    } else if (run.status === 'committed' && Array.isArray(run.physical_weights)) {
      text += (ru ? ' · оценка: ' : ' · estimated: ') + run.physical_weights.map((grams, i) => `T${i}: ${grams} ${gramUnit()}`).join(', ');
    }
    const dateCell = node('span', stamp, 'history-date');
    const nameCell = node('strong', run.filename, 'history-name');
    const contentText = text.substring((`${stamp} · ${run.filename} · ${statusLabels[run.status] || run.status}`).length).replace(/^ · /, '');
    const usedCell = node('span', contentText, 'history-usage');
    const badgeLabel = run.terminal_status === 'cancelled' && run.status === 'committed' ? (ru ? 'отменено · учтено' : 'cancelled · accounted')
      : (run.terminal_status === 'cancelled' || run.status === 'cancelled') ? (ru ? 'отменено · расход не учтён' : 'cancelled · usage not accounted')
      : (statusLabels[run.status] || run.status);
    const badge = node('span', badgeLabel, 'head-status ' + (run.status === 'committed' ? 'status-ok' : 'status-muted'));
    entry.append(dateCell, nameCell, usedCell, badge); details.append(entry);
  }
  content.append(details);
}

let sidebarSignature = '';
function renderSidebar(data) {
  const root = el('sidebar-slots');
  if (!root) return;
  const monitor = data.monitor || {};
  const age = Date.now() / 1000 - Number(monitor.checked_at || 0);
  const headKnown = monitor.connected && monitor.state === 'printing' && Number.isInteger(monitor.active_head)
    && monitor.active_head >= 0 && monitor.active_head <= 3 && age >= -5 && age <= 30;
  const signature = JSON.stringify([data.slots, data.spools, data.last_preflight, data.last_guard, data.runs, currentLang, headKnown ? monitor.active_head : null, monitor.state, monitor.connected, monitor.active_job_key, age <= 30]);
  if (signature === sidebarSignature) return;
  sidebarSignature = signature;
  root.replaceChildren();
  const unassigned = ({ru:'Не назначена', en:'Not assigned', de:'Nicht zugewiesen', uk:'Не призначено', es:'Sin asignar'})[currentLang] || 'Not assigned';
  for (let i = 1; i <= 4; i++) {
    const spool = (data.spools || {})[(data.slots || {})[String(i)]];
    const item = node('div', undefined, 'sidebar-slot' + (headKnown && monitor.active_head === i - 1 ? ' selected-head' : ''));
    const last = data.last_preflight;
    const activeRun = last && last.job_key && (data.runs || {})[last.job_key];
    const guard = data.last_guard || {};
    const match = last && last.source === 'print_start' && last.job_key && guard.job_key === last.job_key && monitor.active_job_key === last.job_key
      && activeRun && ['active','review'].includes(activeRun.status) && !activeRun.terminal_status
      && monitor.connected && age >= -5 && age <= 30 && monitor.filename === last.filename && ['printing','paused'].includes(monitor.state);
    const row = match && Array.isArray(last.rows) ? last.rows.find(r => r.tool === `T${i-1}` && r.spool_id === (data.slots || {})[String(i)]) : null;
    const labels = currentLang === 'ru' ? {ok:'В порядке',unused:'Не используется',insufficient:'Недостаточно',unassigned:'Не назначена'} : {ok:'OK',unused:'Not used',insufficient:'Insufficient',unassigned:'Not assigned'};
    const illustration = node('div', undefined, 'printhead-visual');
    const colorMark = node('div', undefined, 'printhead-color');
    if (spool && validColor(spool.color)) {
      colorMark.style.backgroundColor = spool.color;
      const rgb = [1,3,5].map(j => parseInt(spool.color.slice(j,j+2),16));
      colorMark.style.color = (rgb[0]*299 + rgb[1]*587 + rgb[2]*114) / 1000 > 150 ? '#111' : '#fff';
    }
    colorMark.append(node('strong', `T${i-1}`));
    const hasEstimate = row && Number.isFinite(row.required_g) && row.required_g >= 0;
    const caption = hasEstimate ? `${row.required_g} ${gramUnit()}` : (spool ? spool.material : '—');
    const material = node('div', caption, 'printhead-material');
    if (hasEstimate) material.title = currentLang === 'ru' ? 'Плановый расход по проверке в начале печати' : 'Estimated usage from the print-start check';
    illustration.append(colorMark, material);
    item.append(illustration);
    const name = node('div', undefined, 'head-name');
    if (spool) name.append(colorDot(spool.color));
    name.append(node('strong', spool ? spool.name : unassigned)); item.append(name);
    item.append(node('div', spool ? `${spool.remaining_g} ${gramUnit()}` : '—', 'head-remaining'));
    if (row) {
      item.append(node('div', labels[row.status] || row.status, 'head-state'));
      if (hasEstimate) item.append(node('div', currentLang === 'ru' ? 'План на печать' : 'Print estimate', 'head-required'));
    }
    if (headKnown && monitor.active_head === i - 1) item.append(node('span', currentLang === 'ru' ? 'Выбрана принтером' : 'Selected by printer', 'selected-label'));
    root.append(item);
  }
  if (monitor.connected && monitor.state === 'printing' && !headKnown) root.append(node('p', currentLang === 'ru' ? 'Текущая головка не определена' : 'Current head unavailable', 'sidebar-status'));
}

function renderOverview(data) {
  const result = el('overview-result');
  if (!result) return;
  const ru = currentLang === 'ru';
  const last = data.last_preflight;
  const translations = {'Print start: OK':'Проверка запуска: всё в порядке', 'Print start: attention required':'Проверка запуска: требуется внимание',
    'Print start: unverified':'Проверка запуска: не подтверждена', 'Print start: material advisory':'Проверка запуска: обратите внимание на материал',
    'Export check: provisional attention required':'Проверка экспорта: требуется внимание', 'Export check: mapping unverified':'Проверка экспорта: привязка не подтверждена'};
  result.textContent = last ? ((ru && translations[last.summary]) || last.summary || (ru ? 'Проверка выполнена' : 'Check complete')) : (ru ? 'Проверка G-кода ещё не выполнялась' : 'No G-code check yet');
  el('overview-file').textContent = last ? [last.filename, last.time].filter(Boolean).join(' · ') : '';
  const monitor = data.monitor || {};
  let state = ru ? 'Монитор выключен' : 'Monitor off';
  if (monitor.connected) {
    const labels = ru ? {printing:'Печать идёт', paused:'Пауза', standby:'Ожидание', complete:'Печать завершена'} : {printing:'Printing', paused:'Paused', standby:'Standby', complete:'Print complete'};
    state = labels[monitor.state] || (ru ? 'Принтер подключён' : 'Printer connected');
  } else if (monitor.state !== 'disabled') state = ru ? 'Нет соединения с принтером' : 'Printer disconnected';
  el('overview-connection').textContent = state;
  el('overview-connection').classList.toggle('is-connected', !!monitor.connected);
}
function updateLiveState(data) {
  updateMonitor(data);
  renderOverview(data);
  renderPreflight(data);
  renderGuard(data);
  renderAccounting(data);
  renderReviews(data);
  renderHistory(data);
  renderSidebar(data);
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
      const text = `${spool.name} (${spool.remaining_g} ${gramUnit()}, ${spool.material})`;
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
    el('guard-mode').value = data.printer.guard_mode || 'warn';
    updateMonitor(data);
    renderOverview(data);
    renderSidebar(data);
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
        const option = node('option', `${spool.name} (${spool.remaining_g} ${gramUnit()}, ${spool.material})`);
        option.value = id;
        select.append(option);
      }
      select.value = data.slots[i] || '';
      const selectWrap = node('div', undefined, 'slot-select-wrap');
      const selectedDot = node('span', undefined, 'slot-selected-color'); selectedDot.setAttribute('aria-hidden', 'true');
      const refreshSelection = () => {
        const selected = data.spools[select.value];
        selectedDot.style.backgroundColor = selected && validColor(selected.color) ? selected.color : 'transparent';
        selectedDot.title = selected && validColor(selected.color) ? selected.color : '';
      };
      select.addEventListener('change', refreshSelection); refreshSelection();
      selectWrap.append(selectedDot, select); row.append(selectWrap);
      const choices = node('details', undefined, 'slot-color-choices');
      choices.append(node('summary', currentLang === 'ru' ? 'Выбрать по цвету' : 'Choose by color'));
      for (const [id, spool] of Object.entries(data.spools)) {
        const choice = node('button', undefined, 'slot-color-option'); choice.type = 'button';
        choice.append(colorDot(spool.color), node('span', `${spool.name} · ${spool.remaining_g} ${gramUnit()}`));
        choice.addEventListener('click', () => { select.value = id; refreshSelection(); choices.open = false; });
        choices.append(choice);
      }
      row.append(choices); slots.append(row);
    }
    const table = el('spools-table');
    table.replaceChildren();
    const calSelect = el('cal-spool');
    const previousCalSpool = calSelect.value;
    calSelect.replaceChildren();
    for (const [id, spool] of Object.entries(data.spools)) {
      const option = node('option', spool.name); option.value = id; calSelect.append(option);
    }
    if (data.spools[previousCalSpool]) calSelect.value = previousCalSpool;
    const ruCal = currentLang === 'ru';
    el('cal-title').textContent = ruCal ? 'Идентификация катушки и оценка веса' : 'Spool identification and weight estimate';
    el('cal-help').textContent = ruCal ? 'Метка и параметры необязательны. Вес по движению — оценка, не взвешивание. Учёт при автозамене пока экспериментальный.' : 'Tag and material parameters are optional. Weight calculated from commanded movement is an estimate, not a scale measurement. Automatic replenishment tracking is still experimental.';
    el('cal-uid').placeholder = ruCal ? 'RFID-метка (необязательно)' : 'RFID tag UID (optional)';
    el('cal-diameter').placeholder = ruCal ? 'Диаметр, мм' : 'Diameter, mm';
    el('cal-density').placeholder = ruCal ? 'Плотность, гр./см³' : 'Density, g/cm³';
    el('cal-save').textContent = ruCal ? 'Сохранить параметры' : 'Save spool settings';
    el('cal-read').textContent = ruCal ? 'Прочитать метки U1' : 'Read U1 tags';
    el('heads-read').textContent = ruCal ? 'Показать счётчики головок' : 'Read head counters';
    const modeLabels = ruCal ? ['Не подтверждена', 'RFID-метка', 'Ручная привязка без метки (эксперимент)'] : ['Identity not verified', 'RFID tag', 'Manually confirmed, no tag (experimental)'];
    Array.from(el('cal-mode').options).forEach((option, index) => { option.textContent = modeLabels[index]; });
    const loadCalibration = () => {
      const selected = data.spools[calSelect.value];
      const cfg = selected && selected.calibration ? selected.calibration : {};
      el('cal-uid').value = cfg.uid || '';
      el('cal-mode').value = cfg.identity_mode || (cfg.uid ? 'tag' : 'unverified');
      el('cal-diameter').value = cfg.diameter_mm ?? '';
      el('cal-density').value = cfg.density_g_cm3 ?? '';
    };
    calSelect.onchange = loadCalibration;
    loadCalibration();
    for (const [id, spool] of Object.entries(data.spools)) {
      const row = node('tr');
      row.dataset.spoolId = id;
      const nameCell = node('td'); nameCell.title = id;
      if (spool.color) nameCell.append(colorDot(spool.color));
      nameCell.append(node('strong', spool.name));
      const picker = node('details', undefined, 'color-picker');
      picker.append(node('summary', currentLang === 'ru' ? 'Цвет' : 'Color'));
      picker.append(makePalette(spool.color, color => act(async () => { await api('/api/spools/color', {id, color}); await loadData(); })));
      nameCell.append(picker); row.append(nameCell);
      row.append(node('td', spool.material));
      const weightCell = node('td');
      const input = node('input'); input.type='number'; input.min='0'; input.step='any'; input.value=spool.remaining_g;
      input.style.width='115px'; input.style.maxWidth='100%';
      input.addEventListener('input', () => { input.dataset.dirty = '1'; });
      input.addEventListener('change', () => act(async () => { await api('/api/spools/update', {id, remaining_g:input.value}); await loadData(); }));
      weightCell.append(input, document.createTextNode(` ${gramUnit()}`)); row.append(weightCell);
      const actionCell = node('td'); const button = node('button', t.deleteBtn, 'delete-spool');
      button.style.background='var(--danger)'; button.style.padding='5px 10px';
      button.addEventListener('click', () => act(async () => { if (confirm(`${x.delete}: ${spool.name}?`)) { await api('/api/spools/delete', {id}); await loadData(); } }));
      actionCell.append(button); row.append(actionCell); table.append(row);
    }
    renderPreflight(data, true);
    renderGuard(data, true);
    renderAccounting(data);
    renderReviews(data, true);
    renderHistory(data, true);
  } finally { fullLoadInFlight = false; }
}
function setView(name) {
  if (!['overview', 'spools', 'history', 'settings'].includes(name)) return;
  document.querySelector('.workspace').classList.toggle('single-view', name !== 'overview');
  document.querySelector('.sidebar').hidden = name !== 'overview';
  for (const view of ['overview', 'spools', 'history', 'settings']) {
    el(`view-${view}`).hidden = view !== name;
    const button = el(`nav-${view}`);
    if (view === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
}
for (const button of document.querySelectorAll('.top-nav [data-view]')) {
  button.addEventListener('click', () => setView(button.dataset.view));
}
el('slots-form').addEventListener('submit', event => act(async () => {
  event.preventDefault(); const form = new FormData(event.target); const slots = {};
  for (let i=1; i<=4; i++) slots[i] = form.get(`slot_${i}`);
  await api('/api/slots', slots); await loadData();
}));
el('add-spool-form').addEventListener('submit', event => act(async () => {
  event.preventDefault();
  await api('/api/spools/add', {name:el('new-name').value, material:el('new-mat').value, remaining_g:el('new-weight').value, color:el('new-color').value});
  event.target.reset(); el('new-color').value = ''; await loadData();
}));
el('reserve-form').addEventListener('submit', event => act(async () => {
  event.preventDefault(); await api('/api/settings', {safety_margin_g:el('reserve-input').value}); await loadData();
}));
function printerFields() {
  return {host:el('printer-host').value.trim(), port:Number(el('printer-port').value), enabled:el('printer-enabled').checked, guard_mode:el('guard-mode').value};
}
el('printer-form').addEventListener('submit', event => act(async () => {
  event.preventDefault();
  const fields = printerFields();
  if (fields.guard_mode === 'strict' && !confirm((guardText[currentLang] || guardText.en).confirm)) return;
  await api('/api/printer/config', fields); await loadData();
}));
el('printer-test').addEventListener('click', () => act(async () => {
  const result = await api('/api/printer/test', printerFields());
  const x = extra[currentLang] || extra.en;
  el('printer-status').textContent = `${x.connected} · ${result.result.state}`;
}));
el('cal-read').addEventListener('click', () => act(async () => {
  const result = await api('/api/printer/tags');
  const target = el('cal-tags'); target.replaceChildren();
  result.tags.forEach((uid, head) => {
    const row = node('div', undefined, 'form-inline');
    row.append(node('span', `T${head}: ${uid || (currentLang === 'ru' ? 'метка не обнаружена' : 'tag unavailable')}`));
    if (uid) {
      const use = node('button', currentLang === 'ru' ? 'Выбрать метку' : 'Use tag');
      use.type = 'button'; use.addEventListener('click', () => { el('cal-uid').value = uid; el('cal-mode').value = 'tag'; });
      row.append(use);
    }
    target.append(row);
  });
}));
el('heads-read').addEventListener('click', () => act(async () => {
  const data = await api('/api/printer/head-counters');
  const target = el('heads-content'); target.replaceChildren();
  target.append(node('p', currentLang === 'ru'
    ? 'Счётчики прошивки. Они не измеряют износ и не определяют срок обслуживания.'
    : 'Firmware counters do not measure wear or determine when maintenance is needed.', 'subtitle'));
  const grid = node('div', undefined, 'head-counters-grid');
  for (const row of data.heads) {
    const amount = row.switches_since_maintenance;
    const box = node('div', undefined, 'counter-card');
    box.append(node('strong', `T${row.head}`));
    box.append(node('div', amount === null ? (currentLang === 'ru' ? 'нет данных' : 'unavailable') : String(amount), 'counter-number'));
    box.append(node('div', currentLang === 'ru' ? 'переключений с отметки обслуживания' : 'switches since maintenance marker', 'subtitle'));
    grid.append(box);
  }
  target.append(grid);
}));
el('cal-form').addEventListener('submit', event => { event.preventDefault(); act(async () => {
  const id = el('cal-spool').value;
  if (!id) throw new Error(currentLang === 'ru' ? 'Сначала добавьте катушку.' : 'Add a spool first.');
  const uid = el('cal-uid').value.trim();
  const mode = el('cal-mode').value;
  if (mode === 'tag' && !confirm(currentLang === 'ru' ? 'Подтвердите: выбранная метка принадлежит этой катушке.' : 'Confirm that this tag belongs to the selected spool.')) return;
  if (mode === 'manual_confirmed' && !confirm(currentLang === 'ru' ? 'Подтвердите: катушка без метки определена вручную. Если её заменят, точность нельзя гарантировать. Автоматический учёт пока не включён.' : 'Confirm this untagged spool is identified manually. A replacement cannot be guaranteed to be detected. Automatic accounting is not enabled yet.')) return;
  const nullable = id => el(id).value.trim() === '' ? null : el(id).value;
  await api('/api/spools/calibration', {id, calibration: {uid, identity_mode: mode, diameter_mm: nullable('cal-diameter'), density_g_cm3: nullable('cal-density')}});
  await loadData();
}); });
let backupBusy = false;
async function withBackupDialog(action) {
  if (backupBusy) return;
  backupBusy = true;
  el('backup-export').disabled = true;
  el('backup-import').disabled = true;
  try { await action(); }
  finally { backupBusy = false; updateBackupAvailability(); }
}
el('backup-export').addEventListener('click', () => act(() => withBackupDialog(async () => {
  const result = await window.pywebview.api.export_backup();
  if (result.status === 'ok') alert((extra[currentLang] || extra.en).exportDone + '\\n' + result.path);
})));
el('backup-import').addEventListener('click', () => act(() => withBackupDialog(async () => {
  if (!confirm((extra[currentLang] || extra.en).importConfirm)) return;
  const result = await window.pywebview.api.import_backup();
  if (result.status === 'ok') { await loadData(); alert((extra[currentLang] || extra.en).importDone); }
})));
setInterval(pollLive, 2500);
act(loadData);
</script>
</body>
</html>
"""


from sender_view import install as install_sender_view
HTML_PAGE = install_sender_view(HTML_PAGE)
BASE_HTML_PAGE = HTML_PAGE
from forecast_view import install as install_forecast_view
HTML_PAGE = install_forecast_view(HTML_PAGE.replace('1.1.0-beta.1', APP_VERSION), lab=False)


from spoolman_view import install as install_spoolman_view
HTML_PAGE = install_spoolman_view(HTML_PAGE)


class WebHandler(BaseHTTPRequestHandler):
    store = STORE
    window_controller = None
    sender_controller = None
    forecast_service = None
    spoolman_bridge = None
    isolated = False

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
        if self.isolated and self.path not in ('/', '/index.html', '/api/data', '/api/statistics', '/api/forecast', '/api/sender/status'):
            return self._response(403, {'error': 'Printer access disabled in isolated mode'})
        try:
            if self.path == '/api/spoolman/status':
                from spoolman_bridge import blank
                db = self.store.read()
                return self._response(200, {'state': db.get('spoolman', blank()),
                    'linked': [dict(id=k, name=v['name']) for k, v in db['spools'].items() if v.get('spoolman')]})
            if self.path == '/api/forecast':
                return self._response(200, self.forecast_service.snapshot() if self.forecast_service else {'entries': [], 'revision': 0, 'safety_margin_g': 0, 'error': ''})
            if self.path in ("/", "/index.html"):
                return self._response(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/api/sender/status":
                return self._response(200, self.sender_controller.status() if self.sender_controller else {"enabled": False})
            if self.path == "/api/data":
                return self._response(200, self.store.read())
            if self.path == "/api/statistics":
                return self._response(200, summarize_prints(self.store.read()))
            if self.path == "/api/printer/head-counters":
                config = self.store.read()["printer"]
                if not config["enabled"]:
                    return self._response(409, {"error": "Printer monitor is disabled"})
                try:
                    counters = MoonrakerClient(config["host"], config["port"]).head_maintenance()
                except MoonrakerError as exc:
                    return self._response(502, {"error": f"Printer unavailable: {exc}"})
                return self._response(200, {"heads": counters})
            if self.path == "/api/printer/motion-evidence":
                config = self.store.read()["printer"]
                if not config["enabled"]:
                    return self._response(409, {"error": "Printer monitor is disabled"})
                try:
                    capture = MoonrakerClient(config["host"], config["port"]).motion_evidence()
                except MoonrakerError as exc:
                    return self._response(502, {"error": f"Printer motion evidence unavailable: {exc}"})
                return self._response(200, {"capture": capture})
            if self.path == "/api/printer/tags":
                config = self.store.read()["printer"]
                if not config["enabled"]:
                    return self._response(409, {"error": "Printer monitor is disabled"})
                try:
                    tags = MoonrakerClient(config["host"], config["port"]).tag_snapshot()
                except MoonrakerError as exc:
                    return self._response(502, {"error": f"Printer tags unavailable: {exc}"})
                return self._response(200, {"tags": tags})
            return self._response(404, {"error": "Not found"})
        except StorageError as exc:
            LOGGER.error("Database error: %s", exc)
            return self._response(500, {"error": str(exc)})
        except Exception:
            LOGGER.exception("HTTP GET error")
            return self._response(500, {"error": "Internal server error"})

    def do_POST(self):
        if self.isolated and self.path not in ('/api/window/show', '/api/lang', '/api/settings', '/api/slots', '/api/spools/add', '/api/spools/update', '/api/spools/delete', '/api/spools/color'):
            return self._response(403, {'error': 'Printer and accounting actions disabled in isolated mode'})
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
            body_limit = 46_000_000 if self.path == "/api/sender/select" else 65536
            if not 0 < length <= body_limit:
                return self._response(413, {"error": "Request body too large or empty"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValidationError("JSON body must be an object")
            if self.path.startswith('/api/spoolman/'):
                bridge = self.spoolman_bridge
                if bridge is None:
                    raise ValueError('Spoolman service unavailable')
                action = self.path.rsplit('/', 1)[1]
                if action == 'configure':
                    bridge.configure(body.get('url'), body.get('mode'), body.get('sole_sender'))
                elif action == 'refresh':
                    bridge.refresh()
                elif action == 'attach':
                    bridge.attach(body.get('id'), body.get('slot'))
                elif action == 'resolve':
                    bridge.resolve(body.get('id'), body.get('action'), body.get('note'))
                elif action == 'detach':
                    bridge.detach(body.get('id'))
                else:
                    raise ValueError('Unknown Spoolman action')
                return self._response(200, {'status': 'ok'})
            if self.path.startswith("/api/sender/"):
                if self.sender_controller is None:
                    return self._response(409, {"error": "Sender test environment is not enabled"})
                action = self.path.rsplit("/", 1)[1]
                result = self.sender_controller.select(body) if action == "select" else self.sender_controller.action(action, body)
                return self._response(200, result)
            if self.path == "/api/printer/test":
                config = printer_config({"host": body.get("host"), "port": body.get("port"), "enabled": True})
                try:
                    status = MoonrakerClient(config["host"], config["port"]).status()
                except MoonrakerError as exc:
                    return self._response(502, {"error": f"Printer unavailable: {exc}"})
                return self._response(200, {"status": "ok", "result": status})
            if self.path == "/api/guard/decision":
                try:
                    result = decide_guard(self.store, body.get("action"))
                except MoonrakerError as exc:
                    return self._response(409, {"error": str(exc)})
                return self._response(200, {"status": "ok", "result": result})
            if self.path == "/api/accounting/reconcile":
                if set(body) not in ({"job_key", "consumption"}, {"job_key", "consumption", "measurements"}) or not isinstance(body["job_key"], str):
                    raise ValidationError("Expected a print ID and confirmed per-spool amounts")
                applied = reconcile_completed_review(self.store, body["job_key"], body["consumption"], body.get("measurements"))
                return self._response(200, {"status": "ok", "applied": applied})
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
        if self.path in ('/api/spools/update', '/api/spools/delete', '/api/spools/color') and db['spools'].get(body.get('id'), {}).get('spoolman'):
            raise ValueError('Manage this spool in Spoolman; use Detach to remove its local link')
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
            external = [sid for sid in body.values() if db['spools'].get(sid, {}).get('spoolman')]
            if len(external) != len(set(external)):
                raise ValueError('One Spoolman spool cannot feed multiple heads')
            db["slots"] = body
        elif self.path == "/api/spools/add":
            spool_id = f"spool_{uuid.uuid4().hex}"
            db["spools"][spool_id] = {"name": label(body.get("name"), "Name"),
                "material": label(body.get("material"), "Material"),
                "remaining_g": weight(body.get("remaining_g"))}
            color = spool_color(body.get("color"))
            if color:
                db["spools"][spool_id]["color"] = color
            return spool_id
        elif self.path == "/api/spools/color":
            spool_id = body.get("id")
            if spool_id not in db["spools"]:
                raise ValidationError("Unknown spool ID")
            color = spool_color(body.get("color"))
            if color:
                db["spools"][spool_id]["color"] = color
            else:
                db["spools"][spool_id].pop("color", None)
        elif self.path == "/api/spools/update":
            spool_id = body.get("id")
            if spool_id not in db["spools"]:
                raise ValidationError("Unknown spool ID")
            db["spools"][spool_id]["remaining_g"] = weight(body.get("remaining_g"))
        elif self.path == "/api/spools/calibration":
            if set(body) != {"id", "calibration"} or body["id"] not in db["spools"]:
                raise ValidationError("Unknown spool or calibration fields")
            value = calibration(body["calibration"])
            if value["uid"] and any(item.get("calibration", {}).get("uid") == value["uid"]
                                    for key, item in db["spools"].items() if key != body["id"]):
                raise ValidationError("This tag is already assigned to another spool")
            db["spools"][body["id"]]["calibration"] = value
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


def create_tray_icon(status=None):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    for box, color in zip([(6, 6, 26, 26), (36, 6, 56, 26), (6, 36, 26, 56), (36, 36, 56, 56)],
                          [(240, 80, 80), (80, 160, 240), (80, 210, 120), (250, 190, 50)]):
        dc.ellipse(box, fill=color)
    if status in ('ok', 'shortage'):
        dc.ellipse((24, 24, 63, 63), fill='#258a47' if status == 'ok' else '#c93636')
        if status == 'ok':
            dc.line([(32, 43), (40, 51), (55, 35)], fill='white', width=6)
        else:
            dc.line([(35, 35), (53, 53)], fill='white', width=6)
            dc.line([(53, 35), (35, 53)], fill='white', width=6)
    return image


def create_toolhead_menu_icon(color=None, status=None):
    """Small neutral toolhead with the user's selected filament color."""
    from PIL import Image, ImageDraw
    from io import BytesIO
    image = Image.new('RGBA', (60, 72), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 1, 36, 10), fill='#aab6c0')
    draw.rounded_rectangle((8, 8, 52, 60), radius=9, fill='#d9dee3', outline='#7c8995', width=2)
    draw.polygon([(23, 60), (37, 60), (30, 70)], fill='#aab6c0')
    draw.ellipse((19, 18, 41, 40), fill=color or '#8595a3', outline='#5e6b77', width=2)
    draw.rounded_rectangle((15, 46, 45, 51), radius=2, fill='#88949e')
    if status in ('ok', 'shortage'):
        badge = create_tray_icon(status).crop((24, 24, 64, 64)).resize((28, 28))
        image.alpha_composite(badge, (32, 0))
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def install_macos_toolhead_icons(icon):
    """Add images to pystray's native items while preserving its callbacks."""
    import AppKit
    import Foundation
    original = icon._create_menu_item
    def create_item(descriptor, callbacks):
        item = original(descriptor, callbacks)
        if getattr(descriptor, '_tracker_toolhead', False):
            try:
                payload = create_toolhead_menu_icon(getattr(descriptor, '_tracker_color', None), getattr(descriptor, '_tracker_status', None))
                data = Foundation.NSData.dataWithBytes_length_(payload, len(payload))
                picture = AppKit.NSImage.alloc().initWithData_(data)
                picture.setSize_((18, 22))
                picture.setTemplate_(False)
                item.setImage_(picture)
            except Exception:
                LOGGER.exception('Could not render menu toolhead icon')
        return item
    icon._create_menu_item = create_item


def normalize_dialog_path(result):
    """pywebview returns a path on macOS and may return a sequence elsewhere."""
    if isinstance(result, (str, os.PathLike)):
        path = os.fspath(result)
        return path if isinstance(path, str) and path else None
    if isinstance(result, (list, tuple)):
        for item in result:
            path = normalize_dialog_path(item) if not isinstance(item, (list, tuple)) else None
            if path:
                return path
    return None


class BackupBridge:
    """Native dialogs are available only to pywebview's injected JS API."""

    def __init__(self, store, webview_module):
        self.store = store
        self.webview = webview_module
        self.window = None

    def hide(self):
        self.window.hide()

    def export_backup(self):
        filename = f"SnapmakerSpoolTracker-backup-{time.strftime('%Y-%m-%d')}.json"
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self.webview.FileDialog.SAVE, directory=str(Path.home() / "Documents"),
            save_filename=filename, file_types=("JSON backup (*.json)",)))
        if not selected:
            return {"status": "cancelled"}
        path = write_backup(self.store, selected, APP_VERSION)
        return {"status": "ok", "path": str(path)}

    def import_backup(self):
        selected = normalize_dialog_path(self.window.create_file_dialog(
            self.webview.FileDialog.OPEN, directory=str(Path.home() / "Documents"),
            file_types=("JSON backup (*.json)",)))
        if not selected:
            return {"status": "cancelled"}
        if ISOLATED_ROOT is not None:
            from backup import parse_backup
            from storage import empty_db
            restored = parse_backup(selected)
            restored['printer'] = empty_db()['printer']
            restored['monitor'] = empty_db()['monitor']
            destination = self.store.replace_snapshot(restored)
        else:
            destination = import_backup(self.store, selected)
        return {"status": "ok", "safety_backup": str(destination)}


class DashboardWindow:
    """One pywebview window driven by the process's main GUI loop."""

    def __init__(self, webview_module=None):
        if webview_module is None:
            import webview
            webview_module = webview
        self.webview = webview_module
        self.backup_bridge = BackupBridge(STORE, webview_module)
        self.window = webview_module.create_window(
            "Snapmaker U1 Spool Tracker", f"http://127.0.0.1:{WEB_PORT}",
            js_api=self.backup_bridge, width=900, height=750, min_size=(760, 560), hidden=True)
        self.backup_bridge.window = self.window
        self.window.events.shown += self._on_shown
        self.window.events.closing += self._on_closing
        self.ready = False
        self.pending_show = False
        self.quitting = False
        self.pending_forecast = False
        if hasattr(self.window.events, 'loaded'):
            self.window.events.loaded += self._on_loaded

    def _on_loaded(self):
        self.ready = True
        if self.pending_forecast:
            self.show_forecast()
        elif self.pending_show:
            self.show()

    def show_forecast(self):
        if self.quitting:
            return
        if not self.ready:
            self.pending_forecast = True
            return
        self.pending_forecast = False
        self.show()
        self.window.evaluate_js('refreshSliceForecast(true); setView("overview");')
        if sys.platform == 'darwin':
            from AppKit import NSApplication
            from PyObjCTools import AppHelper
            AppHelper.callAfter(NSApplication.sharedApplication().activateIgnoringOtherApps_, True)

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
        if sys.platform == 'darwin':
            # Cocoa's import sets Regular policy; override it before the GUI starts.
            from webview.platforms import cocoa
            import AppKit
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory)
        if ISOLATED_ROOT is not None:
            self.webview.start(private_mode=True, storage_path=str(ISOLATED_ROOT / 'webview'))
        else:
            self.webview.start()


TRAY_FORECAST_TEXT = {'en': {'ok': '✓ Enough including reserve',
        'shortage': '✕ Not enough filament',
        'unknown': '— Forecast unavailable',
        'plate': 'Plate',
        'mapping': 'Latest slice · assumed mapping 1→T0…4→T3',
        'after': 'after',
        'missing': 'short by'},
 'ru': {'ok': '✓ Хватает с резервом',
        'shortage': '✕ Не хватает',
        'unknown': '— Нет достоверного прогноза',
        'plate': 'Пластина',
        'mapping': 'Последняя нарезка · карта 1→T0…4→T3 предполагается',
        'after': 'после',
        'missing': 'не хватает'},
 'de': {'ok': '✓ Genug Filament einschließlich Reserve',
        'shortage': '✕ Nicht genug Filament',
        'unknown': '— Keine verlässliche Prognose',
        'plate': 'Platte',
        'mapping': 'Letzter Slicing-Vorgang · Zuordnung 1→T0…4→T3 angenommen',
        'after': 'danach',
        'missing': 'es fehlen'},
 'uk': {'ok': '✓ Вистачає з резервом',
        'shortage': '✕ Не вистачає',
        'unknown': '— Немає достовірного прогнозу',
        'plate': 'Пластина',
        'mapping': 'Остання нарізка · відповідність 1→T0…4→T3 припускається',
        'after': 'після',
        'missing': 'не вистачає'},
 'es': {'ok': '✓ Suficiente filamento con reserva',
        'shortage': '✕ Filamento insuficiente',
        'unknown': '— Previsión no disponible',
        'plate': 'Placa',
        'mapping': 'Último laminado · asignación supuesta 1→T0…4→T3',
        'after': 'después',
        'missing': 'faltan'}}


class TrayApp:
    def __init__(self):
        self.icon = None
        self.server = None
        self.window_controller = None
        self.stop_event = threading.Event()
        self.monitor = PrinterMonitor(STORE, on_guard=self._notify_guard)
        self.motion_diagnostic = MotionStreamRecorder(STORE)

    @staticmethod
    def _notify_guard(snapshot):
        guard = snapshot.get("last_guard") or {}
        filename = guard.get("filename", "")
        lang = snapshot.get("language", "en")
        messages = {
            "en": ("Check this print on the U1. It continues; Tracker found a filament warning.",
                   "Tracker paused this print. Check the U1, then open Tracker to cancel or resume.",
                   "Tracker could not confirm a pause. Check the U1 directly."),
            "ru": ("Проверьте печать на U1. Она продолжается; Tracker нашёл проблему с филаментом.",
                   "Tracker поставил печать на паузу. Проверьте U1, затем откройте Tracker для отмены или продолжения.",
                   "Tracker не смог подтвердить паузу. Проверьте U1 напрямую."),
            "de": ("Druck am U1 prüfen. Er läuft weiter; Tracker meldet ein Filamentproblem.",
                   "Tracker hat diesen Druck pausiert. U1 prüfen und in Tracker abbrechen oder fortsetzen.",
                   "Tracker konnte die Pause nicht bestätigen. U1 direkt prüfen."),
            "uk": ("Перевірте друк на U1. Він триває; Tracker виявив проблему з філаментом.",
                   "Tracker зупинив друк. Перевірте U1, потім відкрийте Tracker для скасування або продовження.",
                   "Tracker не зміг підтвердити паузу. Перевірте U1 безпосередньо."),
            "es": ("Revise la impresión en la U1. Continúa; Tracker detectó un problema de filamento.",
                   "Tracker pausó esta impresión. Revise la U1 y abra Tracker para cancelar o reanudar.",
                   "Tracker no pudo confirmar la pausa. Revise la U1 directamente."),
        }
        state = guard.get("state")
        pending = {
            "en": "Tracker is requesting a pause. Check the U1 and do not start another job while the request is unresolved.",
            "ru": "Tracker запрашивает паузу. Проверьте U1 и не запускайте другое задание до выяснения результата.",
            "de": "Tracker fordert eine Pause an. U1 während der Verarbeitung prüfen.",
            "uk": "Tracker запитує паузу. Перевірте U1 під час обробки запиту.",
            "es": "Tracker solicita una pausa. Revise la U1 mientras procesa la solicitud.",
        }
        uncertain = {
            "en": "Command outcome is unknown. Check the U1 directly; do not repeat the command or start another job until resolved. Strict mode was disabled.",
            "ru": "Результат команды неизвестен. Проверьте U1; не повторяйте команду и не запускайте другое задание до выяснения. Строгий режим отключён.",
            "de": "Befehlsergebnis unbekannt. U1 direkt prüfen, Befehl nicht wiederholen. Strenger Modus deaktiviert.",
            "uk": "Результат команди невідомий. Перевірте U1 і не повторюйте команду. Суворий режим вимкнено.",
            "es": "Resultado desconocido. Revise la U1 y no repita el comando. Modo estricto desactivado.",
        }
        index = {"warning": 0, "paused": 1, "pause_failed": 2}.get(state)
        message = (pending.get(lang, pending['en']) if state == "pause_requested" else
                   uncertain.get(lang, uncertain['en']) if state in ("pause_uncertain", "action_uncertain") else
                   messages.get(lang, messages['en'])[index] if index is not None else "")
        if message:
            show_dialog(f"{filename}\n\n{message}", lang)

    def _forecast_snapshot(self):
        service = getattr(self, 'forecast_service', None)
        return service.snapshot() if service is not None else {}

    @staticmethod
    def _forecast_status(snapshot):
        entry = next((e for e in snapshot.get('entries', [])
                      if e['source'] == snapshot.get('latest')), None)
        if snapshot.get('error') or (entry and entry.get('unknown')) or entry is None or not any(r['used'] > 0 for r in entry['rows']):
            return 'unknown', entry
        if any(r['used'] > 0 and not r.get('spool_id') for r in entry['rows']):
            return 'unknown', entry
        return ('shortage' if entry['shortage'] else 'ok'), entry

    def build_menu(self, snapshot=None):
        import pystray
        db = STORE.read()
        tr = I18N.get(db["language"], I18N["en"])
        items = [pystray.MenuItem(tr["tray_title"], self._open_dashboard), pystray.Menu.SEPARATOR]
        snapshot = self._forecast_snapshot() if snapshot is None else snapshot
        status, entry = self._forecast_status(snapshot)
        forecast_text = TRAY_FORECAST_TEXT.get(db['language'], TRAY_FORECAST_TEXT['en'])
        if snapshot:
            label = forecast_text[status]
            if entry:
                from datetime import datetime
                plate = entry['label'].split()[-1]
                observed = datetime.fromtimestamp(entry.get('observed_at', 0)).strftime('%d.%m %H:%M')
                label += f" · {forecast_text['plate']} {plate} · {observed}"
            items.append(pystray.MenuItem(label, self._open_forecast))
            items.append(pystray.MenuItem(forecast_text['mapping'], self._open_forecast))
            items.append(pystray.Menu.SEPARATOR)
        for i in range(1, 5):
            spool = db["spools"].get(db["slots"][str(i)])
            unit = 'гр.' if db['language'] == 'ru' else 'g'
            empty = {'ru': 'Не назначена', 'uk': 'Не призначена', 'de': 'Nicht zugewiesen', 'es': 'Sin asignar'}.get(db['language'], 'Unassigned')
            title = (f"T{i-1} · {spool['name']} — {spool['remaining_g']:g} {unit}"
                     if spool else f'T{i-1} · {empty}')
            if entry and not snapshot.get('error'):
                row = entry['rows'][i-1]
                if row['used'] > 0:
                    if not row.get('spool_id'):
                        title += ' · —'
                    elif row.get('unknown'):
                        title += ' · ? Spoolman'
                    elif row['enough']:
                        title += f" · ✓ {forecast_text['after']} ≈ {row['after']:g} {unit}"
                    else:
                        missing = max(0, snapshot['safety_margin_g'] - row['after'])
                        title += f" · ✕ {forecast_text['missing']} {missing:g} {unit}"
            item = pystray.MenuItem(title, self._open_forecast if entry else self._open_dashboard)
            row = entry['rows'][i-1] if entry and not snapshot.get('error') else None
            item._tracker_status = ('ok' if row['enough'] else 'shortage') if row and row['used'] > 0 and row.get('spool_id') and not row.get('unknown') else None
            item._tracker_toolhead = True
            item._tracker_color = spool.get('color') if spool else None
            items.append(item)
        items.extend([pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr["tray_open"], self._open_dashboard),
            pystray.MenuItem(tr["tray_quit"], self._quit)])
        return pystray.Menu(*items)

    def _open_forecast(self, icon=None, item=None):
        if self.window_controller is not None:
            # evaluate_js waits for Cocoa; menu callbacks run on the Cocoa thread.
            threading.Thread(target=self.window_controller.show_forecast, daemon=True).start()

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
                stamp = (STORE.path.stat().st_mtime_ns, json.dumps(self._forecast_snapshot(), sort_keys=True))
                if stamp != last:
                    self._schedule_menu_refresh()
                    last = stamp
            except (OSError, StorageError):
                LOGGER.exception("Tray refresh failed")

    def _on_slice_completed(self):
        if sys.platform == 'darwin':
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._show_slice_menu)
        else:
            self._schedule_menu_refresh()

    def _show_slice_menu(self):
        # NSStatusBarButton opens the native menu without revealing the dashboard.
        # Menu tracking is modal: never replace its NSMenu while it is open.
        if self.stop_event.is_set() or self.icon is None or getattr(self, '_menu_presented', False):
            return
        self._refresh_menu()
        self._menu_presented = True
        try:
            self.icon.visible = True
            self.icon._status_item.button().performClick_(None)
        except Exception:
            LOGGER.exception('Could not open the slice forecast menu')
        finally:
            self._menu_presented = False
            self._refresh_menu()

    def _schedule_menu_refresh(self):
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._refresh_menu)
        else:
            self._refresh_menu()

    def _refresh_menu(self):
        if self.stop_event.is_set() or self.icon is None or getattr(self, '_menu_presented', False):
            return
        try:
            # Setting pystray's menu invokes NSStatusItem.setMenu_ on macOS.
            # AppKit requires this to run on the main application thread.
            snapshot = self._forecast_snapshot()
            self.icon.menu = self.build_menu(snapshot)
            status, _ = self._forecast_status(snapshot)
            self.icon.icon = create_tray_icon(status)
        except (OSError, StorageError):
            LOGGER.exception("Tray refresh failed")

    def run(self):
        global WEB_PORT
        try:
            STORE.read()
            class DashboardHandler(WebHandler):
                pass
            DashboardHandler.store = STORE
            DashboardHandler.isolated = ISOLATED_ROOT is not None
            self.server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), DashboardHandler)
            WEB_PORT = self.server.server_port
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
            if ISOLATED_ROOT is None:
                from spoolman_bridge import Bridge
                self.spoolman_bridge = Bridge(STORE)
                self.spoolman_bridge.start()
                DashboardHandler.spoolman_bridge = self.spoolman_bridge
                self.monitor.start()
                self.motion_diagnostic.start()
            from forecast_service import ForecastService
            self.forecast_service = ForecastService(STORE, self._on_slice_completed, SLICE_ROOT)
            DashboardHandler.forecast_service = self.forecast_service
            if hasattr(self, "spoolman_bridge"):
                self.forecast_service.inventory_refresh = self.spoolman_bridge.refresh
            if ISOLATED_ROOT is not None:
                (ISOLATED_ROOT / 'runtime.json').write_text(json.dumps({'url': f'http://127.0.0.1:{WEB_PORT}', 'watch': str(SLICE_ROOT), 'version': APP_VERSION}))
            options = {}
            if sys.platform == "darwin":
                import AppKit
                options["darwin_nsapplication"] = AppKit.NSApplication.sharedApplication()
            self.icon = pystray.Icon("SnapmakerU1Tracker", create_tray_icon(),
                                    "Snapmaker U1 Tracker", menu=self.build_menu(), **options)
            if sys.platform == 'darwin':
                install_macos_toolhead_icons(self.icon)
            threading.Thread(target=self._refresh, daemon=True).start()
            self.icon.run_detached(setup=self._show_tray_icon)
            self.forecast_service.start()
            self.window_controller.run()
            return 0
        finally:
            self.stop_event.set()
            if hasattr(self, 'spoolman_bridge'):
                self.spoolman_bridge.stop()
            if hasattr(self, 'forecast_service'):
                self.forecast_service.stop()
            self.motion_diagnostic.stop()
            self.monitor.stop()
            if self.icon is not None:
                self.icon.stop()
            if server_started:
                self.server.shutdown()
            self.server.server_close()


def configure_runtime(arguments):
    """Explicit test sandbox; never reads/imports the installed inventory."""
    import argparse
    global STORE, WEB_PORT, ISOLATED_ROOT, SLICE_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--isolated-root', type=Path)
    parser.add_argument('--slice-root', type=Path)
    options = parser.parse_args(arguments)
    if options.isolated_root:
        root = options.isolated_root.resolve(strict=True)
        if (root / 'ISOLATED_TRACKER_TEST').read_text() != 'offline-only\n':
            parser.error('An explicit offline test marker is required')
        watch = (options.slice_root or root / 'slices').resolve()
        if not watch.is_relative_to(root):
            parser.error('Isolated slice root must be inside the test root')
        ISOLATED_ROOT, SLICE_ROOT = root, watch
        STORE = Store(root / 'inventory', legacy_paths=())
        WEB_PORT = 0
    else:
        SLICE_ROOT = options.slice_root


def main():
    if sys.argv[1:] == ["--sender-demo"]:
        if getattr(sys, 'frozen', False):
            print("Sender demo is available only from the source checkout", file=sys.stderr)
            return 2
        import importlib
        return importlib.import_module("dev.sender_dashboard_demo").main()
    if sys.argv[1:] == ["--self-test"]:
        # Package smoke test: no data directory, printer, GUI or network access.
        from importlib.util import find_spec
        from forecast import ForecastState
        state = ForecastState()
        state.accept([{'source': 'self/Metadata/.1.0.gcode', 'weights': [3, 0, 0, 0]}])
        required = ('pystray', 'webview', 'PIL', 'forecast_service', 'slice_observer')
        return 0 if (all(find_spec(name) is not None for name in required)
                     and len(state.snapshot()['entries']) == 1
                     and physical_weights([10, 20, 30, 40], [1, 1, 3, 0]) == [40, 30, 0, 30]) else 1
    if any(arg.startswith('--') for arg in sys.argv[1:]):
        configure_runtime(sys.argv[1:])
        configure_logging()
        return TrayApp().run()
    configure_logging()
    LOGGER.info("Starting Snapmaker Spool Tracker %s", APP_VERSION)
    if len(sys.argv) > 1:
        return handle_slicer_hook(sys.argv[1])
    return TrayApp().run()


if __name__ == "__main__":
    sys.exit(main())
