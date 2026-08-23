# graph.py
from langchain_core.messages.ai import AIMessage
import os
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from tools import AmazonReviewScraper, load_reviews_from_csv
from dotenv import load_dotenv
from prompt import build_tag_schema_prompt, build_review_tagging_prompt, build_report_writer_prompt, build_html_report_prompt
from report_export import export_reports
from utils import safe_json_loads, build_analysis_markdown
from analysis import (
    Overview,
    compute_overview,
    compute_tag_by_sentiment,
    compute_monthly_sentiment_series,
    build_overview_markdown,
    build_tag_sentiment_markdown,
    build_monthly_series_markdown,
    top_level3_sentiment,
)
from clustering import build_clustering_prompt, parse_clusters, clusters_to_markdown
from cache_store import compute_run_key, get_cache_dir, load_tag_cache, append_tag_cache, write_meta

load_dotenv()

class AgentState(TypedDict, total=False):
    asin: str
    product_title: str
    input_csv: str
    cache_base_dir: str
    max_reviews: int
    raw_reviews: List[Dict[str, Any]]
    tag_schema: Dict[str, Any]
    tagged_reviews: List[Dict[str, Any]]
    analysis_result: str
    overview: Dict[str, Any]
    tag_sentiment_top: List[Dict[str, Any]]
    monthly_series: List[Dict[str, Any]]
    clusters: Dict[str, Any]
    run_key: str
    cache_dir: str
    final_report: str
    final_html_report: str
    export_paths: Dict[str, str]


scraper = AmazonReviewScraper()

_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    """
    懒加载初始化 LLM，避免导入模块时就依赖外部环境。
    输入：
    - None
    输出：
    - llm: ChatOpenAI 实例
    """
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=os.getenv("DEFAULT_MODEL", "qwen3.7-plus-2026-05-26"), 
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL"),
            temperature=0)
    return _llm


def _get_review_text(review: Dict[str, Any]) -> str:
    """
    从结构化评论中获取正文文本字段。
    输入：
    - review: dict
    输出：
    - text: str
    """
    return (review or {}).get("text") or ""

def data_ingestion_node(state: AgentState):
    """节点1：数据获取"""
    input_csv = (state.get("input_csv") or "").strip()
    if input_csv:
        print(f"正在从 CSV 导入评论：{input_csv}")
        reviews = load_reviews_from_csv(input_csv, product_title=state.get("product_title"))
    else:
        print(f"正在抓取 ASIN: {state['asin']} 的评论...")
        max_reviews = int(state.get("max_reviews") or 50)
        reviews = scraper.scrape_reviews(state["asin"], max_reviews=max_reviews)
    product_title = ""
    if reviews:
        product_title = (reviews[0] or {}).get("product_title") or ""
    return {"raw_reviews": reviews, "product_title": product_title}

def tag_schema_generator_node(state: AgentState):
    """节点2：生成标签体系"""
    print("正在生成标签体系...")
    raw_reviews = state.get("raw_reviews") or []
    if not raw_reviews:
        return {"tag_schema": {}}

    sample_texts = [_get_review_text(r) for r in raw_reviews[:12]]
    prompt = build_tag_schema_prompt(sample_texts)
    response = get_llm().invoke(prompt)
    try:
        tag_schema = safe_json_loads(response.content)
        if not isinstance(tag_schema, dict):
            tag_schema = {}
    except Exception:
        tag_schema = {}
    return {"tag_schema": tag_schema}

