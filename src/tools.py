# tools.py
from __future__ import annotations

import hashlib
import csv
import os
import re
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

load_dotenv()

try:
    from firecrawl import FirecrawlApp
except ModuleNotFoundError:
    FirecrawlApp = None


def load_reviews_from_csv(file_path: str, product_title: str | None = None) -> List[Dict[str, Any]]:
    """
    从 CSV 文件加载结构化评论列表（用于绕过抓取限制，进行全链路测试）。

    输入：
    - file_path: CSV 文件路径
    - product_title: 商品名称（可选；若不传则留空）

    输出：
    - reviews: List[Dict[str, Any]]，字段遵循 raw_reviews 契约（id/rating/text/date/verified/helpful）
    """
    file_path = (file_path or "").strip()
    if not file_path:
        raise ValueError("file_path 不能为空")
    p = os.path.abspath(file_path)
    if not os.path.exists(p):
        raise FileNotFoundError(p)

    product_title = (product_title or "").strip()

    def get_first(row: Dict[str, Any], keys: List[str]) -> str:
        for k in keys:
            if k in row and str(row.get(k) or "").strip():
                return str(row.get(k) or "").strip()
        return ""

    def parse_bool(v: Any) -> bool:
        s = str(v or "").strip().lower()
        if not s:
            return False
        return "verified" in s or s in {"1", "true", "yes", "y"}

    def parse_int(v: Any) -> int:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return 0

    def parse_float(v: Any) -> float | None:
        s = str(v or "").strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    reviews: List[Dict[str, Any]] = []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = get_first(row, ["ID", "Id", "id", "Review ID", "review_id", "评论ID"])
            title = get_first(row, ["Title", "title", "Review Title", "review_title"])
            rating = parse_float(get_first(row, ["Rating", "rating", "Stars", "stars"]))
            text = get_first(row, ["Review Content", "review_content", "Content", "content", "Text", "text", "评论内容"])
            date = get_first(row, ["Date", "date"])
            verified = parse_bool(get_first(row, ["Verified", "verified"]))
            helpful = parse_int(get_first(row, ["Helpful", "helpful"]))

            if not text:
                continue
            reviews.append(
                {
                    "id": rid or hashlib.sha1((title + "|" + text).encode("utf-8")).hexdigest()[:12],
                    "rating": rating,
                    "title": title,
                    "text": text,
                    "date": date,
                    "verified": verified,
                    "helpful": helpful,
                    "product_title": product_title,
                }
            )
    return reviews

