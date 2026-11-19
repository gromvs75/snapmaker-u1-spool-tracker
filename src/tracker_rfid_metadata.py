"""Untrusted reader payload validation. Tag data never supplies remaining mass."""
import math
import re


def validate_tag(value, uid):
    if not isinstance(value, dict):
        raise ValueError('Invalid RFID metadata')
    v = dict(value)
    if v.get('format') in EXTRA_FORMATS:
        return validate_extra_tag(v, uid)
    if v.get('format') in ('qidi', 'anycubic'):
        return validate_chip_tag(v, uid)
    if (type(v.get('schema')) is not int or v['schema'] != 1 or v.get('format') != 'bambu' or v.get('uid') != uid
            or not re.fullmatch(r'bambu:[0-9A-F]{32}', str(v.get('identity', '')))
            or int(v['identity'][6:], 16) in (0, 2**128-1)
            or v.get('manufacturer') != 'Bambu Lab'):
        raise ValueError('Invalid Bambu identity')
    for field in ('material', 'name', 'material_id', 'variant_id'):
        text = v.get(field)
        if not isinstance(text, str) or not 1 <= len(text) <= 32 or any(not 32 <= ord(c) <= 126 for c in text):
            raise ValueError('Invalid Bambu text')
    if not v['material_id'].startswith('GF'):
        raise ValueError('Invalid Bambu material ID')
    colors = v.get('colors')
    if (not isinstance(colors, list) or not 1 <= len(colors) <= 2
            or any(not isinstance(c, str) or not re.fullmatch('[0-9A-F]{6}', c) for c in colors)
            or v.get('color') != colors[0]):
        raise ValueError('Invalid Bambu colour')
    for field, low, high in (('diameter_mm', .5, 4), ('nominal_weight_g', 1, 10000),
                             ('nozzle_min_c', 100, 400), ('nozzle_max_c', 100, 400),
                             ('bed_c', 0, 200), ('alpha', 0, 255)):
        n = v.get(field)
        if type(n) not in (int, float) or not math.isfinite(n) or not low <= n <= high:
            raise ValueError('Invalid Bambu dimensions or temperature')
    if v['nozzle_min_c'] > v['nozzle_max_c']:
        raise ValueError('Invalid Bambu temperature range')
    allowed = {'schema', 'format', 'uid', 'identity', 'manufacturer', 'material', 'name',
               'material_id', 'variant_id', 'colors', 'color', 'alpha', 'diameter_mm',
               'nominal_weight_g', 'nozzle_min_c', 'nozzle_max_c', 'bed_c'}
    return {k: v[k] for k in allowed}


def product(tag):
    # Different chips on the same roll must agree on the material and colour.
    keys = ['material_id', 'variant_id', 'material', 'name', 'colors', 'diameter_mm', 'nominal_weight_g']
    if tag['format'] == 'bambu':keys.insert(0, 'identity')
    else:keys += ['format', 'manufacturer']
    return {k: tag[k] for k in keys}


def roll_key(tag):
    """Only documented physical-instance IDs qualify, never product/batch IDs."""
    if tag.get('format') == 'bambu':
        return tag['identity']
    if tag.get('format') == 'openprinttag' and tag.get('instance_uuid'):
        return 'openprinttag:instance:' + tag['instance_uuid']
    return None


