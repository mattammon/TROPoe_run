// Run with: node tests/test_scatter_viewport.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('scatter_component/scatter.js', 'utf8');
const stored = new Map();
function mount() {
  const listeners = {}, handlers = {}, messages = [], layouts = [];
  let reset;
  const chart = {on:(name, fn) => { handlers[name] = fn; }};
  const context = vm.createContext({
    document:{getElementById:id => id === 'chart' ? chart : {addEventListener:(_, fn) => { reset = fn; }}},
    window:{parent:{postMessage:msg => messages.push(msg)}, addEventListener:(_, fn) => { listeners.render = fn; }},
    sessionStorage:{getItem:key => stored.get(key), setItem:(key, value) => stored.set(key, value)},
    Plotly:{react:async (_, data, layout) => layouts.push(JSON.parse(JSON.stringify(layout))),
            relayout:async (_, update) => { layouts.push(update); handlers.plotly_relayout(update); }},
  });
  vm.runInContext(code, context);
  return {handlers, messages, layouts, reset:() => reset(),
    render:async (range, group='a', collection=false) => {
      listeners.render({data:{type:'streamlit:render', args:{viewport_key:'review|master', collection_mode:collection, figure:JSON.stringify({
        data:[{name:group}], layout:{xaxis:{range}, yaxis:{range}, height:500}})}}});
      await vm.runInContext('sequence', context);
    }, wait:() => vm.runInContext('sequence', context)};
}
(async () => {
  let app = mount();
  await app.render([0,100]);
  app.handlers.plotly_relayout({'xaxis.range[0]':10, 'xaxis.range[1]':20, 'yaxis.range':[1,2]});
  await app.render([0,50], 'new classification');
  assert.deepEqual(app.layouts.at(-1).xaxis.range, [10,20]);
  assert.deepEqual(app.layouts.at(-1).yaxis.range, [1,2]);
  // A removed/recreated iframe (including empty filter results) keeps the view.
  app = mount();
  await app.render([0,200]);
  assert.deepEqual(app.layouts.at(-1).xaxis.range, [10,20]);
  app.handlers.plotly_click({points:[{customdata:['date', 'case-123']}]});
  assert.equal(app.messages.at(-1).value.case_id, 'case-123');
  await app.render([0,200], 'selection', true);
  app.handlers.plotly_selected({points:[{customdata:['date','a']},{customdata:['date','b']},{customdata:['date','a']}]});
  assert.deepEqual(Array.from(app.messages.at(-1).value.case_ids), ['a','b']);
  app.reset(); await app.wait();
  assert.deepEqual(Array.from(app.layouts.at(-1)['xaxis.range']), [0,200]);
  await app.render([0,200]);
  assert.deepEqual(app.layouts.at(-1).xaxis.range, [0,200]);
  console.log('Viewport persistence, remount, selection and manual reset passed.');
})().catch(error => {console.error(error); process.exitCode=1;});