def review_tagging_node(state: AgentState):
    """节点3：批量评论打标"""
    print("正在为评论打标签...")
    raw_reviews = state.get("raw_reviews") or []
    tag_schema = state.get("tag_schema") or {}
    if not raw_reviews or not tag_schema:
        return {"tagged_reviews": []}

    run_payload = {
        "asin": state.get("asin") or "",
        "input_csv": state.get("input_csv") or "",
        "product_title": state.get("product_title") or "",
        "tag_schema": tag_schema,
        "llm_model": os.getenv("DEFAULT_MODEL", "qwen3.7-plus-2026-05-26"),
        "tag_prompt_version": "v2-multi-map",
    }
    run_key = compute_run_key(run_payload)
    cache_dir = get_cache_dir(run_key, base_dir=state.get("cache_base_dir"))
    write_meta(cache_dir, {"run_key": run_key, **run_payload})

    cached = load_tag_cache(cache_dir)
    if cached:
        print(f"命中缓存：{len(cached)} 条已打标评论，将进行断点续跑")

    reviews_to_tag = []
    for r in raw_reviews:
        rid = str((r or {}).get("id") or "").strip()
        if rid and rid in cached:
            continue
        reviews_to_tag.append(r)

    prompts = [build_review_tagging_prompt(tag_schema, _get_review_text(r)) for r in raw_reviews]
    llm = get_llm()
    tag_by_id: Dict[str, Dict[str, Any]] = dict(cached)

    mode = (os.getenv("TAGGING_MODE") or "").strip().lower() or "batch"
    if mode == "sequential":
        for r in reviews_to_tag:
            rid = str((r or {}).get("id") or "").strip()
            if not rid:
                continue
            p = build_review_tagging_prompt(tag_schema, _get_review_text(r))
            try:
                resp = llm.invoke(p)
                tag_map = safe_json_loads(getattr(resp, "content", str(resp)))
                if not isinstance(tag_map, dict):
                    tag_map = {}
            except Exception:
                tag_map = {}
            tag_by_id[rid] = tag_map
            append_tag_cache(cache_dir, rid, tag_map)
    else:
        prompts_missing = [build_review_tagging_prompt(tag_schema, _get_review_text(r)) for r in reviews_to_tag]
        try:
            responses = llm.batch(prompts_missing)
            for r, resp in zip(reviews_to_tag, responses):
                rid = str((r or {}).get("id") or "").strip()
                if not rid:
                    continue
                try:
                    tag_map = safe_json_loads(getattr(resp, "content", str(resp)))
                    if not isinstance(tag_map, dict):
                        tag_map = {}
                except Exception:
                    tag_map = {}
                tag_by_id[rid] = tag_map
                append_tag_cache(cache_dir, rid, tag_map)
        except Exception:
            for r in reviews_to_tag:
                rid = str((r or {}).get("id") or "").strip()
                if not rid:
                    continue
                p = build_review_tagging_prompt(tag_schema, _get_review_text(r))
                try:
                    resp = llm.invoke(p)
                    tag_map = safe_json_loads(getattr(resp, "content", str(resp)))
                    if not isinstance(tag_map, dict):
                        tag_map = {}
                except Exception:
                    tag_map = {}
                tag_by_id[rid] = tag_map
                append_tag_cache(cache_dir, rid, tag_map)

    tagged_reviews: List[Dict[str, Any]] = []
    for review in raw_reviews:
        rid = str((review or {}).get("id") or "").strip()
        tag_map = tag_by_id.get(rid, {}) if rid else {}
        if not isinstance(tag_map, dict):
            tag_map = {}
        tagged_reviews.append({"original_review": review, "tag_map": tag_map})

    return {"tagged_reviews": tagged_reviews, "run_key": run_key, "cache_dir": str(cache_dir)}

def data_analysis_node(state: AgentState):
    """节点4：数据分析（数据概览/标签×星级/时间维度）"""
    print("正在进行数据分析...")
    raw_reviews = state.get("raw_reviews") or []
    tagged_reviews = state.get("tagged_reviews") or []
    overview = compute_overview(raw_reviews)
    tag_freq_md = build_analysis_markdown(tagged_reviews)
    tag_sent = compute_tag_by_sentiment(tagged_reviews)
    monthly = compute_monthly_sentiment_series(raw_reviews)

    analysis_md = ""
    analysis_md += build_overview_markdown(overview) + "\n"
    analysis_md += "## 二、标签频次统计\n\n" + tag_freq_md.strip() + "\n\n"
    analysis_md += build_tag_sentiment_markdown(tag_sent) + "\n"
    analysis_md += build_monthly_series_markdown(monthly) + "\n"

    top_sent = top_level3_sentiment(tag_sent, top_n=12)
    top_rows = [{"label": l3, "pos": pos, "neg": neg, "total": total} for l3, pos, neg, total in top_sent]

    return {
        "analysis_result": analysis_md.strip(),
        "overview": {
            "total_reviews": overview.total_reviews,
            "pos_reviews": overview.pos_reviews,
            "neg_reviews": overview.neg_reviews,
            "satisfaction": overview.satisfaction,
            "rating_distribution": overview.rating_distribution,
        },
        "tag_sentiment_top": top_rows,
        "monthly_series": monthly,
    }


