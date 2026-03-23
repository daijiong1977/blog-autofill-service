"""
autofill.py — Core blog generation logic.

Reads config from environment variables:
  SUPABASE_URL               e.g. https://xxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY  service role JWT
  DEEPSEEK_API_KEY           sk-...

Call run_autofill() → returns list of {topic, title, slug, admin_url}
"""

import json, urllib.request, urllib.error, urllib.parse
import re, os, datetime, time
import xml.etree.ElementTree as ET

# ── Config from env ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://lfknsvavhiqrsasdfyrs.supabase.co")
SERVICE_KEY  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]

ADMIN_BASE = os.environ.get("ADMIN_BASE_URL", "https://daedal-portfolio.vercel.app")

# ── RSS sources ───────────────────────────────────────────────────────────────
TOPIC_SOURCES = {
    "ai": [
        "https://hnrss.org/frontpage?q=AI+machine+learning&count=5",
        "https://hnrss.org/frontpage?q=LLM+GPT&count=5",
        "https://feeds.feedburner.com/venturebeat/SZYF",
    ],
    "tennis": [
        "https://www.espn.com/espn/rss/tennis/news",
        "https://feeds.bbci.co.uk/sport/tennis/rss.xml",
        "https://news.google.com/rss/search?q=tennis+ATP+WTA&hl=en-US&gl=US&ceid=US:en",
    ],
    "news": [
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://hnrss.org/frontpage?count=8",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    ],
}

TOPIC_CONFIG = {
    "ai": {
        "count": 2,
        "persona": "software engineer specialising in distributed systems and AI/ML tooling",
        "blog_style": "technical analysis with real-world engineering perspective",
    },
    "tennis": {
        "count": 2,
        "persona": "software engineer who follows the ATP/WTA tour closely and loves the sport",
        "blog_style": "thoughtful commentary mixing technical insight with sports analysis",
    },
    "news": {
        "count": 2,
        "persona": "software engineer commenting on tech industry news and its implications for developers",
        "blog_style": "opinionated takes on news, grounded in engineering experience",
    },
}

# ── RSS helpers ───────────────────────────────────────────────────────────────
def fetch_rss(url, max_items=4):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 blog-autofill/2.0"
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            desc  = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()[:400]
            link  = item.findtext("link", "").strip()
            if title and len(title) > 5:
                items.append({"title": title, "description": desc, "url": link})
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []

def gather_sources(topic):
    articles = []
    for url in TOPIC_SOURCES[topic]:
        articles.extend(fetch_rss(url, max_items=3))
        if len(articles) >= 6:
            break
    return articles[:6]

# ── DeepSeek (OpenAI-compatible) ─────────────────────────────────────────────
def call_llm(prompt, max_tokens=1800):
    body = json.dumps({
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]

def generate_post(topic, cfg, articles):
    sources_text = "\n".join(
        f"- [{a['title']}]({a['url']})\n  {a['description']}"
        for a in articles
    ) or "(no recent articles — write from current knowledge)"

    prompt = f"""You are a {cfg['persona']} writing for your personal portfolio blog at daedal.dev.

Here are recent articles/discussions on "{topic}":
{sources_text}

Write an original blog post ({cfg['blog_style']}) that:
- Has a compelling, specific title (opinionated, not generic)
- Is 500-750 words of actual content
- Expresses YOUR own analysis and opinions, not just a summary
- Uses a conversational but expert voice — direct, no fluff
- Plain paragraphs separated by blank lines (no markdown # headers)
- Ends with a concrete takeaway or open question

Respond ONLY with valid JSON (no markdown fences), exactly this shape:
{{
  "title": "...",
  "description": "One compelling sentence, max 160 chars",
  "content": "Paragraph 1.\\n\\nParagraph 2.\\n\\nParagraph 3....",
  "tags": ["tag1", "tag2", "tag3"],
  "reading_time": "X min read"
}}"""

    raw = call_llm(prompt)
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    return json.loads(raw)

def generate_cn_translation(title, description, content):
    prompt = f"""请将以下英文博客文章翻译成地道的中文（简体）。保持原有的语气和风格，专业术语可保留英文或标注中文。

英文标题：{title}

英文摘要：{description}

英文正文（段落以空行分隔）：
{content}

请以JSON格式返回（不要加markdown代码块），格式如下：
{{
  "title_cn": "中文标题",
  "description_cn": "中文摘要（不超过200字）",
  "content_cn": "中文正文段落1\\n\\n中文正文段落2\\n\\n..."
}}"""
    raw = call_llm(prompt, max_tokens=2500)
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    return json.loads(raw)

# ── Supabase helpers ──────────────────────────────────────────────────────────
SUPA_HEADERS = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

def slugify(title):
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s)
    return s[:80].rstrip("-")

def slug_exists(slug):
    url = f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{urllib.parse.quote(slug)}&select=slug"
    req = urllib.request.Request(url, headers=SUPA_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return len(json.loads(resp.read())) > 0

def insert_post(data, cn_data):
    slug = slugify(data["title"])
    base_slug, suffix = slug, 1
    while True:
        try:
            if not slug_exists(slug):
                break
        except Exception:
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    payload = {
        "slug":           slug,
        "title":          data["title"],
        "title_cn":       cn_data.get("title_cn", ""),
        "description":    data["description"][:200],
        "description_cn": cn_data.get("description_cn", "")[:200],
        "content":        data["content"],
        "content_cn":     cn_data.get("content_cn", ""),
        "tags":           data.get("tags", []),
        "date":           datetime.date.today().isoformat(),
        "reading_time":   data.get("reading_time", "5 min read"),
        "published":      True,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/posts",
        data=body,
        headers=SUPA_HEADERS,
    )
    with urllib.request.urlopen(req) as resp:
        json.loads(resp.read())
    return slug

# ── Main entry point ──────────────────────────────────────────────────────────
def run_autofill():
    """Generate 6 draft blog posts and insert into Supabase. Returns results list."""
    results = []
    errors  = []

    for topic, cfg in TOPIC_CONFIG.items():
        articles = gather_sources(topic)

        for i in range(cfg["count"]):
            subset = articles[i * 3 : (i * 3) + 3]
            try:
                post_data = generate_post(topic, cfg, subset)
                cn_data = generate_cn_translation(
                    post_data["title"],
                    post_data["description"],
                    post_data["content"],
                )
                slug = insert_post(post_data, cn_data)
                results.append({
                    "topic":     topic,
                    "title":     post_data["title"],
                    "slug":      slug,
                    "admin_url": f"{ADMIN_BASE}/admin/posts/{slug}",
                })
                time.sleep(1)
            except Exception as e:
                errors.append({"topic": topic, "error": str(e)})

    return {"created": results, "errors": errors}
