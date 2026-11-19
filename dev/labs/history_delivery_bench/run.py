"""Ordinary history UI -> real Spoolman 0.27.1, fresh databases, loopback only."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from dev.labs.uid_live_bench.bambu_run import spoolman
from tracker_uid_spoolman import Client
from tracker_uid_session import Session
from tracker_uid_sender import Sender
from tracker_uid_gui import serve
from storage import Store
from backup import create_backup
from spoolman_bridge import blank,remote_id
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser()
    for name in ('spoolman','spoolman-python','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    for k,v in vars(args).items():setattr(args,k,v.absolute())
    args.output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='history-delivery-') as temp:
        root=Path(temp)
        with spoolman(args,root/'spoolman') as url:
            client=Client(url);filament,_=client.request('POST','/filament',dict(name='Synthetic review PLA',material='PLA',density=1.24,diameter=1.75,weight=1000,color_hex='ff7f26'))
            row,_=client.request('POST','/spool',dict(filament_id=filament['id'],initial_weight=1000,remaining_weight=500));sid=remote_id(url,row['id'])
            store=Store(root/'old')
            def seed(d):
                d['language']='ru';d['spoolman']=dict(blank(),url=url,mode='send',epoch='synthetic')
                d['spools']={sid:dict(name='Review PLA',material='PLA',remaining_g=500,spoolman=dict(url=url,id=row['id']))};d['slots']['1']=sid
                d['plans']['p']=dict(filename='review-bench.gcode',sha256='a'*64,size=100,weights=[12,0,0,0],spool_ids=[sid,'','',''],created_at=1000,status='review',printer=dict(d['printer']))
                d['runs']['r']=dict(job_id='r',plan_id='p',filename='review-bench.gcode',start_time=2000,status='review',physical_weights=[12,0,0,0],physical_spool_ids=[sid,'','',''],tool_mapping=[0,1,2,3])
            store.update(seed);app=Session(root/'profile',allowed_urls=[url]);package=create_backup(store,'1.3.3');review=app.call('validate_backup',package=package)
            app.call('restore_backup',package=package,expected_revision=review['current_revision'],confirmed=True)
            app.call('save_settings',values=dict(spoolman_mode='send'),expected_revision=app.call('settings')['revision'])
            sender=Sender(app,[url]);server=serve(app,app.fleet,sender=sender);thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1202,'height':950});page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
                    page.locator('#uid-history-dialog[open]').wait_for();page.locator('#uid-history-edit').click();expect(page.locator('.uid-extra-amount')).to_have_value('12')
                    page.locator('.uid-extra-amount').fill('3.5');page.locator('#uid-review-ack').check();page.locator('#uid-review-apply').click()
                    expect(page.locator('#uid-history-send')).to_be_visible();before,_=client.request('GET','/spool/'+str(row['id']));assert before['remaining_weight']==500
                    operation=app.call('delivery_list')[0];page.screenshot(path=str(args.output/'before-send.png'));page.locator('#uid-history-send').click()
                    expect(page.locator('#uid-history-dialog')).to_contain_text('Готово: Tracker и Spoolman');page.screenshot(path=str(args.output/'sent.png'))
                    after,_=client.request('GET','/spool/'+str(row['id']));assert after['remaining_weight']==496.5
                    for _ in range(3):assert sender.confirm_send(operation['operation_id'],operation['revision'],'repeat-after-success',confirmed=True)['status']=='sent'
                    again,_=client.request('GET','/spool/'+str(row['id']));assert again['remaining_weight']==496.5
                    inspect=app.call('inspect');assert len(inspect['debits'])==1 and inspect['debits'][0]['delta_mg']==3500
                    assert app.call('library_snapshot')['spools'][0]['remaining_mg']==496500
                    result=dict(success=True,spoolman_version='0.27.1',real_printer_used=False,windows_gui_verified=False,
                        planned_g=12,edited_g=3.5,comment='',remote_before_g=500,remote_after_g=496.5,
                        local_debits=1,delivery_states=[a['state'] for a in app.call('delivery_audit')],repeated_confirmations=3)
                    (args.output/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));browser.close()
            finally:server.shutdown();server.server_close();thread.join();app.close()

if __name__=='__main__':main()
