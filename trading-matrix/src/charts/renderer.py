"""OHLC PNG without a browser."""

from __future__ import annotations

import io


def render_chart_image(candles: list[dict], title: str, width_px: int = 800, height_px: int = 400) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    fig.patch.set_facecolor("#0b1220")
    ax = fig.add_subplot(111)
    ax.set_facecolor("#0b1220")
    if candles:
        xs = range(len(candles))
        for x, candle in zip(xs, candles):
            o = float(candle["open"])
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
            color = "#10b981" if c >= o else "#ef4444"
            ax.plot([x, x], [l, h], color=color, linewidth=1)
            bottom = min(o, c)
            height = max(abs(c - o), 1e-9)
            ax.add_patch(
                plt.Rectangle((x - 0.3, bottom), 0.6, height, facecolor=color, edgecolor=color)
            )
    ax.set_title(title, color="#94a3b8", fontsize=10)
    ax.tick_params(colors="#94a3b8", labelsize=7)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
