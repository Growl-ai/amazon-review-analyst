from __future__ import annotations

import csv
import datetime as _dt
import html
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from utils import build_tag_columns
from charts import bar_chart_svg, line_chart_svg, write_svg
from analysis import Overview


def export_reports(
    asin: str,
    final_report_markdown: str,
    analysis_markdown: str | None = None,
    overview: Overview | None = None,
    tag_sentiment_top: List[Dict[str, Any]] | None = None,
    monthly_series: List[Dict[str, Any]] | None = None,
    product_title: str | None = None,
    tagged_reviews: Optional[List[Dict[str, Any]]] = None,
    tag_schema: Optional[Dict[str, Any]] = None,
    output_dir: str | Path | None = None,
    final_html_report: str | None = None,
) -> Dict[str, str]:
    """
    导出报告文件（最终报告 MD/HTML、分析结果 MD、打标结果 CSV）。

    输入：
    - asin: 商品 ASIN
    - final_report_markdown: 最终洞察报告（Markdown）
    - analysis_markdown: 标签频次统计（Markdown，可选）
    - overview: 数据概览（可选）
    - tag_sentiment_top: Top 三级标签好评/差评统计（可选）
    - monthly_series: 月度趋势数据（可选）
    - product_title: 商品名称（可选）
    - tagged_reviews: 打标后的评论列表（可选）
    - tag_schema: 标签体系（用于生成 CSV 列，可选）
    - output_dir: 输出目录（默认 agents/review-analyst/output）

    输出：
    - paths: 导出文件路径字典
    """
    asin = (asin or "").strip() or "UNKNOWN_ASIN"
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    base_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parent / "output"
    base_dir.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, str] = {}
    md_text = (final_report_markdown or "").strip() + "\n"

    product_title = (product_title or "").strip()
    title_line = f"# Amazon 评论洞察报告：{product_title}\n\n" if product_title else "# Amazon 评论洞察报告\n\n"
    subtitle = f"- ASIN：{asin}\n- 产品名称：{product_title or '未知'}\n\n"
    dashboard_md = title_line + subtitle

    chart_files: Dict[str, str] = {}
    if overview:
        items = [(f"{k}★", overview.rating_distribution.get(k, 0)) for k in range(5, 0, -1)]
        chart = bar_chart_svg("评分分布（评论数）", items)
        p = base_dir / f"{asin}_{timestamp}_rating_distribution.svg"
        chart_files["rating_distribution_svg"] = str(p)
        write_svg(p, chart.svg)
    if tag_sentiment_top:
        items2 = []
        for row in tag_sentiment_top:
            items2.append((str(row.get("label") or ""), float(row.get("total") or 0)))
        chart2 = bar_chart_svg("高频三级标签（总频次）", items2[:12], bar_color="#22C55E")
        p2 = base_dir / f"{asin}_{timestamp}_tag_top.svg"
        chart_files["tag_top_svg"] = str(p2)
        write_svg(p2, chart2.svg)
    if monthly_series:
        months = [str(r.get("month")) for r in monthly_series]
        pos = [float(r.get("pos") or 0) for r in monthly_series]
        neg = [float(r.get("neg") or 0) for r in monthly_series]
        series = [
            ("正面(4-5星)", list(zip(months, pos))),
            ("负面(1-3星)", list(zip(months, neg))),
        ]
        chart3 = line_chart_svg("月度正负评论趋势", series)
        p3 = base_dir / f"{asin}_{timestamp}_monthly_trend.svg"
        chart_files["monthly_trend_svg"] = str(p3)
        write_svg(p3, chart3.svg)

    if overview:
        dashboard_md += "## 一、数据概览\n\n"
        dashboard_md += f"- 总评论数：{overview.total_reviews}\n"
        dashboard_md += f"- 正面评价(4-5星)：{overview.pos_reviews}\n"
        dashboard_md += f"- 负面评价(1-3星)：{overview.neg_reviews}\n"
        dashboard_md += f"- 满意度：{overview.satisfaction * 100:.1f}%\n\n"
        if "rating_distribution_svg" in chart_files:
            dashboard_md += f"![]({Path(chart_files['rating_distribution_svg']).name})\n\n"

    if analysis_markdown:
        dashboard_md += "## 二、统计分析\n\n"
        dashboard_md += (analysis_markdown or "").strip() + "\n\n"

    if "tag_top_svg" in chart_files:
        dashboard_md += "## 三、标签可视化\n\n"
        dashboard_md += f"![]({Path(chart_files['tag_top_svg']).name})\n\n"

    if "monthly_trend_svg" in chart_files:
        dashboard_md += "## 四、时间维度\n\n"
        dashboard_md += f"![]({Path(chart_files['monthly_trend_svg']).name})\n\n"

    md_text = dashboard_md + "## 五、洞察与建议（LLM生成）\n\n" + md_text

    report_md_path = base_dir / f"{asin}_{timestamp}_report.md"
    report_md_path.write_text(md_text, encoding="utf-8")
    paths["report_markdown_path"] = str(report_md_path)

    report_html_path = base_dir / f"{asin}_{timestamp}_report.html"
    
    if final_html_report:
        html_content = final_html_report
        if "rating_distribution_svg" in chart_files:
            html_content = html_content.replace("[RATING_DISTRIBUTION_SVG]", Path(chart_files["rating_distribution_svg"]).name)
        if "tag_top_svg" in chart_files:
            html_content = html_content.replace("[TAG_TOP_SVG]", Path(chart_files["tag_top_svg"]).name)
        if "monthly_trend_svg" in chart_files:
            html_content = html_content.replace("[MONTHLY_TREND_SVG]", Path(chart_files["monthly_trend_svg"]).name)
        report_html_path.write_text(html_content, encoding="utf-8")
    else:
        report_html_path.write_text(
            _build_dashboard_html(
                asin=asin,
                product_title=product_title,
                final_report_markdown=final_report_markdown,
                analysis_markdown=analysis_markdown or "",
                overview=overview,
                chart_files={k: Path(v).name for k, v in chart_files.items()},
            ),
            encoding="utf-8",
        )
    paths["report_html_path"] = str(report_html_path)

    if analysis_markdown:
        analysis_path = base_dir / f"{asin}_{timestamp}_analysis.md"
        analysis_path.write_text((analysis_markdown or "").strip() + "\n", encoding="utf-8")
        paths["analysis_markdown_path"] = str(analysis_path)

    if tagged_reviews is not None and tag_schema is not None:
        csv_path = base_dir / f"{asin}_{timestamp}_tagged.csv"
        export_tagged_csv(csv_path, tagged_reviews=tagged_reviews, tag_schema=tag_schema)
        paths["tagged_csv_path"] = str(csv_path)

    return paths


