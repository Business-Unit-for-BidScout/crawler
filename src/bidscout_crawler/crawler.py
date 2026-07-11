import hashlib
import random
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from .classifier import classify

BLOCK_WORDS = ("验证码", "访问过于频繁", "安全验证", "请输入验证码", "访问受限", "Access Denied", "Forbidden", "人机验证")
LINK_WORDS = ("采购", "招标", "中标", "成交", "结果", "合同", "询价", "磋商", "比选", "公告", "公示", "意向", "更正", "废标", "流标", "终止", "延期")

@dataclass
class SourceResult:
    source_id: str
    checked: int = 0
    saved: int = 0
    unchanged: int = 0
    blocked: int = 0
    failed: int = 0

def text_from_html(content):
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "nav", "footer"]): node.decompose()
    title = soup.title.get_text(" ", strip=True)[:500] if soup.title else ""
    text = "\n".join(x.strip() for x in soup.get_text("\n").splitlines() if x.strip())
    return title, text[:500000]

def candidate_links(base, html, limit):
    soup = BeautifulSoup(html, "html.parser"); output = []; seen = set(); host = urlparse(base).netloc
    for link in soup.find_all("a", href=True):
        title = " ".join(link.get_text(" ", strip=True).split()); url = urljoin(base, link["href"]); parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc != host or url in seen: continue
        if any(word in title for word in LINK_WORDS):
            seen.add(url); output.append((url, title))
            if len(output) >= limit: break
    return output

class Crawler:
    def __init__(self, storage, user_agent, delay_min=3, delay_max=7, timeout=30):
        self.storage = storage; self.delay_min = delay_min; self.delay_max = max(delay_max, delay_min)
        self.client = httpx.Client(headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}, follow_redirects=True, timeout=timeout)
    def wait(self): time.sleep(random.uniform(self.delay_min, self.delay_max))
    def fetch(self, url):
        response = self.client.get(url)
        if response.status_code in (401, 403, 429): raise PermissionError(f"stop status {response.status_code}")
        response.raise_for_status()
        if any(x.lower() in response.text[:20000].lower() for x in BLOCK_WORDS): raise PermissionError("access-control signal detected")
        return response
    def crawl_source(self, source, max_items=20):
        result = SourceResult(source["id"]); access = source.get("access") or {}
        urls = access.get("list_urls") or ([access.get("homepage_url")] if access.get("homepage_url") else [])
        for list_url in urls:
            try:
                listing = self.fetch(list_url); result.checked += 1
                for url, hint in candidate_links(str(listing.url), listing.content, max_items):
                    try:
                        self.wait(); response = self.fetch(url); raw = response.content; digest = hashlib.sha256(raw).hexdigest()
                        if self.storage.seen_hash(url) == digest: result.unchanged += 1; continue
                        title, text = text_from_html(raw); classification = classify(title or hint, text, source.get("name", source["id"]))
                        self.storage.save(source["id"], url, str(response.url), title or hint, None, raw, text, response.status_code, response.headers.get("content-type", ""), classification)
                        result.saved += 1
                    except PermissionError:
                        result.blocked += 1; return result
                    except Exception:
                        result.failed += 1
            except PermissionError:
                result.blocked += 1; return result
            except Exception:
                result.failed += 1
            self.wait()
        return result
