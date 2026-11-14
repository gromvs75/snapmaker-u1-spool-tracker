"""Read-only layer ranges from explicit G-code extrusion, never a debit source.

Ranges describe planned command extrusion. Firmware macros, purge and skipped
objects can differ. Unsupported extrusion modes fail closed.
"""
import math
import re


def layer_estimates(handle):
    handle.seek(0)
    relative=False;absolute_coords=True;position=0.;head=0;totals=[0.]*4;layers={};current=None
    def snapshot():return [max(0.,v) for v in totals]
    for raw in handle:
        line=raw.decode('utf-8',errors='strict').strip()
        match=re.search(r'\bSET_PRINT_STATS_INFO\s+.*?CURRENT_LAYER=(\d+)\b',line.split(';',1)[0])
        if match:
            number=int(match[1])
            if number in layers or (current is not None and number<=current):
                raise ValueError('Layer sequence is ambiguous')
            current=number;layers[number]={'low_mm':snapshot(),'high_mm':snapshot()}
        command=line.split(';',1)[0].strip().upper()
        if not command:continue
        op=command.split()[0]
        if re.match(r'^(?:G0?[0123]|G92|M82|M83|T\d+)[A-Z]',op):
            raise ValueError('Compact commands require a verified parser')
        for token in command.split()[1:]:
            if token.startswith('E') and not re.fullmatch(r'E[-+]?(?:\d+(?:\.\d*)?|\.\d+)',token):
                raise ValueError('Unsupported extrusion number')
        fields={k:float(v) for k,v in re.findall(r'([XYZEFST])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))',command[len(op):])}
        if any(not math.isfinite(v) for v in fields.values()):raise ValueError('Invalid G-code number')
        if op=='G90':absolute_coords=True
        elif op=='G91':absolute_coords=False
        elif op=='M82':relative=False
        elif op=='M83':relative=True
        elif op=='G92' and 'E' in fields:position=fields['E']
        elif re.fullmatch(r'T\d+',op):
            head=int(op[1:])
            if head not in range(4):raise ValueError('Unsupported tool')
        elif op in ('G20','M200','M221','G10','G11'):
            raise ValueError('Unsupported extrusion units, scaling or firmware retract')
        elif op in ('G0','G1','G2','G3') and 'E' in fields:
            value=fields['E'];is_relative=relative or not absolute_coords
            delta=value if is_relative else value-position
            position=position+value if is_relative else value
            totals[head]+=delta
            if current is not None:
                r=layers[current]
                r['low_mm']=[min(a,b) for a,b in zip(r['low_mm'],snapshot())]
                r['high_mm']=[max(a,b) for a,b in zip(r['high_mm'],snapshot())]
    return {str(k):v for k,v in layers.items()}
