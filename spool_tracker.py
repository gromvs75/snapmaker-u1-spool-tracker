#!/usr/bin/env python3
"""
Snapmaker U1 Spool Tracker
Multi-language support (EN, RU, DE, UK, ES) + Native macOS Dialogs
"""

import sys
import os
import json
import subprocess
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pystray
from PIL import Image, ImageDraw

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "spools_u1.json")
WEB_PORT = 8765

DEFAULT_DB = {
    "language": "en",
    "slots": {
        "1": "spool_001",
        "2": "spool_002",
        "3": "spool_003",
        "4": "spool_004"
    },
    "spools": {
        "spool_001": {"name": "Snapmaker PLA Black", "material": "PLA", "remaining_g": 850.0},
        "spool_002": {"name": "Snapmaker PLA White", "material": "PLA", "remaining_g": 620.0},
        "spool_003": {"name": "eSUN PETG Red", "material": "PETG", "remaining_g": 1000.0},
        "spool_004": {"name": "Snapmaker Support PVA", "material": "PVA", "remaining_g": 350.0}
    }
}

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
        "btn_proceed": "Продолжить печать",
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
        "btn_proceed": "Продовжити друк",
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

def load_db():
    if not os.path.exists(DB_FILE):
        save_db(DEFAULT_DB)
        return DEFAULT_DB
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "language" not in data:
                data["language"] = "en"
            return data
    except Exception:
        return DEFAULT_DB

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def parse_u1_gcode(filepath):
    weights = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for line in reversed(lines):
        clean = line.strip().lower()
        if "filament used [g]" in clean and "=" in line:
            raw_val = line.split("=", 1)[1].strip()
            try:
                weights = [float(x.strip()) for x in raw_val.split(",") if x.strip()]
            except ValueError:
                pass
            if weights:
                break

    while len(weights) < 4:
        weights.append(0.0)

    return weights[:4]

def ask_native_macos_alert(deficit_details, lang="en"):
    tr = I18N.get(lang, I18N["en"])
    details_str = "\\n".join(deficit_details)
    prompt_text = (
        f"{tr['dialog_warn']}\\n\\n"
        f"{tr['dialog_desc']}\\n"
        f"{details_str}\\n\\n"
        f"{tr['dialog_cooling']}"
    )
    
    script = f'''
    display dialog "{prompt_text}" ¬
    with title "{tr['dialog_title']}" ¬
    buttons {{"{tr['btn_cancel']}", "{tr['btn_proceed']}"}} ¬
    default button "{tr['btn_cancel']}" ¬
    with icon caution
    '''
    try:
        res = subprocess.check_output(["osascript", "-e", script], text=True)
        return tr["btn_proceed"] in res
    except subprocess.CalledProcessError:
        return False

def handle_slicer_hook(gcode_path):
    weights = parse_u1_gcode(gcode_path)
    total_required = sum(weights)
    if total_required <= 0:
        sys.exit(0)

    db = load_db()
    lang = db.get("language", "en")
    tr = I18N.get(lang, I18N["en"])
    slots = db.get("slots", {})
    spools = db.get("spools", {})

    deficits = []
    has_shortage = False

    for i in range(4):
        req_g = weights[i]
        if req_g <= 0:
            continue

        slot_num = str(i + 1)
        spool_id = slots.get(slot_num)
        spool = spools.get(spool_id)

        if not spool:
            deficits.append(tr["slot_unassigned"].format(slot=slot_num, req=req_g))
            has_shortage = True
            continue

        rem_g = spool.get("remaining_g", 0.0)
        if rem_g < req_g:
            has_shortage = True
            shortage = req_g - rem_g
            deficits.append(tr["slot_shortage"].format(
                slot=slot_num,
                name=spool["name"],
                rem=rem_g,
                req=req_g,
                short=shortage
            ))

    if has_shortage:
        proceed = ask_native_macos_alert(deficits, lang=lang)
        if not proceed:
            print("[Snapmaker U1] Export cancelled by user.")
            sys.exit(1)

    for i in range(4):
        slot_num = str(i + 1)
        spool_id = slots.get(slot_num)
        spool = spools.get(spool_id)
        if spool:
            new_val = max(0.0, spool["remaining_g"] - weights[i])
            spool["remaining_g"] = round(new_val, 2)

    save_db(db)
    sys.exit(0)

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
    <table>
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

    <h2 id="t-add-hdr" style="margin-top: 26px;">Add New Spool</h2>
    <form id="add-spool-form" class="form-inline">
      <input type="text" id="new-name" placeholder="Spool name" required>
      <input type="text" id="new-mat" placeholder="Material" style="max-width: 130px;" required>
      <input type="number" id="new-weight" placeholder="Grams" value="1000" style="max-width: 100px;" required>
      <button type="submit" id="t-add-btn">+ Add Spool</button>
    </form>
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

let currentLang = "en";

function applyTexts(lang) {
  const t = dict[lang] || dict["en"];
  document.getElementById("t-subtitle").innerText = t.subtitle;
  document.getElementById("t-slots-hdr").innerText = t.slotsHdr;
  document.getElementById("t-save-slots").innerText = t.saveSlots;
  document.getElementById("t-spools-hdr").innerText = t.spoolsHdr;
  document.getElementById("t-th-name").innerText = t.thName;
  document.getElementById("t-th-mat").innerText = t.thMat;
  document.getElementById("t-th-rem").innerText = t.thRem;
  document.getElementById("t-th-act").innerText = t.thAct;
  document.getElementById("t-add-hdr").innerText = t.addHdr;
  document.getElementById("new-name").placeholder = t.namePh;
  document.getElementById("new-mat").placeholder = t.matPh;
  document.getElementById("t-add-btn").innerText = t.addBtn;
}

