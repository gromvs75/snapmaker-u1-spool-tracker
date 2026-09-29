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
  'printer-status': element(), 'preflight-content': element(),
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
  el: id => nodes[id],
  node: (tag, value) => ({tag, textContent: value, children: [], append(child) {this.children.push(child);}})
});
vm.runInContext(HELPERS, context);
const data = {
  monitor: {connected: true, state: 'printing', filename: 'job.gcode', error: ''},
  last_preflight: {time: '10:00', summary: 'OK', rows: []},
  plans: {p: {created_at: 1, filename: 'job.gcode', status: 'active'}},
  runs: {r: {plan_id: 'p', start_time: 2, status: 'active'}},
  spools: {s: {name: 'Black', material: 'PLA', remaining_g: 900}}
};
context.updateLiveState(data);
assert.equal(input.value, '1000'); // Focused edit is untouched.
assert.equal(option.textContent, 'Black (900g, PLA)');
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
"""
    program = harness.replace("HELPERS", json.dumps(helpers))
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
