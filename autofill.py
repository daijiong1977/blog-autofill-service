"""
autofill.py — Core blog generation logic.

Reads config from environment variables:
  SUPABASE_URL               e.g. https://xxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY  service role JWT
  DEEPSEEK_API_KEY           sk-...

Call run_autofill_en() → generate English posts and insert them into Supabase.
Call run_autofill_cn() → translate existing English posts and update CN fields separately.
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
def call_llm(prompt, max_tokens=1800, system_prompt=None, temperature=0.7):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
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

def parse_llm_json(raw):
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    return json.loads(raw)

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
    return parse_llm_json(raw)

def generate_cn_translation(title, description, content):
    translator_system = """你是一位中英双语的技术专栏编辑，擅长把英文技术评论文章改写成自然、锋利、有网感的简体中文。

你的目标不是逐句直译，而是在不歪曲原意的前提下，写出像中文母语作者亲自写的文章。

必须遵守：
- 保留原文的核心观点、论证顺序、语气强度与具体细节。
- 不要出现翻译腔，不要机械照搬英文句法。
- 标题要像中文技术评论文章标题，准确、自然、有张力，不要硬译。
- 正文按原文段落对应输出，段落数尽量一致。
- 人名、公司名、产品名、协议名、框架名保留英文；必要时可在首次出现时补简短中文说明。
- 专业术语优先使用中文技术社区常见说法；若直译生硬，则保留英文。
- 避免空话、套话和机器翻译常见连接词，如“值得注意的是”“与此同时”“总而言之”，除非语义上确实需要。
- 可以润色句子让中文更顺，但不能删掉关键论点，也不能加入原文没有的新观点。"""

    first_pass_prompt = f"""请将以下英文博客文章改写为高质量的简体中文技术评论文章。

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

    first_pass = parse_llm_json(call_llm(
        first_pass_prompt,
        max_tokens=2500,
        system_prompt=translator_system,
        temperature=0.4,
    ))

    polish_prompt = f"""下面有一篇英文原文，以及一版已经翻成中文的初稿。请你作为中文母语技术编辑，对中文初稿做二次润色。

润色目标：
- 消除翻译腔，让表达更像中文作者直接写作。
- 保留原文的观点、事实、论证关系和语气，不要漏信息，不要擅自发挥。
- 让标题更自然，摘要更凝练，正文更顺畅。
- 保持段落结构清晰，仍然输出为普通段落文本。

英文标题：{title}

英文摘要：{description}

英文正文：
{content}

中文初稿标题：{first_pass.get('title_cn', '')}

中文初稿摘要：{first_pass.get('description_cn', '')}

中文初稿正文：
{first_pass.get('content_cn', '')}

请输出最终润色后的JSON（不要加markdown代码块），格式如下：
{{
  "title_cn": "中文标题",
  "description_cn": "中文摘要（不超过200字）",
  "content_cn": "中文正文段落1\\n\\n中文正文段落2\\n\\n..."
}}"""

    polished = parse_llm_json(call_llm(
        polish_prompt,
        max_tokens=2800,
        system_prompt=translator_system,
        temperature=0.3,
    ))

    return {
        "title_cn": polished.get("title_cn", first_pass.get("title_cn", "")),
        "description_cn": polished.get("description_cn", first_pass.get("description_cn", "")),
        "content_cn": polished.get("content_cn", first_pass.get("content_cn", "")),
    }

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

def insert_post(data, cn_data=None):
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

    cn_data = cn_data or {}

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

def fetch_posts_missing_cn(limit=6):
    query = urllib.parse.urlencode({
        "select": "id,slug,title,description,content",
        "published": "eq.true",
        "or": "(content_cn.is.null,content_cn.eq.)",
        "order": "date.desc",
        "limit": str(limit),
    })
    url = f"{SUPABASE_URL}/rest/v1/posts?{query}"
    req = urllib.request.Request(url, headers=SUPA_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())

def update_post_cn(post_id, cn_data):
    payload = {
        "title_cn": cn_data.get("title_cn", ""),
        "description_cn": cn_data.get("description_cn", "")[:200],
        "content_cn": cn_data.get("content_cn", ""),
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/posts?id=eq.{urllib.parse.quote(str(post_id))}",
        data=body,
        headers={**SUPA_HEADERS, "Prefer": "return=minimal"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=20):
        return None

# ── Main entry point ──────────────────────────────────────────────────────────
def run_autofill_en():
    """Generate English blog posts and insert them into Supabase."""
    results = []
    errors  = []

    for topic, cfg in TOPIC_CONFIG.items():
        articles = gather_sources(topic)

        for i in range(cfg["count"]):
            subset = articles[i * 3 : (i * 3) + 3]
            try:
                print(f"[run_en] generating topic={topic} batch={i+1}", flush=True)
                post_data = generate_post(topic, cfg, subset)
                slug = insert_post(post_data)
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

def run_autofill_cn(limit=6):
    """Translate existing English posts into Chinese and update CN fields only."""
    results = []
    errors = []

    try:
        posts = fetch_posts_missing_cn(limit=limit)
    except Exception as e:
        return {"translated": [], "errors": [{"scope": "fetch_posts_missing_cn", "error": str(e)}]}

    for post in posts:
        try:
            print(f"[run_cn] translating slug={post['slug']}", flush=True)
            cn_data = generate_cn_translation(
                post["title"],
                post["description"],
                post["content"],
            )
            update_post_cn(post["id"], cn_data)
            results.append({
                "id": post["id"],
                "slug": post["slug"],
                "title": post["title"],
                "admin_url": f"{ADMIN_BASE}/admin/posts/{post['slug']}",
            })
            time.sleep(1)
        except Exception as e:
            errors.append({"slug": post.get("slug", "unknown"), "error": str(e)})

    return {"translated": results, "errors": errors}