async function changeLang(lang) {
  currentLang = lang;
  applyTexts(lang);
  await fetch('/api/lang', { method: 'POST', body: JSON.stringify({ language: lang }) });
  loadData();
}

async function loadData() {
  const res = await fetch('/api/data');
  const data = await res.json();
  currentLang = data.language || 'en';
  document.getElementById('lang-picker').value = currentLang;
  applyTexts(currentLang);
  const t = dict[currentLang] || dict['en'];

  const slotsDiv = document.getElementById('slots-container');
  slotsDiv.innerHTML = '';
  for (let i = 1; i <= 4; i++) {
    const curId = data.slots[i] || '';
    let options = `<option value="">${t.emptySlot}</option>`;
    for (const [id, s] of Object.entries(data.spools)) {
      options += `<option value="${id}" ${id === curId ? 'selected' : ''}>${s.name} (${s.remaining_g}g, ${s.material})</option>`;
    }
    slotsDiv.innerHTML += `
      <div class="slot-row">
        <span class="slot-badge">${t.slotLabel} ${i} (${t.toolheadPrefix}${i-1}):</span>
        <select name="slot_${i}">${options}</select>
      </div>
    `;
  }

  const table = document.getElementById('spools-table');
  table.innerHTML = '';
  for (const [id, s] of Object.entries(data.spools)) {
    table.innerHTML += `
      <tr>
        <td><code>${id}</code></td>
        <td><strong>${s.name}</strong></td>
        <td>${s.material}</td>
        <td><input type="number" value="${s.remaining_g}" onchange="updateWeight('${id}', this.value)" style="width: 80px;"> g</td>
        <td><button onclick="deleteSpool('${id}')" style="background: var(--danger); padding: 5px 10px; font-size: 12px;">${t.deleteBtn}</button></td>
      </tr>
    `;
  }
}

document.getElementById('slots-form').onsubmit = async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const slots = {};
  for (let i = 1; i <= 4; i++) slots[i] = formData.get('slot_' + i);
  await fetch('/api/slots', { method: 'POST', body: JSON.stringify(slots) });
  const t = dict[currentLang] || dict['en'];
  alert(t.savedAlert);
  loadData();
};

document.getElementById('add-spool-form').onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    name: document.getElementById('new-name').value,
    material: document.getElementById('new-mat').value,
    remaining_g: parseFloat(document.getElementById('new-weight').value) || 1000
  };
  await fetch('/api/spools/add', { method: 'POST', body: JSON.stringify(body) });
  e.target.reset();
  loadData();
};

async function updateWeight(id, val) {
  await fetch('/api/spools/update', { method: 'POST', body: JSON.stringify({ id, remaining_g: parseFloat(val) }) });
  loadData();
}

async function deleteSpool(id) {
  if (!confirm('Delete spool ' + id + '?')) return;
  await fetch('/api/spools/delete', { method: 'POST', body: JSON.stringify({ id }) });
  loadData();
}

loadData();
</script>
</body>
</html>
"""

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/data":
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(load_db()).encode("utf-8"))
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8'))
        db = load_db()

        if self.path == "/api/lang":
            db["language"] = body.get("language", "en")
        elif self.path == "/api/slots":
            db["slots"] = body
        elif self.path == "/api/spools/add":
            db["spools"][f"spool_{len(db['spools']) + 1:03d}"] = body
        elif self.path == "/api/spools/update":
            s_id = body.get("id")
            if s_id in db["spools"]:
                db["spools"][s_id]["remaining_g"] = body.get("remaining_g", 0.0)
        elif self.path == "/api/spools/delete":
            s_id = body.get("id")
            if s_id in db["spools"]:
                del db["spools"][s_id]

        save_db(db)
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

def start_web_server():
    server = HTTPServer(("127.0.0.1", WEB_PORT), WebHandler)
    server.serve_forever()

def create_tray_icon():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    colors = [(240, 80, 80), (80, 160, 240), (80, 210, 120), (250, 190, 50)]
    coords = [(6, 6, 26, 26), (36, 6, 56, 26), (6, 36, 26, 56), (36, 36, 56, 56)]
    for (box, color) in zip(coords, colors):
        dc.ellipse(box, fill=color)
    return image

class TrayApp:
    def __init__(self): self.icon = None
    def build_menu(self):
        db = load_db()
        lang = db.get("language", "en")
        tr = I18N.get(lang, I18N["en"])
        items = [pystray.MenuItem(tr["tray_title"], lambda: None, enabled=False), pystray.Menu.SEPARATOR]
        for i in range(1, 5):
            s_id = db.get("slots", {}).get(str(i))
            spool = db.get("spools", {}).get(s_id)
            if spool:
                items.append(pystray.MenuItem(tr["tray_slot"].format(slot=i, idx=i-1, name=spool['name'], rem=spool['remaining_g']), lambda: None, enabled=False))
            else:
                items.append(pystray.MenuItem(tr["tray_empty"].format(slot=i, idx=i-1), lambda: None, enabled=False))
        items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr["tray_open"], lambda: webbrowser.open(f"http://127.0.0.1:{WEB_PORT}")),
            pystray.MenuItem(tr["tray_quit"], lambda icon, item: os._exit(0))
        ])
        return pystray.Menu(*items)

    def run(self):
        threading.Thread(target=start_web_server, daemon=True).start()
        self.icon = pystray.Icon("SnapmakerU1Tracker", create_tray_icon(), "Snapmaker U1 Tracker", menu=self.build_menu())
        self.icon.run()

def main():
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(('.gcode', '.g', '.pp')):
        handle_slicer_hook(sys.argv[1])
    else:
        TrayApp().run()

if __name__ == "__main__":
    main()