class AmazonReviewScraper:
    def __init__(self, api_key: Optional[str] = None, marketplace_domain: str = "www.amazon.com"):
        """
        初始化亚马逊评论抓取器。

        输入：
        - api_key: Firecrawl API Key（可选，默认从环境变量 FIRECRAWL_API_KEY 读取）
        - marketplace_domain: 亚马逊站点域名（默认 www.amazon.com）

        输出：
        - AmazonReviewScraper 实例
        """
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        self.marketplace_domain = marketplace_domain
        self.app = None

    def scrape_reviews(self, asin: str, max_reviews: int = 50) -> List[Dict]:
        """
        根据 ASIN 抓取亚马逊评论并解析为结构化数据。

        输入：
        - asin: 商品 ASIN
        - max_reviews: 最大返回评论条数

        输出：
        - reviews: List[Dict]，每条评论至少包含字段：id/text/rating/date/verified/helpful
        """
        if not asin or not asin.strip():
            raise ValueError("asin 不能为空")
        if not self.api_key:
            raise ValueError("缺少 FIRECRAWL_API_KEY，请在 .env 中配置")
        if FirecrawlApp is None:
            raise ModuleNotFoundError("未安装 firecrawl 依赖，请先安装项目依赖（firecrawl-py）")
        if self.app is None:
            self.app = FirecrawlApp(api_key=self.api_key)

        asin = asin.strip()
        url = (
            f"https://{self.marketplace_domain}/product-reviews/{asin}/"
            f"?reviewerType=all_reviews&sortBy=recent&pageNumber=1"
        )

        max_reviews = max(1, int(max_reviews))
        scroll_steps = min(10, max(2, (max_reviews + 7) // 8))
        actions = []
        for _ in range(scroll_steps):
            actions.append({"type": "scroll", "direction": "down"})
            actions.append({"type": "wait", "milliseconds": 1500})

        mobile = os.getenv("FIRECRAWL_MOBILE", "1") not in {"0", "false", "False"}
        proxy_first = os.getenv("FIRECRAWL_PROXY", "auto")
        proxy_candidates = [proxy_first, "stealth", "enhanced"]
        proxies = []
        for p in proxy_candidates:
            if p and p not in proxies:
                proxies.append(p)

        scrape_result = None
        markdown = ""
        html = ""
        reviews: List[Dict[str, Any]] = []
        used_proxy = ""

        for proxy in proxies:
            used_proxy = proxy
            try:
                scrape_result = self.app.scrape_url(
                    url,
                    formats=["markdown", "html"],
                    actions=actions,
                    only_main_content=False,
                    mobile=mobile,
                    proxy=proxy,
                    headers={
                        "accept-language": "en-US,en;q=0.9",
                    },
                )
            except Exception as e:
                if self._is_country_restricted_error(e):
                    scrape_result = self.app.scrape_url(
                        url,
                        formats=["markdown", "html"],
                        only_main_content=False,
                        mobile=mobile,
                        proxy=proxy,
                    )
                else:
                    raise

            markdown = self._extract_markdown(scrape_result)
            html = self._extract_html(scrape_result)

            if self._looks_blocked(markdown, html):
                continue

            reviews = self.parse_reviews_from_markdown(markdown)
            if not reviews and html:
                reviews = self.parse_reviews_from_html(html)
            if reviews:
                break

        if not reviews:
            extracted = self._fallback_extract_reviews_via_json(url, actions=actions, proxy=used_proxy, source_html=html)
            if extracted:
                reviews = extracted

        product_title = self._extract_product_title(scrape_result, markdown=markdown) if scrape_result is not None else ""
        for r in reviews:
            r.setdefault("product_title", product_title)
        normalized = [r for r in (self._normalize_review(r) for r in reviews) if r.get("text")]
        return normalized[:max_reviews]

    def _extract_markdown(self, scrape_result: Any) -> str:
        """
        从 Firecrawl 返回对象中提取 markdown 字符串。

        输入：
        - scrape_result: Firecrawl 返回值（dict 或 Document）

        输出：
        - markdown: str
        """
        if isinstance(scrape_result, dict):
            for key in ("markdown", "content", "data"):
                if key not in scrape_result:
                    continue
                value = scrape_result.get(key)
                if isinstance(value, str) and value.strip():
                    return value
                if isinstance(value, dict):
                    md = value.get("markdown")
                    if isinstance(md, str) and md.strip():
                        return md
        markdown = getattr(scrape_result, "markdown", None)
        if isinstance(markdown, str) and markdown.strip():
            return markdown
        raise ValueError("Firecrawl 返回内容中未找到 markdown")

    def _extract_html(self, scrape_result: Any) -> str:
        """
        从 Firecrawl 返回对象中提取 html 字符串。

        输入：
        - scrape_result: Firecrawl 返回值（dict 或 Document）

        输出：
        - html: str（可能为空）
        """
        if isinstance(scrape_result, dict):
            value = scrape_result.get("html")
            if isinstance(value, str) and value.strip():
                return value
            data = scrape_result.get("data")
            if isinstance(data, dict):
                html_value = data.get("html")
                if isinstance(html_value, str) and html_value.strip():
                    return html_value
        html_value = getattr(scrape_result, "html", None)
        if isinstance(html_value, str) and html_value.strip():
            return html_value
        return ""

    def _is_country_restricted_error(self, error: Exception) -> bool:
        """
        判断是否为 Firecrawl 的国家/区域能力限制错误。

        输入：
        - error: Exception

        输出：
        - is_restricted: bool
        """
        msg = str(error or "").lower()
        return "not allowed by default in your country" in msg or "website not supported" in msg

    def _looks_blocked(self, markdown: str, html: str) -> bool:
        """
        判断抓取结果是否疑似被反爬拦截（返回截图/验证码页等）。

        输入：
        - markdown: 页面 markdown
        - html: 页面 html

        输出：
        - blocked: bool
        """
        md = (markdown or "").strip()
        h = (html or "").strip()
        if not h and md.startswith("![](") and "amazon" in md.lower():
            return True
        if h and ("captcha" in h.lower() or "robot" in h.lower() or "enter the characters" in h.lower()):
            return True
        if h and ("data-hook=\"review\"" in h or "data-hook='review'" in h):
            return False
        if "out of 5 stars" in md.lower() or "reviewed in" in md.lower():
            return False
        if h and len(h) < 1500 and md.startswith("![]("):
            return True
        return False

    def _extract_product_title(self, scrape_result: Any, markdown: str) -> str:
        """
        提取商品名称（尽量从 Firecrawl metadata/title 获取，失败则从 markdown 首行推测）。

        输入：
        - scrape_result: Firecrawl 返回值（dict 或 Document）
        - markdown: 页面 markdown 文本

        输出：
        - product_title: str（可能为空）
        """
        if isinstance(scrape_result, dict):
            meta = scrape_result.get("metadata") or {}
            if isinstance(meta, dict):
                title = meta.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()
            title = scrape_result.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()

        meta = getattr(scrape_result, "metadata", None)
        title = getattr(meta, "title", None) if meta is not None else None
        if isinstance(title, str) and title.strip():
            return title.strip()

        md = (markdown or "").strip()
        if not md:
            return ""
        first_line = md.splitlines()[0].strip("# ").strip()
        if first_line and len(first_line) <= 120:
            return first_line
        return ""

    def parse_reviews_from_markdown(self, markdown: str) -> List[Dict[str, Any]]:
        """
        将亚马逊评论页的 markdown 解析为结构化评论列表。

        输入：
        - markdown: Firecrawl 返回的 markdown 文本

        输出：
        - reviews: List[Dict[str, Any]]
        """
        markdown = markdown or ""

        rating_re = re.compile(r"(?P<rating>\d(?:\.\d)?)\s+out of\s+5\s+stars", re.IGNORECASE)
        author_re = re.compile(r"^By\s+(?P<author>.+)$", re.IGNORECASE)
        reviewed_re = re.compile(r"Reviewed in\s+(?P<region>.+?)\s+on\s+(?P<date>.+)$", re.IGNORECASE)
        helpful_re = re.compile(r"(?P<count>\d+)\s+(people\s+)?found\s+this\s+helpful", re.IGNORECASE)

        reviews: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}
        buffer_lines: List[str] = []

        def flush():
            nonlocal current, buffer_lines
            if not current:
                buffer_lines = []
                return
            text = self._clean_review_text("\n".join(buffer_lines)).strip()
            current["text"] = text
            reviews.append(current)
            current = {}
            buffer_lines = []

        for raw_line in markdown.splitlines():
            line = (raw_line or "").strip()
            if not line:
                continue

            rating_match = rating_re.search(line)
            if rating_match:
                flush()
                current = {"rating": float(rating_match.group("rating"))}
                continue

            if not current:
                continue

            if "verified purchase" in line.lower():
                current["verified"] = True
                continue
            helpful_match = helpful_re.search(line)
            if helpful_match:
                try:
                    current["helpful"] = int(helpful_match.group("count"))
                except Exception:
                    current["helpful"] = None
                continue
            if line.lower().startswith("helpful") or line.lower().startswith("report"):
                continue

            m_author = author_re.match(line)
            if m_author and "author" not in current:
                current["author"] = m_author.group("author").strip()
                continue

            m_reviewed = reviewed_re.search(line)
            if m_reviewed:
                current["reviewed_in"] = m_reviewed.group("region").strip()
                current["date"] = m_reviewed.group("date").strip()
                continue

            if "title" not in current and len(line) <= 120 and not line.lower().startswith("read more"):
                current["title"] = line.strip("*# ").strip()
                continue

            buffer_lines.append(line)

        flush()
        return reviews

    def parse_reviews_from_html(self, html: str) -> List[Dict[str, Any]]:
        """
        从亚马逊评论页 HTML 中提取评论信息（作为 markdown 解析失败时的兜底）。

        输入：
        - html: 页面 HTML

        输出：
        - reviews: List[Dict[str, Any]]
        """
        html = html or ""
        if not html.strip():
            return []

        rating_re = re.compile(r'(\d(?:\.\d)?)\s+out of\s+5\s+stars', re.IGNORECASE)
        review_block_re = re.compile(r'<div[^>]+data-hook="review"[\s\S]*?</div>\s*</div>', re.IGNORECASE)
        body_re = re.compile(r'data-hook="review-body"[\s\S]*?<span[^>]*>([\s\S]*?)</span>', re.IGNORECASE)
        title_re = re.compile(r'data-hook="review-title"[\s\S]*?<span[^>]*>([\s\S]*?)</span>', re.IGNORECASE)
        date_re = re.compile(r'Reviewed in[\s\S]*? on ([A-Za-z]+\s+\d{1,2},\s+\d{4})', re.IGNORECASE)
        verified_re = re.compile(r'data-hook="avp-badge"', re.IGNORECASE)
        helpful_re = re.compile(r'(\d+)\s+people\s+found\s+this\s+helpful', re.IGNORECASE)

        def strip_tags(s: str) -> str:
            s = re.sub(r"<[^>]+>", " ", s or "")
            s = re.sub(r"\s+", " ", s).strip()
            return s

        reviews: List[Dict[str, Any]] = []
        blocks = review_block_re.findall(html)
        if not blocks:
            blocks = html.split('data-hook="review"')
            blocks = ["data-hook=\"review\"" + b for b in blocks[1:]]

        for b in blocks[:200]:
            rating_match = rating_re.search(b)
            rating = float(rating_match.group(1)) if rating_match else None
            body_match = body_re.search(b)
            text = strip_tags(body_match.group(1)) if body_match else ""
            title_match = title_re.search(b)
            title = strip_tags(title_match.group(1)) if title_match else ""
            date_match = date_re.search(b)
            date = date_match.group(1).strip() if date_match else ""
            verified = bool(verified_re.search(b))
            helpful_match = helpful_re.search(b)
            helpful = int(helpful_match.group(1)) if helpful_match else 0

            if not text:
                continue
            reviews.append(
                {
                    "rating": rating,
                    "title": title,
                    "date": date,
                    "verified": verified,
                    "helpful": helpful,
                    "text": text,
                }
            )
        return reviews

    def _clean_review_text(self, text: str) -> str:
        """
        清洗评论正文文本（去掉 Read more 等噪声并压缩空白）。

        输入：
        - text: 原始文本

        输出：
        - cleaned: 清洗后的文本
        """
        text = text or ""
        text = re.sub(r"\s*\[Read more\]\s*", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _normalize_review(self, review: Dict[str, Any]) -> Dict[str, Any]:
        """
        标准化单条评论字段，补齐必需字段。

        输入：
        - review: 评论 dict

        输出：
        - normalized_review: 标准化后的 dict
        """
        review = dict[str, Any](review or {})
        review["text"] = (review.get("text") or "").strip()
        review.setdefault("verified", False)
        review.setdefault("helpful", 0)
        rating = review.get("rating")
        if isinstance(rating, str):
            try:
                review["rating"] = float(rating)
            except Exception:
                review["rating"] = None
        review.setdefault("id", self._build_review_id(review))
        return review

    def _build_review_id(self, review: Dict[str, Any]) -> str:
        """
        生成评论唯一标识（当页面未提供原生 ID 时）。

        输入：
        - review: 评论 dict

        输出：
        - review_id: str
        """
        base = "|".join(
            [
                str(review.get("author") or ""),
                str(review.get("date") or ""),
                str(review.get("rating") or ""),
                str(review.get("title") or ""),
                str(review.get("text") or ""),
            ]
        ).strip()
        if not base:
            return "UNKNOWN"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

    def _fallback_extract_reviews_via_json(
        self, url: str, actions: List[Dict[str, Any]], proxy: str, source_html: str
    ) -> List[Dict[str, Any]]:
        """
        使用 Firecrawl 的 json format 做结构化抽取（当 markdown/html 解析失败时兜底）。

        输入：
        - url: 评论页 URL
        - actions: 浏览器 actions
        - proxy: Firecrawl proxy 选项

        输出：
        - reviews: List[Dict[str, Any]]
        """
        if self.app is None:
            return []

        if not source_html or ("data-hook=\"review\"" not in source_html and "out of 5 stars" not in source_html):
            return []

        schema = {
            "type": "object",
            "properties": {
                "product_title": {"type": "string"},
                "reviews": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rating": {"type": "number"},
                            "date": {"type": "string"},
                            "verified": {"type": "boolean"},
                            "helpful": {"type": "number"},
                            "title": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
            },
            "required": ["reviews"],
        }

        prompt = (
            "Extract Amazon product reviews from the page content. "
            "Do NOT fabricate. If reviews are not present in the page content, return {\"reviews\": []}. "
            "Return product_title and reviews. Each review must include: rating (number 1-5), date (string), "
            "verified (boolean), helpful (number), title (string), text (string)."
        )

        try:
            result = self.app.scrape_url(
                url,
                formats=[
                    {"type": "json", "prompt": prompt, "schema": schema},
                ],
                actions=actions,
                only_main_content=False,
                proxy=proxy,
                mobile=os.getenv("FIRECRAWL_MOBILE", "1") not in {"0", "false", "False"},
            )
        except Exception:
            return []

        data = getattr(result, "json", None)
        if not isinstance(data, dict):
            if isinstance(result, dict):
                data = result.get("json") or (result.get("data") or {}).get("json")
        if not isinstance(data, dict):
            return []

        product_title = str(data.get("product_title") or "").strip()
        reviews = data.get("reviews") or []
        if not isinstance(reviews, list):
            return []
        out: List[Dict[str, Any]] = []
        for r in reviews:
            if not isinstance(r, dict):
                continue
            rr = dict(r)
            if product_title:
                rr.setdefault("product_title", product_title)
            out.append(rr)
        return out

if __name__ == "__main__":
    scraper = AmazonReviewScraper()
    asin = os.getenv("DEMO_ASIN", "B07R4Z3MX7")
    try:
        reviews = scraper.scrape_reviews(asin, max_reviews=5)
        print(reviews)
        print(f"reviews_count={len(reviews)}")
    except Exception as e:
        print(f"scrape_failed: {e}")
