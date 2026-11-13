"""Prepare a macOS-only, no-hardware full-process UID bench from local clones."""
from pathlib import Path
import sys, subprocess, json, shutil
ROOT = Path('/private/tmp/tracker-uid-live')
REPO = Path(__file__).resolve().parents[3]

def prepare():
    if (ROOT/'printer_data/config/printer.cfg').exists() or (ROOT/'.klipper-running').exists():
        raise RuntimeError('Existing bench configuration; refusing to overwrite. Reuse run.py.')
    inc=ROOT/'compat'; (inc/'sys').mkdir(parents=True,exist_ok=True); (inc/'linux').mkdir(exist_ok=True)
    (inc/'sys/prctl.h').write_text('#include <pthread.h>\n#define PR_SET_NAME 15\nstatic int prctl(int op, const char *name) { return pthread_setname_np(name); }\n')
    (inc/'linux/can.h').write_text('#include <stdint.h>\nstruct can_frame { uint32_t can_id; uint8_t can_dlc; uint8_t pad[3]; uint8_t data[8] __attribute__((aligned(8))); };\n')
    sys.path.insert(0,str(ROOT/'klipper/klippy'))
    import chelper
    sources=[str(ROOT/'klipper/klippy/chelper'/f) for f in chelper.SOURCE_FILES]
    subprocess.run(['clang','-Wno-unknown-attributes','-O2','-shared','-fPIC','-I'+str(inc),'-o',str(ROOT/'klipper/klippy/chelper/c_helper.so'),*sources],check=True)
    data=ROOT/'printer_data'
    for name in ('config','logs','comms','gcodes'): (data/name).mkdir(parents=True,exist_ok=True)
    (ROOT/'.tracker-uid-simulator.json').write_text(json.dumps({'kind':'tracker-uid-filesystem-simulator','version':1}))
    (data/'config/printer.cfg').write_text('[mcu]\nserial: /no-hardware/uid-bench\n[printer]\nkinematics: none\nmax_velocity: 100\nmax_accel: 1000\n[virtual_sdcard]\npath: '+str(data/'gcodes')+'\n[pause_resume]\n[display_status]\n[bench_radio]\n')
    (data/'config/moonraker.conf').write_text('[server]\nhost: 127.0.0.1\nport: 18726\nklippy_uds_address: '+str(data/'comms/klippy.sock')+'\n[file_manager]\nfile_system_observer: none\n[machine]\nprovider: none\n[authorization]\ntrusted_clients:\n  127.0.0.1\n[announcements]\ndev_mode: True\n')
    commands=['emergency_stop','get_config','allocate_oids count=%c','finalize_config crc=%u','get_clock']
    (ROOT/'mcu.dict').write_text(json.dumps({'commands':{c:i+2 for i,c in enumerate(commands)},'responses':{'config is_config=%c crc=%u is_shutdown=%c move_count=%hu':10,'clock clock=%u':11},'config':{'CLOCK_FREQ':1000000,'STATS_SUMSQ_BASE':256,'MCU':'uid-bench'},'version':'synthetic-no-hardware'}))
    src=REPO/'dev/labs/uid_windows_live_bench/fm175xx_reader.py'
    shutil.copy2(src,ROOT/'klipper/klippy/extras/fm175xx_reader.py')
    shutil.copy2(Path(__file__).with_name('bench_radio.py'),ROOT/'klipper/klippy/extras/bench_radio.py')
    print('Prepared isolated bench', ROOT)
if __name__=='__main__':prepare()
