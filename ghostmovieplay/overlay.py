"""収録用オーバーレイ (疑似カーソル / クリック波紋 / ハイライト / 黒み).

字幕は原則 ffmpeg で焼き込むのでここでは扱わない — が、ffmpeg を通さず
素の webm で確認したいとき用に DOM 字幕も持たせてある (--subtitle-mode dom)。

add_init_script で仕込むため、ナビゲーション後も自動で復活する。
body 未生成のタイミングでも壊れないよう、DOM 生成は ensure() で遅延させる。
"""

from __future__ import annotations

OVERLAY_JS = r"""
(() => {
  if (window.__gmp) return;
  const Z = '2147483647';
  let root = null, cursor = null, ring = null, caption = null, curtain = null;
  let cx = -100, cy = -100;

  function el(tag, style) {
    const e = document.createElement(tag);
    Object.assign(e.style, style);
    return e;
  }

  function ensure() {
    // ナビゲーションで飛んだら作り直す
    if (root && document.body && document.body.contains(root)) return true;
    if (!document.body) return false;

    root = el('div', {
      position: 'fixed', left: '0', top: '0', right: '0', bottom: '0',
      zIndex: Z, pointerEvents: 'none', overflow: 'hidden',
    });
    root.id = '__gmp_layer';

    ring = el('div', {
      position: 'absolute', border: '3px solid #ffd400', borderRadius: '6px',
      boxShadow: '0 0 0 9999px rgba(0,0,0,0.45), 0 0 14px rgba(255,212,0,0.9)',
      opacity: '0', transition: 'opacity 180ms ease',
    });
    root.appendChild(ring);

    caption = el('div', {
      position: 'absolute', left: '6%', right: '6%', bottom: '5%',
      textAlign: 'center', font: '600 30px/1.45 "Yu Gothic UI",Meiryo,sans-serif',
      color: '#fff', textShadow: '0 2px 0 #000,0 -2px 0 #000,2px 0 0 #000,-2px 0 0 #000,0 0 12px rgba(0,0,0,.8)',
      whiteSpace: 'pre-wrap', opacity: '0', transition: 'opacity 120ms ease',
    });
    root.appendChild(caption);

    cursor = el('div', {
      position: 'absolute', left: '0', top: '0', width: '26px', height: '26px',
      transform: 'translate(' + cx + 'px,' + cy + 'px)',
      transition: 'transform 0ms linear', willChange: 'transform',
    });
    cursor.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 26 26">' +
      '<path d="M3 2 L3 20 L8 15.5 L11.5 23 L15 21.4 L11.6 14.2 L18.5 14 Z" ' +
      'fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    root.appendChild(cursor);

    curtain = el('div', {
      position: 'absolute', left: '0', top: '0', right: '0', bottom: '0',
      background: '#000', opacity: '0', transition: 'opacity 400ms ease',
    });
    root.appendChild(curtain);

    document.body.appendChild(root);
    return true;
  }

  const NS = {
    ready() { return ensure(); },

    moveTo(x, y, ms) {
      if (!ensure()) return;
      cx = x - 4; cy = y - 3;   // 矢印の先端を座標に合わせる
      cursor.style.transition = 'transform ' + ms + 'ms cubic-bezier(.33,.7,.35,1)';
      cursor.style.transform = 'translate(' + cx + 'px,' + cy + 'px)';
    },

    ripple(x, y) {
      if (!ensure()) return;
      const r = el('div', {
        position: 'absolute', left: (x - 6) + 'px', top: (y - 6) + 'px',
        width: '12px', height: '12px', borderRadius: '50%',
        border: '3px solid #35c5ff', background: 'rgba(53,197,255,.35)',
        transform: 'scale(1)', opacity: '1',
        transition: 'transform 480ms ease-out, opacity 480ms ease-out',
      });
      root.appendChild(r);
      requestAnimationFrame(() => {
        r.style.transform = 'scale(4.2)';
        r.style.opacity = '0';
      });
      setTimeout(() => r.remove(), 560);
    },

    highlight(rect) {
      if (!ensure()) return;
      if (!rect) { ring.style.opacity = '0'; return; }
      const pad = 6;
      Object.assign(ring.style, {
        left: (rect.x - pad) + 'px', top: (rect.y - pad) + 'px',
        width: (rect.width + pad * 2) + 'px', height: (rect.height + pad * 2) + 'px',
        opacity: '1',
      });
    },

    clearHighlight() { if (ensure()) ring.style.opacity = '0'; },

    caption(text) {
      if (!ensure()) return;
      caption.textContent = text || '';
      caption.style.opacity = text ? '1' : '0';
    },

    curtain(on) {
      if (!ensure()) return;
      curtain.style.opacity = on ? '1' : '0';
    },
  };

  window.__gmp = NS;
  if (document.readyState !== 'loading') ensure();
  else document.addEventListener('DOMContentLoaded', ensure);
})();
"""
