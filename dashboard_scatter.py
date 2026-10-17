"""Selectable Plotly scatter with browser-owned viewport across Streamlit reruns."""
from functools import lru_cache
from pathlib import Path
import tempfile

import plotly.io as pio
from plotly.offline import get_plotlyjs
import streamlit.components.v1 as components


@lru_cache(maxsize=1)
def _component():
    # Serve the installed Plotly bundle locally: no CDN or extra JS dependency.
    root = Path(tempfile.mkdtemp(prefix='tropoe_scatter_'))
    source = Path(__file__).with_name('scatter_component')
    for name in ('index.html', 'scatter.js'):
        (root/name).write_text((source/name).read_text(), encoding='utf-8')
    (root/'plotly.min.js').write_text(get_plotlyjs(), encoding='utf-8')
    return components.declare_component('tropoe_scatter', path=str(root))


def persistent_scatter(figure, key, scope=''):
    """Return clicked case IDs; zoom stays local and does not trigger a rerun."""
    return _component()(figure=pio.to_json(figure), viewport_key=key+'|'+str(scope),
                        key=key, default=None)
