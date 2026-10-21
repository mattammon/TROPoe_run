/* Keep ranges outside Streamlit's figure identity. Persist only within this tab. */
const chart = document.getElementById('chart');
let viewportKey = '', viewport = {}, figure = null, drawing = false, bound = false;
let sequence = Promise.resolve(), collectionMode = false;
function send(type, payload = {}) {
  window.parent.postMessage({isStreamlitMessage: true, type, ...payload}, '*');
}
function remember() {
  try { sessionStorage.setItem(viewportKey, JSON.stringify(viewport)); } catch (_) {}
}
function capture(event) {
  if (drawing) return;
  for (const axis of ['xaxis', 'yaxis']) {
    if (event[axis + '.autorange'] === true) {
      delete viewport[axis];
    } else if (event[axis + '.range']) {
      viewport[axis] = event[axis + '.range'];
    } else if (event[axis + '.range[0]'] !== undefined && event[axis + '.range[1]'] !== undefined) {
      viewport[axis] = [event[axis + '.range[0]'], event[axis + '.range[1]']];
    }
  }
  remember();
}
async function draw() {
  if (!figure) return;
  const layout = JSON.parse(JSON.stringify(figure.layout));
  layout.autosize = true;
  delete layout.width;
  layout.height = layout.height || 600;
  // Python's data-dependent ranges are defaults only; preserve the user's view.
  for (const axis of ['xaxis', 'yaxis']) {
    layout[axis] = {...layout[axis]};
    if (viewport[axis]) {
      layout[axis].range = viewport[axis];
      layout[axis].autorange = false;
    }
  }
  layout.uirevision = viewportKey;
  drawing = true;
  try {
    await Plotly.react(chart, figure.data, layout, {responsive:true, displaylogo:false});
    if (!bound) {
      chart.on('plotly_relayout', capture);
      chart.on('plotly_click', event => {
        const point = event.points && event.points[0];
        if (!point || !point.customdata) return;
        const caseId = point.customdata[point.customdata.length - 1];
        send('streamlit:setComponentValue', {value:{case_id:caseId, token:Date.now() + ':' + Math.random()}, dataType:'json'});
      });
      chart.on('plotly_selected', event => {
        if (!collectionMode || !event || !event.points) return;
        const ids = [...new Set(event.points.filter(p => p.customdata).map(p => p.customdata[p.customdata.length-1]))];
        send('streamlit:setComponentValue', {value:{case_ids:ids, token:Date.now()+':'+Math.random()}, dataType:'json'});
      });
      bound = true;
    }
    send('streamlit:setFrameHeight', {height:layout.height + 45});
  } finally { drawing = false; }
}
window.addEventListener('message', event => {
  if (event.data.type !== 'streamlit:render') return;
  const args = event.data.args;
  sequence = sequence.then(async () => {
    const nextKey = 'tropoe-viewport:' + args.viewport_key;
    if (viewportKey !== nextKey) {
      viewportKey = nextKey;
      try { viewport = JSON.parse(sessionStorage.getItem(viewportKey) || '{}'); } catch (_) { viewport = {}; }
    }
    collectionMode = Boolean(args.collection_mode);
    figure = JSON.parse(args.figure);
    await draw();
  });
});
document.getElementById('reset').addEventListener('click', () => {
  sequence = sequence.then(async () => {
    viewport = {};
    remember();
    // Explicit relayout defeats Plotly's uirevision preservation on manual reset.
    drawing = true;
    try {
      const update = {};
      for (const axis of ['xaxis', 'yaxis']) {
        update[axis + '.range'] = figure.layout[axis].range;
        update[axis + '.autorange'] = false;
      }
      await Plotly.relayout(chart, update);
    } finally { drawing = false; }
  });
});
send('streamlit:componentReady', {apiVersion:1});
send('streamlit:setFrameHeight', {height:645});
