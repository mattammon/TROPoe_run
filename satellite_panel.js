// Resize only the dashboard's satellite column. Width survives Streamlit reruns.
(() => {
  const win = window.parent, doc = win.document;
  if (win.__tropoeSatelliteCleanup) win.__tropoeSatelliteCleanup();
  let panel, column, row, handle, resizeObserver, startX, startWidth;
  let width = 480;
  try { width = Number(win.sessionStorage.getItem('tropoeSatelliteDockWidth')) || width; } catch (_) {}
  const clamp = (value, total) => Math.max(260, Math.min(value, Math.max(260, total * .65)));
  function apply(value) {
    if (!row || !column) return;
    const total = row.getBoundingClientRect().width;
    if (win.innerWidth <= 700) { column.style.removeProperty('flex'); column.style.removeProperty('width'); column.style.removeProperty('--tropoe-satellite-width'); return; }
    width = clamp(value, total);
    column.style.setProperty('flex', `0 0 ${width}px`, 'important');
    column.style.setProperty('width', `${width}px`, 'important');
    column.style.setProperty('--tropoe-satellite-width', `${width}px`);
    handle.setAttribute('aria-valuenow', Math.round(width));
    handle.setAttribute('aria-valuemax', Math.round(total * .65));
    win.dispatchEvent(new Event('resize'));
  }
  function save() { try { win.sessionStorage.setItem('tropoeSatelliteDockWidth', width); } catch (_) {} }
  function move(event) { if (startX !== undefined) apply(startWidth + startX - event.clientX); }
  function end() { if (startX !== undefined) save(); startX = undefined; }
  function detach() {
    if (resizeObserver) resizeObserver.disconnect();
    if (handle) handle.remove();
    if (column) { column.style.removeProperty('flex'); column.style.removeProperty('width'); column.style.removeProperty('--tropoe-satellite-width'); }
    panel = column = row = handle = null;
  }
  function attach() {
    const found = doc.querySelector('.st-key-satellite_dock');
    if (found === panel) return;
    detach();
    if (!found) return;
    panel = found;
    column = panel.closest('[data-testid="stColumn"]');
    if (!column) return;
    row = column.parentElement;
    handle = doc.createElement('div');
    handle.className = 'tropoe-satellite-resize';
    handle.tabIndex = 0;
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'vertical');
    handle.setAttribute('aria-label', 'Resize satellite panel');
    handle.setAttribute('aria-valuemin', '260');
    handle.title = 'Drag to resize satellite panel (or use arrow keys)';
    handle.addEventListener('pointerdown', event => {
      startX = event.clientX; startWidth = column.getBoundingClientRect().width;
      handle.setPointerCapture(event.pointerId); event.preventDefault();
    });
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        apply(width + (event.key === 'ArrowLeft' ? 20 : -20)); save(); event.preventDefault();
      }
    });
    column.appendChild(handle);
    resizeObserver = new win.ResizeObserver(() => apply(width));
    resizeObserver.observe(row);
    apply(width);
  }
  const observer = new win.MutationObserver(attach);
  observer.observe(doc.body, {childList: true, subtree: true});
  attach();
  win.__tropoeSatelliteCleanup = () => { observer.disconnect(); detach(); };
})();
