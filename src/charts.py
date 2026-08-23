from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class SvgChart:
    """
    SVG 图表对象。

    输入：
    - title: 图表标题
    - svg: SVG 字符串

    输出：
    - SvgChart 实例
    """

    title: str
    svg: str


def write_svg(path: str | Path, svg: str) -> str:
    """
    将 SVG 写入文件。

    输入：
    - path: 输出路径
    - svg: SVG 字符串

    输出：
    - saved_path: str
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(svg, encoding="utf-8")
    return str(p)


def bar_chart_svg(
    title: str,
    items: List[Tuple[str, float]],
    width: int = 900,
    height: int = 360,
    bar_color: str = "#4F8DF7",
) -> SvgChart:
    """
    生成简易水平条形图（SVG）。

    输入：
    - title: 标题
    - items: [(label, value)]
    - width/height: 画布尺寸
    - bar_color: 柱颜色

    输出：
    - SvgChart
    """
    padding_left = 220
    padding_right = 28
    padding_top = 52
    padding_bottom = 18
    plot_w = max(1, width - padding_left - padding_right)
    plot_h = max(1, height - padding_top - padding_bottom)

    max_v = max((v for _, v in items), default=1.0)
    max_v = max(max_v, 1.0)

    row_h = plot_h / max(len(items), 1)
    bar_h = row_h * 0.55

    def esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{padding_left}" y="28" font-size="18" font-family="sans-serif" fill="#111">{esc(title)}</text>',
    ]

    for i, (label, value) in enumerate(items):
        y_mid = padding_top + i * row_h + row_h * 0.5
        y = y_mid - bar_h / 2
        w = (float(value) / max_v) * plot_w

        svg.append(
            f'<text x="{padding_left - 10}" y="{y_mid + 5}" text-anchor="end" font-size="12" font-family="sans-serif" fill="#333">{esc(label)}</text>'
        )
        svg.append(f'<rect x="{padding_left}" y="{y}" width="{w}" height="{bar_h}" fill="{bar_color}" rx="4" ry="4"/>')
        svg.append(
            f'<text x="{padding_left + w + 8}" y="{y_mid + 5}" font-size="12" font-family="sans-serif" fill="#111">{value:g}</text>'
        )

    svg.append("</svg>")
    return SvgChart(title=title, svg="\n".join(svg))


def line_chart_svg(
    title: str,
    series: List[Tuple[str, List[Tuple[str, float]]]],
    width: int = 900,
    height: int = 360,
) -> SvgChart:
    """
    生成简易折线图（SVG），适合时间序列（按月/按周）。

    输入：
    - title: 标题
    - series: [(name, [(x_label, y_value), ...]), ...]

    输出：
    - SvgChart
    """
    padding_left = 54
    padding_right = 24
    padding_top = 52
    padding_bottom = 42
    plot_w = max(1, width - padding_left - padding_right)
    plot_h = max(1, height - padding_top - padding_bottom)

    palette = ["#4F8DF7", "#F97316", "#22C55E", "#A855F7"]
    x_labels = []
    if series and series[0][1]:
        x_labels = [x for x, _ in series[0][1]]
    n = max(len(x_labels), 1)

    max_v = 1.0
    for _, pts in series:
        for _, v in pts:
            max_v = max(max_v, float(v))

    def esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{padding_left}" y="28" font-size="18" font-family="sans-serif" fill="#111">{esc(title)}</text>',
        f'<line x1="{padding_left}" y1="{padding_top + plot_h}" x2="{padding_left + plot_w}" y2="{padding_top + plot_h}" stroke="#CBD5E1"/>',
        f'<line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_h}" stroke="#CBD5E1"/>',
    ]

    tick_count = 4
    for i in range(tick_count + 1):
        y = padding_top + plot_h - (plot_h * i / tick_count)
        val = max_v * i / tick_count
        svg.append(f'<line x1="{padding_left}" y1="{y}" x2="{padding_left + plot_w}" y2="{y}" stroke="#F1F5F9"/>')
        svg.append(f'<text x="{padding_left - 8}" y="{y + 4}" text-anchor="end" font-size="11" font-family="sans-serif" fill="#64748B">{val:g}</text>')

    for idx, (name, pts) in enumerate(series):
        color = palette[idx % len(palette)]
        points = []
        for i, (_, v) in enumerate(pts):
            x = padding_left + (plot_w * i / max(n - 1, 1))
            y = padding_top + plot_h - (plot_h * float(v) / max_v)
            points.append((x, y))
        if not points:
            continue
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)
        svg.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for x, y in points:
            svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="{color}"/>')
        svg.append(
            f'<text x="{padding_left + plot_w}" y="{padding_top + 18 + idx * 16}" text-anchor="end" font-size="12" font-family="sans-serif" fill="{color}">{esc(name)}</text>'
        )

    for i, lab in enumerate(x_labels):
        x = padding_left + (plot_w * i / max(n - 1, 1))
        svg.append(f'<text x="{x:.2f}" y="{padding_top + plot_h + 20}" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#64748B">{esc(lab)}</text>')

    svg.append("</svg>")
    return SvgChart(title=title, svg="\n".join(svg))


if __name__ == "__main__":
    demo = bar_chart_svg("星级分布", [("5★", 19), ("4★", 10), ("3★", 2), ("2★", 1), ("1★", 0)])
    p = Path(__file__).resolve().parent / "output" / "demo_rating.svg"
    print(write_svg(p, demo.svg))