def validate_chip_tag(v, uid):
    kind = v['format']
    size = 8 if kind == 'qidi' else 14
    if (type(v.get('schema')) is not int or v['schema'] != 1 or not isinstance(uid,str)
            or not re.fullmatch('[0-9A-F]{%d}' % size, uid) or v.get('uid') != uid
            or v.get('identity') != kind+':chip:'+uid):
        raise ValueError('Invalid chip-scoped RFID identity')
    base = {'schema','format','uid','identity','manufacturer','material','name','material_id','variant_id',
            'color','colors','alpha','diameter_mm','nominal_weight_g','nozzle_min_c','nozzle_max_c','bed_c'}
    if kind == 'qidi':
        for key in ('material_code','color_code','manufacturer_code'):
            if type(v.get(key)) is not int or not 1 <= v[key] <= 255:
                raise ValueError('Invalid QIDI code')
        material = {2:'PLA',0x29:'PETG'}.get(v['material_code'])
        color = {1:'FFFFFF',0x0B:'1714B0',0x12:'FF362D',0x14:'898F9B'}.get(v['color_code'])
        if (v.get('material') != material or v.get('color') != color
                or v.get('manufacturer') != ('QIDI' if v['manufacturer_code']==1 else 'QIDI-compatible')
                or v.get('material_id') != 'qidi:%02X' % v['material_code']
                or v.get('variant_id') != '%02X:%02X' % (v['color_code'],v['manufacturer_code'])
                or v.get('colors') != ([color] if color else []) or v.get('alpha') != 255
                or any(v.get(k) is not None for k in ('diameter_mm','nominal_weight_g','nozzle_min_c','nozzle_max_c','bed_c'))):
            raise ValueError('QIDI metadata disagrees with read codes')
        base |= {'material_code','color_code','manufacturer_code'}
    else:
        if (v.get('manufacturer') != 'Anycubic' or type(v.get('layout_version')) is not int
                or v['layout_version'] not in (0x64,0x65) or not isinstance(v.get('sku'),str)
                or not re.fullmatch('[A-Za-z0-9+_-]{1,11}',v['sku'])
                or v.get('material_id') != 'anycubic:'+v['sku'] or v.get('variant_id') != v['sku']):
            raise ValueError('Invalid Anycubic product fields')
        if not isinstance(v.get('color'),str) or not re.fullmatch('[0-9A-F]{6}',v['color']) or v.get('colors') != [v['color']]:
            raise ValueError('Invalid Anycubic color')
        for key,low,high in (('diameter_mm',.5,4),('nominal_weight_g',1,10000),('nozzle_min_c',100,400),
                             ('nozzle_max_c',100,400),('bed_c',0,200),('bed_min_c',0,200),
                             ('length_m',0,10000),('print_speed_min',0,2000),('print_speed_max',0,2000),('alpha',0,255)):
            n=v.get(key)
            if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:
                raise ValueError('Invalid Anycubic numeric field')
        if v['nozzle_min_c']>v['nozzle_max_c'] or v['bed_min_c']>v['bed_c'] or v['print_speed_min']>v['print_speed_max']:
            raise ValueError('Invalid Anycubic ranges')
        if not isinstance(v.get('brand_code'),str) or len(v['brand_code'])>16:
            raise ValueError('Invalid Anycubic brand code')
        base |= {'sku','brand_code','bed_min_c','length_m','print_speed_min','print_speed_max','layout_version'}
    for field in ('name','material_id','variant_id','manufacturer','material'):
        value=v.get(field)
        if field=='material' and value is None and kind=='qidi':continue
        if not isinstance(value,str) or not 1<=len(value)<=64 or any(not 32<=ord(c)<=126 for c in value):
            raise ValueError('Invalid RFID text')
    return {k:v[k] for k in base}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - {'enabled', 'allow_create', 'send_usage', 'new_spools', 'initial_balances', 'densities', 'diameters', 'nominal_weights', 'confirmed_new_tags', 'material_names', 'manufacturer_names', 'approvals'}:
        raise ValueError('Invalid RFID settings')
    approvals=value.get('approvals',{})
    if not isinstance(approvals,dict) or len(approvals)>10000:raise ValueError('Invalid RFID approvals')
    for identity,approval in approvals.items():
        if not isinstance(identity,str) or len(identity)>64 or not isinstance(approval,dict) or set(approval)-{'product','remaining_g','density','diameter','nominal','catalog'} or not {'product','remaining_g','density','diameter','nominal'}<=set(approval):
            raise ValueError('Invalid RFID approval')
        if 'catalog' in approval:
            c=approval['catalog']
            if (not isinstance(c,dict) or set(c)!={'source','revision','product_id','confirmed_fields','match'}
                    or c['source']!='SpoolmanDB' or c['match']!='suggested-by-properties'
                    or not isinstance(c['revision'],str) or not re.fullmatch('[a-f0-9]{64}',c['revision'])
                    or not isinstance(c['product_id'],str) or not 0<len(c['product_id'])<=300
                    or not isinstance(c['confirmed_fields'],list) or any(v not in ('density','diameter','nominal') for v in c['confirmed_fields'])):
                raise ValueError('Invalid RFID catalog provenance')
        if not isinstance(approval['product'],dict):raise ValueError('Invalid approved RFID product')
        for key,low,high in (('remaining_g',0,100000),('density',.1,5),('diameter',.5,4),('nominal',1,10000)):
            n=approval[key]
            if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:raise ValueError('Invalid approved RFID value')
    for key in ('enabled', 'allow_create', 'send_usage'):
        if key in value and type(value[key]) is not bool:
            raise ValueError('Invalid RFID switch')
    if value.get('new_spools', 'hold') not in ('hold', 'nominal'):
        raise ValueError('Invalid initial balance policy')
    confirmed = value.get('confirmed_new_tags', [])
    if (not isinstance(confirmed,list) or len(confirmed)>10000 or any(not isinstance(v,str) or not
            re.fullmatch(r'(?:(?:qidi|creality):chip:[0-9A-F]{8}|(?:anycubic|elegoo|tigertag|generic-ndef|opentag|openprinttag):chip:[0-9A-F]{14})',v) for v in confirmed)):
        raise ValueError('Invalid confirmed new RFID tags')
    for key in ('material_names','manufacturer_names'):
        items=value.get(key,{})
        if not isinstance(items,dict) or len(items)>10000:raise ValueError('Invalid RFID name mapping')
        for code,name in items.items():
            if any(not isinstance(t,str) or not 1<=len(t)<=64 or any(not 32<=ord(c)<=126 for c in t) for t in (code,name)):
                raise ValueError('Invalid RFID mapped name')
    for key, maximum in (('initial_balances', 100000), ('densities', 5), ('diameters',4), ('nominal_weights',10000)):
        items = value.get(key, {})
        if not isinstance(items, dict) or len(items) > 10000:
            raise ValueError('Invalid RFID mapping')
        for name, number in items.items():
            if (not isinstance(name, str) or not 1 <= len(name) <= 64
                    or type(number) not in (int, float) or not math.isfinite(number)
                    or not 0 <= number <= maximum or (key == 'densities' and number < .1)):
                raise ValueError('Invalid RFID mapping value')
            if (key=='diameters' and number<.5) or (key=='nominal_weights' and number<1):
                raise ValueError('Invalid RFID material property')
    return value