def review_clustering_node(state: AgentState):
    """节点5：文本聚类（好评/差评）"""
    print("正在进行文本聚类（好评/差评）...")
    raw_reviews = state.get("raw_reviews") or []
    pos = [r for r in raw_reviews if isinstance(r.get("rating"), (int, float)) and float(r.get("rating")) >= 4]
    neg = [r for r in raw_reviews if isinstance(r.get("rating"), (int, float)) and float(r.get("rating")) <= 3]
    pos_sample = pos[:30]
    neg_sample = neg[:30]

    llm = get_llm()

    pos_prompt = build_clustering_prompt("好评", pos_sample, max_clusters=6)
    neg_prompt = build_clustering_prompt("差评", neg_sample, max_clusters=6)

    pos_clusters = []
    neg_clusters = []
    try:
        pos_resp = llm.invoke(pos_prompt)
        pos_clusters = parse_clusters(getattr(pos_resp, "content", str(pos_resp)))
    except Exception:
        pos_clusters = []
    try:
        neg_resp = llm.invoke(neg_prompt)
        neg_clusters = parse_clusters(getattr(neg_resp, "content", str(neg_resp)))
    except Exception:
        neg_clusters = []

    md = ""
    md += clusters_to_markdown("五、好评主题聚类", pos_clusters) + "\n"
    md += clusters_to_markdown("六、差评主题聚类", neg_clusters) + "\n"

    analysis = (state.get("analysis_result") or "").strip()
    if analysis:
        analysis = analysis + "\n\n" + md.strip()
    else:
        analysis = md.strip()

    return {
        "clusters": {"pos": [c.__dict__ for c in pos_clusters], "neg": [c.__dict__ for c in neg_clusters]},
        "analysis_result": analysis,
    }

def report_writer_node(state: AgentState):
    """节点6：撰写最终报告（LLM）"""
    print("正在撰写最终洞察报告...")
    analysis = (state.get("analysis_result") or "").strip()
    if not analysis:
        analysis = "## 数据分析结果\n\n暂无可用数据。"
    prompt = build_report_writer_prompt(state.get("asin") or "", analysis, product_title=state.get("product_title"))
    response = get_llm().invoke(prompt)
    return {"final_report": getattr(response, "content", str(response))}


def html_report_writer_node(state: AgentState):
    """节点7：生成可视化HTML报告（LLM）"""
    print("正在生成可视化 HTML 报告...")
    asin = state.get("asin") or ""
    product_title = state.get("product_title") or ""
    final_report = state.get("final_report") or ""
    
    prompt = build_html_report_prompt(asin, product_title, final_report)
    response = get_llm().invoke(prompt)
    html_content = getattr(response, "content", str(response)).strip()
    
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()
    
    return {"final_html_report": html_content}


def export_report_node(state: AgentState):
    """
    节点6：导出阶段性产物与最终报告。

    输入：
    - state: AgentState

    输出：
    - {"export_paths": {...}}
    """
    print("正在导出报告文件...")
    report_md = (state.get("final_report") or "").strip()
    analysis_md = (state.get("analysis_result") or "").strip()
    overview_dict = state.get("overview") or {}
    try:
        overview = Overview(
            total_reviews=int(overview_dict.get("total_reviews", 0)),
            pos_reviews=int(overview_dict.get("pos_reviews", 0)),
            neg_reviews=int(overview_dict.get("neg_reviews", 0)),
            satisfaction=float(overview_dict.get("satisfaction", 0.0)),
            rating_distribution=overview_dict.get("rating_distribution") or {},
        )
    except Exception:
        overview = None
    paths = export_reports(
        state.get("asin") or "",
        report_md,
        analysis_markdown=analysis_md,
        overview=overview,
        tag_sentiment_top=state.get("tag_sentiment_top") or [],
        monthly_series=state.get("monthly_series") or [],
        product_title=state.get("product_title") or "",
        tagged_reviews=state.get("tagged_reviews") or [],
        tag_schema=state.get("tag_schema") or {},
        final_html_report=state.get("final_html_report"),
    )
    return {"export_paths": paths}

# 4. 构建Graph
def build_graph():
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("data_ingestion", data_ingestion_node)
    workflow.add_node("generate_tags", tag_schema_generator_node)
    workflow.add_node("tag_reviews", review_tagging_node)
    workflow.add_node("analyze_data", data_analysis_node)
    workflow.add_node("cluster_reviews", review_clustering_node)
    workflow.add_node("write_report", report_writer_node)
    workflow.add_node("write_html_report", html_report_writer_node)
    workflow.add_node("export_report", export_report_node)

    # 定义边 (Edges)
    workflow.add_edge(START, "data_ingestion")
    workflow.add_edge("data_ingestion", "generate_tags")
    workflow.add_edge("generate_tags", "tag_reviews")
    workflow.add_edge("tag_reviews", "analyze_data")
    workflow.add_edge("analyze_data", "cluster_reviews")
    workflow.add_edge("cluster_reviews", "write_report")
    workflow.add_edge("write_report", "write_html_report")
    workflow.add_edge("write_html_report", "export_report")
    workflow.add_edge("export_report", END)

    return workflow.compile()

# 编译图
app = build_graph()


if __name__ == "__main__":
    demo_state: AgentState = {"asin": "B000TEST", "max_reviews": 1}
    print(app.get_graph().draw_ascii())
