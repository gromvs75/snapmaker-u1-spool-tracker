"""Exercise the embedded live-update JavaScript with a minimal DOM fixture."""

import json
import shutil
import subprocess

import pytest

from spool_tracker import HTML_PAGE


def test_live_render_preserves_edits_and_updates_print_state():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    source = HTML_PAGE.split("<script>", 1)[1].split("</script>", 1)[0]
    helpers = source[source.index("function updateMonitor"):source.index("async function changeLang")]
    harness = r"""
const assert = require('assert');
const vm = require('vm');
function element() {
  return { textContent: '', children: [], replacements: 0,
    replaceChildren() { this.children = []; this.replacements++; },
    append(child) { this.children.push(child); } };
}
const nodes = {
  'printer-status': element(), 'preflight-content': element(), 'guard-content': element(),
  'accounting-status': element(), 'spools-table': element(),
  'slots-container': element()
};
const input = {value: '1000', dataset: {}};
const row = {dataset: {spoolId: 's'}, querySelector: () => input};
const option = {value: 's', textContent: 'Black (1000g, PLA)'};
const select = {options: [option]};
nodes['spools-table'].rows = [row];
nodes['slots-container'].querySelectorAll = () => [select];
const document = {activeElement: input};
const context = vm.createContext({
  console, document, JSON, Object, String,
  currentLang: 'en', extra: {en: {connected: 'Connected', disconnected: 'Disconnected', none: 'None'}},
  gramUnit: () => 'g',
  guardText: {en: {paused: 'Tracker paused this print.', recentPlan: 'Previous plan', job: 'Printer job'}},
  el: id => nodes[id],
  node: (tag, value) => ({tag, textContent: value, style: {}, children: [],
    append(child) {this.children.push(child);}, addEventListener() {}})
});
vm.runInContext(HELPERS, context);
const data = {
  monitor: {connected: true, state: 'printing', filename: 'job.gcode', error: ''},
  last_preflight: {time: '10:00', summary: 'OK', rows: []},
  last_guard: null,
  plans: {p: {created_at: 1, filename: 'job.gcode', status: 'active'}},
  runs: {r: {plan_id: 'p', start_time: 2, status: 'active'}},
  spools: {s: {name: 'Black', material: 'PLA', remaining_g: 900}}
};
context.updateLiveState(data);
assert.equal(input.value, '1000'); // Focused edit is untouched.
assert.equal(option.textContent, 'Black (900 g, PLA)');
assert.match(nodes['accounting-status'].textContent, /active/);
assert.match(nodes['printer-status'].textContent, /printing/);
assert.equal(nodes['preflight-content'].replacements, 1);
document.activeElement = null;
input.dataset.dirty = '1';
context.updateLiveState(data);
assert.equal(input.value, '1000'); // Blurred but unsaved edit is untouched.
assert.equal(nodes['preflight-content'].replacements, 1); // No flicker for unchanged preflight.
delete input.dataset.dirty;
data.spools.s.remaining_g = 890;
data.plans.p.status = 'committed';
data.runs.r.status = 'committed';
data.last_preflight = {time: '10:01', summary: 'New preflight', rows: []};
context.updateLiveState(data);
assert.equal(input.value, '890');
assert.match(nodes['accounting-status'].textContent, /committed/);
assert.equal(nodes['preflight-content'].replacements, 2);
data.last_guard = {job_key: 'job1', filename: 'job.gcode', state: 'paused', reason: ''};
data.monitor.state = 'paused';
context.updateLiveState(data);
assert.equal(nodes['guard-content'].children.length, 2);
assert.equal(nodes['guard-content'].children[1].children.length, 2);
data.monitor.state = 'printing';
context.updateLiveState(data);
assert.equal(nodes['guard-content'].children.length, 1); // No stale action buttons.
"""
    program = harness.replace("HELPERS", json.dumps(helpers))
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_unaccounted_prints_show_completed_and_cancelled_without_manual_form():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    source = HTML_PAGE.split("<script>", 1)[1].split("</script>", 1)[0]
    code = source[source.index("let reviewSignature"):source.index("let historySignature")]
    harness = r"""
const assert = require('assert');
const vm = require('vm');
function item(tag, text) { return {tag, textContent: text, children: [],
  append(child) {this.children.push(child);}, replaceChildren() {this.children=[];} }; }
const root = item('div');
const ctx = vm.createContext({JSON, Object, Date, currentLang: 'ru',
  el: () => root, node: (tag, value) => item(tag, value)});
vm.runInContext(SOURCE, ctx);
ctx.renderReviews({runs: {a: {status:'review', terminal_status:'completed', start_time:1, filename:'x.gcode'},
  b: {status:'review', start_time:2, filename:'unfinished.gcode'},
  c: {status:'committed', terminal_status:'completed', start_time:3, filename:'accounted.gcode'},
  d: {status:'cancelled', terminal_status:'cancelled', start_time:4, filename:'cancelled.gcode'},
  e: {status:'committed', terminal_status:'cancelled', start_time:5, filename:'accounted-cancel.gcode'}}});
assert.equal(root.children.length, 4);
assert.match(root.children[1].textContent, /Остатки катушек не изменены/);
assert.match(root.children[2].textContent, /cancelled\.gcode.*отменена/);
assert.match(root.children[3].textContent, /x\.gcode/);
assert.ok(root.children.every(child => child.tag !== 'form'));
"""
    result = subprocess.run([node, "-e", harness.replace("SOURCE", json.dumps(code))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_accounted_print_is_visible_separately_from_manual_review():
    node_path = shutil.which('node')
    if not node_path:
        pytest.skip('Node.js is unavailable')
    source = HTML_PAGE.split('<script>', 1)[1].split('</script>', 1)[0]
    code = source[source.index('let historySignature'):source.index('function updateLiveState')]
    harness = r'''
const assert = require('assert');
const vm = require('vm');
function item(tag, text) { return {tag, textContent:text, children:[], open:false,
  append(child){this.children.push(child)}, replaceChildren(){this.children=[]},
  querySelector(){return null}}; }
const nodes = {'history-content':item('div'), 'latest-accounting':item('div')};
const ctx = vm.createContext({JSON, Object, Number, Math, Date, currentLang:'ru',
  gramUnit:()=> 'гр.', el:id=>nodes[id], node:(tag, value)=>item(tag, value)});
vm.runInContext(SOURCE,ctx);
ctx.renderHistory({spools:{s:{name:'Black'}}, runs:{
  a:{status:'review', terminal_status:'completed', start_time:1, filename:'old.gcode'},
  b:{status:'committed', accounting_method:'motion_estimate', start_time:2,
     filename:'new.gcode', motion_consumption:{s:9.611}}}});
const text=nodes['latest-accounting'].children.map(c => c.textContent).join(' ');
assert.match(text, /new\.gcode/); assert.match(text, /Black: 9\.611 гр\./);
assert.doesNotMatch(text, /old\.gcode/);
'''
    result = subprocess.run([node_path, '-e', harness.replace('SOURCE', json.dumps(code))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sidebar_highlights_only_fresh_selected_printing_head():
    node_path = shutil.which('node')
    if not node_path:
        pytest.skip('Node.js is unavailable')
    source = HTML_PAGE.split('<script>', 1)[1].split('</script>', 1)[0]
    code = source[source.index('let sidebarSignature'):source.index('function renderOverview')]
    harness = r'''
const assert = require('assert');
const vm = require('vm');
function item(tag, text, cls) {return {tag, textContent:text, className:cls, children:[], style:{},
  append(...children) {this.children.push(...children)}, replaceChildren(){this.children=[]}, setAttribute(){}};}
const root = item('div');
const ctx = vm.createContext({JSON, Object, Number, Date, currentLang:'ru',
  gramUnit:()=> 'гр.', validColor:()=>false, colorDot:()=>item('span'), el:()=>root, node:(...args)=>item(...args)});
vm.runInContext(SOURCE,ctx);
const data = {slots:{1:'a'},spools:{a:{name:'Black',remaining_g:10,material:'PLA'}},
  monitor:{connected:true,state:'printing',active_head:0,checked_at:Date.now()/1000}};
data.monitor.filename = 'part.gcode'; data.monitor.active_job_key = 'job1';
data.last_guard = {job_key:'job1'};
data.last_preflight = {source:'print_start', job_key:'job1', filename:'part.gcode', rows:[{tool:'T0',spool_id:'a',required_g:11.98,status:'ok'}]};
data.runs = {job1:{status:'review'}};
ctx.renderSidebar(data);
assert.equal(root.children[0].children[0].children[1].textContent, '11.98 гр.');
assert.match(root.children[0].className, /selected-head/);
assert.doesNotMatch(root.children[1].className, /selected-head/);
data.monitor.active_head = 2; ctx.renderSidebar(data);
assert.doesNotMatch(root.children[0].className, /selected-head/);
assert.match(root.children[2].className, /selected-head/);
data.monitor.active_job_key = 'different'; ctx.renderSidebar(data);
assert.equal(root.children[0].children[0].children[1].textContent, 'PLA');
data.monitor.active_job_key = 'job1';
data.monitor.checked_at -= 60; ctx.renderSidebar(data);
assert.equal(root.children[0].children[0].children[1].textContent, 'PLA');
assert.ok(root.children.slice(0,4).every(item => !item.className.includes('selected-head')));
assert.match(root.children[4].textContent, /не определена/);
data.monitor.state = 'complete'; ctx.renderSidebar(data);
assert.equal(root.children.length, 4);
assert.ok(root.children.every(item => !item.className.includes('selected-head')));
'''
    result = subprocess.run([node_path, '-e', harness.replace('SOURCE', json.dumps(code))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
