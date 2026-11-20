"""Published 1.3.3 tray artwork, fed by the 2.0 read-only forecast model.

Artwork helpers ported from fdeb1aa; never import legacy spool_tracker/Store.
"""
import logging
from datetime import datetime
LOGGER = logging.getLogger('tracker20')


def grams(value, digits=1):
    return f'{value:.{digits}f}'.replace('.',',')+' г'


def tray_model(snapshot):
    printer=snapshot.get('printers',{}).get(snapshot.get('selected_printer'),{})
    entry=next((e for e in printer.get('entries',snapshot.get('entries',[])) if e['source']==snapshot.get('latest')),None)
    materials = entry['materials'] if entry and not snapshot.get('error') else []
    label = 'Ожидаем нарезку Snorca'
    mapping = ''
    status = entry['status'] if materials else 'unknown'
    if materials:
        estimate = {'ok': '✓ По прогнозу хватает', 'shortage': '✕ По прогнозу не хватает',
                    'unknown': 'Нужно сверить головки или остатки'}[status]
        label = estimate + ' · Расход ' + grams(sum(m['grams'] for m in materials), 2)
        mapping = ('Уточните головки в окне подготовки Orca' if entry['requires_mapping']
                   else 'Прогноз по цвету и типу · Сверьте с Orca')
    if entry:
        if not materials:label='Нет данных о расходе материала'
        label+=' · '+('Стол '+str(entry['plate']) if entry.get('plate') else 'Стол не определён')+' · '+datetime.fromtimestamp(entry['completed_at_ns']/1e9).strftime('%d.%m %H:%M')
    rows = {row['channel']: row for row in entry['rows']} if materials else {}
    heads=[]
    for i in range(4):
        head=printer.get('heads',[{}]*4)[i];spool=head.get('spool')
        title=f'T{i} · '+(spool['name']+' — '+grams(spool['remaining_mg']/1000) if spool else 'Не назначена')
        row = rows.get(str(i))
        if row:
            title += ' · Нужно ' + grams(row['used'], 2)
            if row['unknown']:
                title += ' · Сверьте остаток'
            elif row['enough']:
                title += ' · После ≈ ' + grams(row['after'], 2)
            else:
                title += ' · Не хватает с резервом ' + grams(row['deficit'], 2)
        heads.append(dict(title=title, color=(spool.get('details', {}).get('color') or None) if spool else None,
                          status=row['status'] if row else None))
    return dict(title=(printer.get('name') or 'Snapmaker U1')+' (4 головки)',status=status,
                forecast=label,mapping=mapping,materials=materials,heads=heads,
                event=(entry['source'],entry['completed_at_ns'],entry.get('sha256')) if entry else None)


def build_menu(model, show, forecast, quit):
    import pystray
    items=[pystray.MenuItem(model['title'],show),pystray.Menu.SEPARATOR,
           pystray.MenuItem(model['forecast'],forecast)]
    for material in model['materials']:
        item = pystray.MenuItem(f"Материал {material['number']} · {grams(material['grams'], 2)}", forecast)
        item._tracker_material_color = material['color']
        items.append(item)
    if model['mapping']:
        items.append(pystray.MenuItem(model['mapping'],forecast))
    items.append(pystray.Menu.SEPARATOR)
    for head in model['heads']:
        item=pystray.MenuItem(head['title'],forecast)
        item._tracker_toolhead=True;item._tracker_color=head['color'];item._tracker_status=head['status']
        items.append(item)
    items.extend([pystray.Menu.SEPARATOR,pystray.MenuItem('Открыть Tracker',show,default=True),
                  pystray.MenuItem('Настроить катушки и слоты…',show),pystray.MenuItem('Выход',quit)])
    return pystray.Menu(*items)

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
    return png_bytes(image)


def create_material_menu_icon(color):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (32, 32))
    ImageDraw.Draw(image).ellipse((3, 3, 29, 29), fill=color, outline='#a4abb7', width=2)
    return png_bytes(image)


def png_bytes(image):
    from io import BytesIO
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
        toolhead = getattr(descriptor, '_tracker_toolhead', False)
        material_color = getattr(descriptor, '_tracker_material_color', None)
        if toolhead or material_color:
            try:
                if toolhead:
                    payload = create_toolhead_menu_icon(getattr(descriptor, '_tracker_color', None), getattr(descriptor, '_tracker_status', None))
                    size = (18, 22)
                else:
                    payload = create_material_menu_icon(material_color)
                    size = (16, 16)
                data = Foundation.NSData.dataWithBytes_length_(payload, len(payload))
                picture = AppKit.NSImage.alloc().initWithData_(data)
                picture.setSize_(size)
                picture.setTemplate_(False)
                item.setImage_(picture)
            except Exception:
                LOGGER.exception('Could not render forecast menu icon')
        return item
    icon._create_menu_item = create_item