EXTRA_FORMATS = ('creality','elegoo','tigertag','generic-ndef','opentag','openprinttag')


def validate_extra_tag(v, uid):
    kind=v['format'];size=8 if kind=='creality' else 14
    if (type(v.get('schema')) is not int or v['schema']!=1 or not isinstance(uid,str)
            or not re.fullmatch('[0-9A-F]{%d}' % size,uid) or v.get('uid')!=uid
            or v.get('identity')!=kind+':chip:'+uid):
        raise ValueError('Invalid RFID chip identity')
    keys={'schema','format','uid','identity','manufacturer','material','name','material_id','variant_id',
          'color','colors','alpha','diameter_mm','nominal_weight_g','nozzle_min_c','nozzle_max_c','bed_c'}
    if kind == 'openprinttag' and 'instance_uuid' in v:
        instance = v['instance_uuid']
        if (not isinstance(instance, str) or not re.fullmatch('[0-9A-F]{32}', instance)
                or int(instance, 16) in (0, 2**128-1)):
            raise ValueError('Invalid OpenPrintTag instance UUID')
        keys.add('instance_uuid')
    if kind=='tigertag':
        keys|={'twin_id','tag_index','tag_count'}
        for key,maximum in (('twin_id',2**32-1),('tag_index',15),('tag_count',15)):
            if type(v.get(key)) is not int or not 0<=v[key]<=maximum:raise ValueError('Invalid TigerTag pairing hint')
        if v['tag_count'] and v['tag_index']>v['tag_count']:raise ValueError('Invalid TigerTag tag count')
    if not keys<=v.keys():raise ValueError('Incomplete RFID metadata')
    for key in ('manufacturer','material','name','material_id','variant_id'):
        value=v[key]
        if key=='material' and value is None:continue
        if not isinstance(value,str) or not 1<=len(value)<=64 or any(not 32<=ord(c)<=126 for c in value):
            raise ValueError('Invalid RFID text')
    if not v['material_id'].startswith(kind+':'):raise ValueError('Invalid RFID product namespace')
    maker={'creality':'Creality','elegoo':'Elegoo','tigertag':'TigerTag'}.get(kind)
    if maker and v['manufacturer']!=maker:raise ValueError('Invalid RFID manufacturer')
    colors=v['colors']
    if (not isinstance(colors,list) or len(colors)>5 or any(not isinstance(c,str) or not re.fullmatch('[0-9A-F]{6}',c) for c in colors)
            or v['color']!=(colors[0] if colors else None)):
        raise ValueError('Invalid RFID colors')
    for key,low,high in (('diameter_mm',.5,4),('nominal_weight_g',1,10000),('nozzle_min_c',100,400),
                         ('nozzle_max_c',100,400),('bed_c',0,200),('alpha',0,255)):
        n=v[key]
        if n is None and key!='alpha':continue
        if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:raise ValueError('Invalid RFID numeric field')
    if v['nozzle_min_c'] is not None and v['nozzle_max_c'] is not None and v['nozzle_min_c']>v['nozzle_max_c']:
        raise ValueError('Invalid RFID temperature range')
    return {key:v[key] for key in keys}
