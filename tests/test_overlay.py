"""オーバーレイの呼び口が record.py と揃っていること.

**呼び出しは全部 `window.__gmp && ...` で守ってある。** 遷移直後など層が
無い瞬間に落ちないための書き方だが、そのぶん **名前を変えても誰も落ちない**
—— 疑似カーソルが動かない動画が黙って撮れる。ブラウザを起こさずに
確かめられるのはここまでなので、せめて名前だけは突き合わせる。
"""

import re

from ghostmovieplay import record
from ghostmovieplay.overlay import OVERLAY_JS

# record.py の中の `window.__gmp.<名前>(` を全部拾う
CALLED = re.compile(r"window\.__gmp\.([A-Za-z]\w*)\s*\(")


def called_names() -> set[str]:
    import inspect

    return set(CALLED.findall(inspect.getsource(record)))


def test_every_call_site_has_something_to_call():
    names = called_names()
    # 呼んでいる先が 1 つも取れないなら、この検査自体が死んでいる
    assert {"moveTo", "ripple", "highlight", "clearHighlight", "caption"} <= names

    for name in sorted(names):
        assert re.search(rf"\b{name}\s*\(", OVERLAY_JS), \
            f"overlay に {name} が無い (record.py が黙って空振りする)"


def test_the_overlay_installs_itself_once():
    """add_init_script と goto 後の evaluate で 2 回通る. 二重に生やさない."""
    assert "if (window.__gmp) return;" in OVERLAY_JS
    assert "window.__gmp = NS;" in OVERLAY_JS


def test_the_layer_does_not_take_clicks():
    """飾りが操作を食うと、台本どおりに押しているのに反応しない画が撮れる."""
    assert "pointerEvents: 'none'" in OVERLAY_JS
