"""Offline names for observed codes; never changes chip identity, colour or mass."""
import re
from tracker_tigertag_registry import MATERIALS, BRANDS, REVISION


def resolve_names(tag, config):
    code=tag['material_id']
    material=tag['material'] or config.get('material_names',{}).get(code)
    manufacturer=config.get('manufacturer_names',{}).get(code,tag['manufacturer'])
    sources={}
    if tag['format']=='tigertag':
        match=re.fullmatch(r'tigertag:([0-9A-F]{4}):([0-9A-F]{4}):([0-9A-F]{8})',code)
        if not match:raise ValueError('Invalid TigerTag registry codes')
        brand_id,material_id,_=(int(v,16) for v in match.groups())
        if not material and material_id != 0xFFFF and material_id in MATERIALS:
            material=MATERIALS[material_id];sources['material']='TigerTag CC0 '+REVISION
        if manufacturer=='TigerTag' and code not in config.get('manufacturer_names',{}) and brand_id != 0xFFFF and brand_id in BRANDS:
            manufacturer=BRANDS[brand_id];sources['manufacturer']='TigerTag CC0 '+REVISION
    return dict(material=material,manufacturer=manufacturer,lookup_sources=sources)