def _build_html(asin: str, markdown: str) -> str:
    """
    将 markdown 文本包装为一个可直接打开的 HTML（不做 markdown 渲染）。

    输入：
    - asin: 商品 ASIN
    - markdown: markdown 内容

    输出：
    - html: str
    """
    safe = html.escape(markdown or "")
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Amazon Review Insight Report - {html.escape(asin)}</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; margin: 24px; color: #111; }}
      header {{ margin-bottom: 16px; }}
      h1 {{ font-size: 20px; margin: 0 0 8px 0; }}
      .meta {{ color: #666; font-size: 12px; }}
      pre {{ white-space: pre-wrap; word-break: break-word; background: #f6f8fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; line-height: 1.5; }}
    </style>
  </head>
  <body>
    <header>
      <h1>Amazon Review Insight Report</h1>
      <div class="meta">ASIN: {html.escape(asin)}</div>
    </header>
    <pre>{safe}</pre>
  </body>
</html>
"""


def _build_dashboard_html(
    asin: str,
    product_title: str,
    final_report_markdown: str,
    analysis_markdown: str,
    overview: Overview | None,
    chart_files: Dict[str, str],
) -> str:
    title = product_title or "Amazon 评论洞察报告"
    cards = ""
    if overview:
        cards = f"""
        <div class="cards">
          <div class="card"><div class="k">总评论数</div><div class="v">{overview.total_reviews}</div></div>
          <div class="card"><div class="k">正面(4-5星)</div><div class="v">{overview.pos_reviews}</div></div>
          <div class="card"><div class="k">负面(1-3星)</div><div class="v">{overview.neg_reviews}</div></div>
          <div class="card"><div class="k">满意度</div><div class="v">{overview.satisfaction * 100:.1f}%</div></div>
        </div>
        """
    charts_html = ""
    if "rating_distribution_svg" in chart_files:
        charts_html += f'<section class="panel"><h2>评分分布</h2><a class="chart-link" href="{chart_files["rating_distribution_svg"]}" target="_blank"><img class="chart" src="{chart_files["rating_distribution_svg"]}" /></a></section>'
    if "tag_top_svg" in chart_files:
        charts_html += f'<section class="panel"><h2>高频标签</h2><a class="chart-link" href="{chart_files["tag_top_svg"]}" target="_blank"><img class="chart" src="{chart_files["tag_top_svg"]}" /></a></section>'
    if "monthly_trend_svg" in chart_files:
        charts_html += f'<section class="panel"><h2>时间趋势</h2><a class="chart-link" href="{chart_files["monthly_trend_svg"]}" target="_blank"><img class="chart" src="{chart_files["monthly_trend_svg"]}" /></a></section>'

    analysis_html = _markdown_to_html(analysis_markdown or "")
    report_html = _markdown_to_html(final_report_markdown or "")
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{html.escape(title)} - {html.escape(asin)}</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; margin: 22px; color: #0f172a; background: #0b1220; }}
      .container {{ max-width: 1120px; margin: 0 auto; }}
      header {{ background: linear-gradient(180deg, rgba(79,141,247,.25), rgba(15,23,42,.15)); border: 1px solid rgba(148,163,184,.25); border-radius: 16px; padding: 18px 18px; margin-bottom: 16px; }}
      h1 {{ font-size: 22px; margin: 0 0 6px 0; color: #e2e8f0; }}
      .meta {{ color: #94a3b8; font-size: 13px; }}
      .cards {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }}
      .card {{ background: rgba(2,6,23,.35); border: 1px solid rgba(148,163,184,.18); border-radius: 12px; padding: 12px; }}
      .card .k {{ color: #94a3b8; font-size: 12px; }}
      .card .v {{ color: #e2e8f0; font-size: 22px; font-weight: 700; margin-top: 6px; }}
      .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }}
      .panel {{ background: rgba(2,6,23,.35); border: 1px solid rgba(148,163,184,.18); border-radius: 16px; padding: 14px; }}
      .panel h2 {{ margin: 0 0 10px 0; font-size: 16px; color: #e2e8f0; }}
      a.chart-link {{ display: block; }}
      img.chart {{ width: 100%; height: 240px; object-fit: contain; border-radius: 12px; background: white; }}
      @media (max-width: 980px) {{
        .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      }}
      @media (max-width: 640px) {{
        body {{ margin: 14px; }}
        .grid {{ grid-template-columns: 1fr; }}
        .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        img.chart {{ height: 210px; }}
      }}

      .md {{ color: #e2e8f0; line-height: 1.7; }}
      .md h1, .md h2, .md h3, .md h4 {{ color: #e2e8f0; margin: 16px 0 10px; }}
      .md h1 {{ font-size: 20px; }}
      .md h2 {{ font-size: 17px; }}
      .md h3 {{ font-size: 15px; }}
      .md p {{ margin: 10px 0; color: #cbd5e1; }}
      .md ul {{ margin: 8px 0 12px 20px; color: #cbd5e1; }}
      .md li {{ margin: 4px 0; }}
      .md code {{ background: rgba(148,163,184,.18); border: 1px solid rgba(148,163,184,.18); border-radius: 6px; padding: 0 6px; }}
      .md pre {{ background: rgba(2,6,23,.55); border: 1px solid rgba(148,163,184,.18); border-radius: 12px; padding: 12px; overflow-x: auto; }}
      .md pre code {{ border: none; background: transparent; padding: 0; }}
      .md table {{ width: 100%; border-collapse: collapse; margin: 10px 0 14px; }}
      .md th, .md td {{ border: 1px solid rgba(148,163,184,.18); padding: 8px 10px; text-align: left; }}
      .md th {{ background: rgba(148,163,184,.10); color: #e2e8f0; }}
      .md td {{ color: #cbd5e1; }}
      .md img {{ max-width: 100%; height: auto; border-radius: 10px; background: white; }}
      .divider {{ height: 1px; background: rgba(148,163,184,.18); margin: 12px 0 14px; }}
    </style>
  </head>
  <body>
    <div class="container">
      <header>
        <h1>{html.escape(title)}</h1>
        <div class="meta">ASIN：{html.escape(asin)} ｜ 产品名称：{html.escape(product_title or "未知")}</div>
        {cards}
      </header>

      <div class="grid">
        {charts_html}
      </div>

      <section class="panel">
        <h2>统计分析</h2>
        <div class="md">{analysis_html}</div>
        <div class="divider"></div>
        <h2>洞察与建议</h2>
        <div class="md">{report_html}</div>
      </section>
    </div>
  </body>
</html>
"""


def _md_inline(text: str) -> str:
    text = html.escape(text or "")
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', text)
    return text


def _markdown_to_html(md: str) -> str:
    md = (md or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not md:
        return "<p>（无内容）</p>"

    lines = md.split("\n")
    out: List[str] = []
    i = 0
    in_code = False
    code_lines: List[str] = []
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def flush_code():
        nonlocal in_code, code_lines
        if in_code:
            out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
            in_code = False
            code_lines = []

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
            else:
                close_ul()
                in_code = True
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if re.match(r"^#{1,6}\s+", line):
            close_ul()
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            out.append(f"<h{level}>{_md_inline(title)}</h{level}>")
            i += 1
            continue

        if line.strip().startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append("<li>" + _md_inline(line.strip()[2:].strip()) + "</li>")
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            close_ul()
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i]:
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(row_cells)
                i += 1
            thead = "<tr>" + "".join(f"<th>{_md_inline(c)}</th>" for c in header_cells) + "</tr>"
            tbody_rows = []
            for r in rows:
                padded = r + [""] * max(0, len(header_cells) - len(r))
                tbody_rows.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in padded[: len(header_cells)]) + "</tr>")
            out.append("<table><thead>" + thead + "</thead><tbody>" + "".join(tbody_rows) + "</tbody></table>")
            continue

        m_img = re.match(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$", line)
        if m_img:
            close_ul()
            src = html.escape(m_img.group(1).strip())
            out.append(f'<p><img src="{src}" alt="" /></p>')
            i += 1
            continue

        if not line.strip():
            close_ul()
            i += 1
            continue

        close_ul()
        out.append("<p>" + _md_inline(line.strip()) + "</p>")
        i += 1

    flush_code()
    close_ul()
    return "\n".join(out)


def export_tagged_csv(path: str | Path, tagged_reviews: List[Dict[str, Any]], tag_schema: Dict[str, Any]) -> None:
    """
    导出打标结果 CSV（符合项目说明的列结构：评论ID、评论内容、一级-二级列...）。

    输入：
    - path: 输出路径
    - tagged_reviews: [{"original_review": {"id":..., "text":...}, "tag_map": {...}}, ...]
    - tag_schema: {"一级": {"二级": ["三级", ...]}}

    输出：
    - None（写文件）
    """
    columns = build_tag_columns(tag_schema)
    headers = ["评论ID", "评论内容", *columns]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for item in tagged_reviews or []:
            review = item.get("original_review") or {}
            tag_map = item.get("tag_map") or {}
            row: Dict[str, Any] = {"评论ID": review.get("id") or "", "评论内容": review.get("text") or ""}
            for col in columns:
                level1, level2 = col.split("-", 1)
                values = []
                if isinstance(tag_map, dict):
                    level2_map = tag_map.get(level1) or {}
                    if isinstance(level2_map, dict):
                        values = level2_map.get(level2) or []
                row[col] = json.dumps(values, ensure_ascii=False)
            writer.writerow(row)


if __name__ == "__main__":
    demo_schema = {"功能价值": {"核心功能": ["理毛效果", "吸力强弱"]}}
    demo_tagged = [{"original_review": {"id": "r1", "text": "x"}, "tag_map": {"功能价值": {"核心功能": ["理毛效果"]}}}]
    demo_overview = Overview(total_reviews=10, pos_reviews=7, neg_reviews=3, satisfaction=0.7, rating_distribution={1: 1, 2: 2, 3: 0, 4: 3, 5: 4})
    print(
        export_reports(
            "B000TEST",
            "# 洞察\n\nHello",
            analysis_markdown="# 标签频次统计\n",
            overview=demo_overview,
            tag_sentiment_top=[{"label": "理毛效果", "total": 10}],
            monthly_series=[{"month": "2024-01", "pos": 3, "neg": 1}, {"month": "2024-02", "pos": 4, "neg": 2}],
            tagged_reviews=demo_tagged,
            tag_schema=demo_schema,
            product_title="Demo Product",
        )
    )
