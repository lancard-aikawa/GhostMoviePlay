"""リプレイの再現性を確保する仕掛け.

同じ plan.json から何度でも同じ動画が録れることがこのツールの前提なので、
乱数と時刻という2つのブレ要因を潰せるようにしてある。

  "determinism": { "seed": 12345, "time": "2026-01-01T09:00:00" }

seed  : Math.random を seed 固定の PRNG (mulberry32) に差し替える
time  : page.clock で開始時刻を固定する (その後は実時間どおりに進む)

注意: seed が効くのは Math.random を使っているコードだけ。crypto.getRandomValues
や、サーバ側・WebAssembly 側の乱数までは面倒を見ない。
"""

from __future__ import annotations

SEED_JS_TEMPLATE = r"""
(() => {
  if (window.__gmpSeeded) return;
  window.__gmpSeeded = true;
  let s = (%SEED%) >>> 0;
  Math.random = () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
})();
"""


def seed_script(seed: int) -> str:
    return SEED_JS_TEMPLATE.replace("%SEED%", str(int(seed)))


def apply(page, determinism, verbose: bool = True) -> list[str]:
    """page に決定論化を仕込む。goto より前に呼ぶこと.

    戻り値は適用した項目の説明 (ログ用)。
    """
    applied: list[str] = []

    if determinism.time:
        # install しただけだと時計が止まるので resume で実時間進行に戻す。
        # 止めるとアニメーションや setTimeout も凍り、多くのアプリが動かなくなる。
        page.clock.install(time=determinism.time)
        page.clock.resume()
        applied.append(f"時刻を {determinism.time} に固定")

    if determinism.seed is not None:
        page.add_init_script(seed_script(determinism.seed))
        applied.append(f"Math.random を seed={determinism.seed} に固定")

    if applied and verbose:
        for item in applied:
            print(f"  決定論化: {item}")
    return applied
