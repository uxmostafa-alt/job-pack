"""Fetch fresh product design roles (UAE, KSA and remote) from public job feeds and render docs/index.html.

Standard library only. No LLM calls. Run: python3 fetch.py
"""
import concurrent.futures as cf
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
CAIRO = ZoneInfo("Africa/Cairo")
NOW = datetime.now(timezone.utc)
# Roles older than a week are not worth applying to; the page filters further to 3 days or today.
MAX_AGE = timedelta(days=7)
UA = {"User-Agent": "job-pack/1.0 (personal job digest; github.com/uxmostafa-alt/job-pack)"}
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

# Cron strings in .github/workflows/refresh.yml, keyed by Cairo UTC offset in hours.
SCHEDULES = {3: "40 4,8,12,16 * * *", 2: "40 5,9,13,17 * * *"}

# ---------- filters ----------

TITLE_NEED = re.compile(r"designer|design lead|lead,? design|product design\b", re.I)
TITLE_AREA = re.compile(r"\b(product|ux|ui|user experience|experience|service|user interface|interaction|ai|conversational|design systems?)\b", re.I)
TITLE_BLOCK = re.compile(
    r"\b(junior|jr\.?|intern|internship|graduate|trainee|entry|graphic|motion|interior|fashion|industrial|"
    r"mechanical|civil|architect|architectural|landscape|game|level|instructional|packaging|print|jewel\w*|"
    r"textile|hardware|electrical|structural|sound|3d|merchandis\w*|head|director|vp|vice president|"
    r"manager|engineer|developer|researcher|copywriter|content designer|marketing|brand|video|illustrat\w*|"
    r"freelance|contract(or)?|part[- ]time|tutor|trainer|annotat\w*|"
    r"nationals?|tamheer|emirati|saudi(zation|isation)|locali[sz]ation program)\b",
    re.I,
)
AI_TITLE = re.compile(r"\b(ai|ml|genai|llm|conversational|machine learning|agentic)\b", re.I)
SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|staff|principal)\b", re.I)

COUNTRY = {
    "AE": r"united arab emirates|\buae\b|dubai|abu dhabi|sharjah|ajman|ras al[- ]khaimah|fujairah|al ain|umm al[- ]quwain",
    "SA": r"saudi|\bksa\b|riyadh|jeddah|jiddah|dammam|khobar|dhahran|mecca|makkah|medina|madinah|\bneom\b|tabuk|jubail",
}
COUNTRY_RE = {k: re.compile(v, re.I) for k, v in COUNTRY.items()}
CODES = {"ae": "AE", "are": "AE", "sa": "SA", "sau": "SA"}
REMOTE_WORD = re.compile(r"\b(remote|anywhere|worldwide|global|distributed|work from home|wfh|fully remote)\b", re.I)
REMOTE_OK = re.compile(r"\b(anywhere|worldwide|global|emea|mena|middle east|gcc|international)\b", re.I)
FILLER = re.compile(r"\b(remote|fully|first|friendly|only|work from home|wfh|hybrid|location|locations|timezone|time zone|tz|or|and|in|the|of)\b|[\s,;:/|()\-–—+&.]+", re.I)


def classify_place(text, country_code=None, remote=False):
    """Return (region, label) where region is AE, SA, REMOTE, or None when the role does not fit."""
    text = (text or "").strip()
    code = CODES.get((country_code or "").lower())
    for region, rx in COUNTRY_RE.items():
        if rx.search(text):
            return region, text
    if code:
        return code, text or code
    if remote or REMOTE_WORD.search(text) or not text:
        if REMOTE_OK.search(text):
            return "REMOTE", text if text else "Remote"
        leftover = FILLER.sub("", text)
        if not leftover:
            return "REMOTE", "Remote, region not stated"
    return None, text


def title_fits(title):
    t = title or ""
    return bool(TITLE_NEED.search(t) and TITLE_AREA.search(t) and not TITLE_BLOCK.search(t))


TAGS = [
    ("Arabic/RTL", re.compile(r"\barabic\b|\brtl\b|right-to-left|bilingual", re.I)),
    ("AI", re.compile(r"\b(ai|llm|genai|generative|machine learning|agentic)\b", re.I)),
    ("Design system", re.compile(r"design systems?", re.I)),
    ("Gov/Enterprise", re.compile(r"\b(government|public sector|enterprise|b2b)\b", re.I)),
    ("Fintech", re.compile(r"\b(fintech|payments?|banking|lending)\b", re.I)),
]


def fit(job, text):
    tags = [name for name, rx in TAGS if rx.search(text or "")]
    score = len(tags)
    score += {"AE": 3, "SA": 2, "REMOTE": 1}.get(job["region"], 0)
    score += 2 if SENIOR_TITLE.search(job["title"]) else 0
    score += 2 if AI_TITLE.search(job["title"]) else 0
    return tags, score


# ---------- helpers ----------

def get(url, data=None):
    req = urllib.request.Request(url, headers=UA, data=data)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def get_json(url):
    return json.loads(get(url))


def to_dt(value):
    """Parse ISO strings, RFC 822 strings, or epoch seconds/milliseconds into aware UTC datetimes."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        s = str(value).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        if re.match(r"\d{4}-\d{2}-\d{2}T", s):
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def money(lo, hi, cur="", period=""):
    def f(n):
        n = float(n)
        return f"{n/1000:.0f}K" if n >= 1000 else f"{n:g}"
    if not lo and not hi:
        return None
    rng = f"{f(lo)}–{f(hi)}" if lo and hi and lo != hi else f(lo or hi)
    return " ".join(x for x in [cur or "", rng, f"/{period}" if period else ""] if x).replace(" /", "/")


def job(source, board, jid, title, company, url, place, posted, salary=None, text=""):
    region, label = place
    return {
        "id": f"{source}:{jid}", "board": board, "source": source, "title": title.strip(), "company": company.strip(),
        "url": url, "region": region, "location": label, "posted": posted.isoformat() if posted else None,
        "salary": salary, "_text": text,
    }


# ---------- company ATS boards ----------

def greenhouse(slug):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        offices = " / ".join(o.get("name", "") for o in j.get("offices") or [])
        loc = (j.get("location") or {}).get("name", "")
        yield job("greenhouse", f"greenhouse:{slug}", j["id"], j["title"], j.get("company_name") or slug,
                  j["absolute_url"], classify_place(f"{loc} {offices}".strip()),
                  to_dt(j.get("first_published")), text=strip_html(j.get("content")))


def lever(slug):
    for j in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        c = j.get("categories") or {}
        loc = " / ".join(c.get("allLocations") or [c.get("location") or ""])
        sr = j.get("salaryRange") or {}
        sal = money(sr.get("min"), sr.get("max"), sr.get("currency", ""), (sr.get("interval") or "").replace("per-", ""))
        remote = j.get("workplaceType") == "remote"
        yield job("lever", f"lever:{slug}", j["id"], j["text"], slug, j["hostedUrl"],
                  classify_place(loc, j.get("country"), remote), to_dt(j.get("createdAt")), sal,
                  j.get("descriptionPlain", "") + " " + j.get("additionalPlain", ""))


def ashby(slug):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        sec = " / ".join(s.get("location", "") for s in j.get("secondaryLocations") or [])
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        loc = " / ".join(x for x in [j.get("location", ""), sec, country] if x)
        comp = j.get("compensation") or {}
        sal = comp.get("scrapeableCompensationSalarySummary") if j.get("shouldDisplayCompensationOnJobPostings", True) else None
        yield job("ashby", f"ashby:{slug}", j["id"], j["title"], slug, j["jobUrl"],
                  classify_place(loc, None, j.get("isRemote")), to_dt(j.get("publishedAt")), sal, j.get("descriptionPlain", ""))


def workable(slug):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    company = d.get("name") or slug
    for j in d.get("jobs", []):
        locs = " / ".join(", ".join(x for x in [l.get("city"), l.get("country")] if x) for l in j.get("locations") or [])
        loc = locs or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        yield job("workable", f"workable:{slug}", j["shortcode"], j["title"], company, j["url"],
                  classify_place(loc, None, j.get("telecommuting")), to_dt(j.get("published_on")))


def recruitee(slug):
    d = get_json(f"https://{slug}.recruitee.com/api/offers/")
    for j in d.get("offers", []):
        s = j.get("salary") or {}
        sal = money(s.get("min"), s.get("max"), s.get("currency", ""), s.get("period", ""))
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        yield job("recruitee", f"recruitee:{slug}", j["id"], j["title"], j.get("company_name") or slug, j["careers_url"],
                  classify_place(loc, j.get("country_code"), j.get("remote")), to_dt(j.get("published_at")), sal,
                  strip_html(j.get("description")))


def smartrecruiters(company_id):
    for country in ("ae", "sa"):
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100&country={country}")
        for j in d.get("content", []):
            loc = j.get("location") or {}
            yield job("smartrecruiters", f"smartrecruiters:{company_id}", j["id"], j["name"],
                      (j.get("company") or {}).get("name") or company_id,
                      f"https://jobs.smartrecruiters.com/{company_id}/{j['id']}",
                      classify_place(loc.get("fullLocation") or loc.get("city", ""), loc.get("country"), loc.get("remote")),
                      to_dt(j.get("releasedDate")))


ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable, "recruitee": recruitee,
       "smartrecruiters": smartrecruiters}


LI_CARD = re.compile(r"<li>(.*?)</li>", re.S)


def li_field(pattern, card):
    m = re.search(pattern, card, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def linkedin(_):
    """LinkedIn's public job search (no login), past week, UAE and KSA only.

    Sequential and slow on purpose: about 24 small requests per run. If LinkedIn refuses a run,
    the feed is marked failed and the last good LinkedIn roles stay until the next run.
    """
    for place in ("United Arab Emirates", "Saudi Arabia"):
        for q in ("product designer", "ux designer", "ui ux designer", "experience designer"):
            for start in (0, 10, 20):
                url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                       + urllib.parse.urlencode({"keywords": q, "location": place, "f_TPR": "r604800", "start": start}))
                req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "en"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    cards = LI_CARD.findall(r.read().decode("utf-8", "replace"))
                for c in cards:
                    jid = li_field(r'data-entity-urn="urn:li:jobPosting:(\d+)"', c)
                    link = li_field(r'base-card__full-link[^>]*href="([^"]+)"', c).split("?")[0]
                    title = li_field(r'base-search-card__title">(.*?)</h3>', c)
                    if not (jid and link and title):
                        continue
                    company = re.sub(r"<[^>]+>", "", li_field(r'base-search-card__subtitle">(.*?)</h4>', c)).strip()
                    loc = li_field(r'job-search-card__location">(.*?)</span>', c)
                    salary = li_field(r'job-search-card__salary-info">(.*?)</span>', c) or None
                    yield job("linkedin", "linkedin", jid, title, company, link, classify_place(loc),
                              to_dt(li_field(r'datetime="(\d{4}-\d{2}-\d{2})"', c)), salary)
                if len(cards) < 10:
                    break
                time.sleep(2)


def workable_search(_):
    """Workable's public job search across all its customers; many UAE and KSA startups hire through Workable."""
    for place in ("United Arab Emirates", "Saudi Arabia"):
        for q in ("product designer", "ux designer", "ui designer"):
            token = ""
            for _page in range(3):
                url = (f"https://jobs.workable.com/api/v1/jobs?query={urllib.parse.quote(q)}"
                       f"&location={urllib.parse.quote(place)}" + (f"&pageToken={urllib.parse.quote(token)}" if token else ""))
                d = get_json(url)
                for j in d.get("jobs", []):
                    if j.get("state") not in (None, "published"):
                        continue
                    loc = j.get("location") or {}
                    label = ", ".join(x for x in [loc.get("city"), loc.get("countryName")] if x)
                    company = (j.get("company") or {}).get("title", "")
                    yield job("workable", "workable-search", j["id"], j["title"], company, j["url"],
                              classify_place(label, None, j.get("workplace") == "remote"), to_dt(j.get("created")), None,
                              strip_html(" ".join(str(j.get(k) or "") for k in ("description", "requirementsSection"))))
                token = d.get("nextPageToken")
                if not token:
                    break

# ---------- remote job boards (credited on the page, as their terms ask) ----------

def remotive(_):
    for q in ("designer", "ux"):
        for j in get_json(f"https://remotive.com/api/remote-jobs?search={q}")["jobs"]:
            yield job("remotive", "remotive", j["id"], j["title"], j["company_name"], j["url"],
                      classify_place(j.get("candidate_required_location"), None, True),
                      to_dt(j.get("publication_date")), j.get("salary") or None, strip_html(j.get("description")))


def remoteok(_):
    for j in get_json("https://remoteok.com/api?tag=design")[1:]:
        sal = money(j.get("salary_min"), j.get("salary_max"), "$", "yr")
        yield job("remoteok", "remoteok", j["id"], j["position"], j["company"], j["url"],
                  classify_place(j.get("location"), None, True), to_dt(j.get("date")), sal, strip_html(j.get("description")))


def himalayas(_):
    for q in ("product%20designer", "ux%20designer", "ui%20designer"):
        for j in get_json(f"https://himalayas.app/jobs/api/search?q={q}&sort=recent")["jobs"]:
            restr = j.get("locationRestrictions") or []
            place = classify_place(" / ".join(restr) or "Worldwide", None, True)
            sal = money(j.get("minSalary"), j.get("maxSalary"), j.get("currency", ""), "yr")
            yield job("himalayas", "himalayas", j["guid"], j["title"], j["companyName"], j["applicationLink"],
                      place, to_dt(j.get("pubDate")), sal, strip_html(j.get("description")))


def jobicy(_):
    for query in ("tag=product%20designer", "tag=ux%20designer", "industry=design-multimedia"):
        for j in get_json(f"https://jobicy.com/api/v2/remote-jobs?count=50&{query}").get("jobs", []):
            sal = money(j.get("annualSalaryMin"), j.get("annualSalaryMax"), j.get("salaryCurrency", ""), "yr")
            yield job("jobicy", "jobicy", j["id"], html.unescape(j["jobTitle"]), html.unescape(j["companyName"]), j["url"],
                      classify_place(j.get("jobGeo"), None, True), to_dt(j.get("pubDate")), sal, strip_html(j.get("jobDescription")))


def wwr(_):
    root = ET.fromstring(get("https://weworkremotely.com/categories/remote-design-jobs.rss"))
    for it in root.iter("item"):
        raw = it.findtext("title") or ""
        company, _, title = raw.partition(": ")
        yield job("wwr", "wwr", it.findtext("guid") or it.findtext("link"), title or raw, company if title else "",
                  it.findtext("link"), classify_place(it.findtext("region"), None, True),
                  to_dt(it.findtext("pubDate")), None, strip_html(it.findtext("description")))


def workingnomads(_):
    for j in get_json("https://www.workingnomads.com/api/exposed_jobs/"):
        yield job("workingnomads", "workingnomads", j["url"], j["title"], j["company_name"], j["url"],
                  classify_place(j.get("location"), None, True), to_dt(j.get("pub_date")), None, strip_html(j.get("description")))


BOARDS = {"linkedin": linkedin, "workable-search": workable_search, "remotive": remotive, "remoteok": remoteok, "himalayas": himalayas, "jobicy": jobicy, "wwr": wwr, "workingnomads": workingnomads}

# ---------- pipeline ----------

def collect(companies):
    tasks = [(f"{ats}:{slug}", ATS[ats], slug) for ats, slug in companies] + [(k, fn, None) for k, fn in BOARDS.items()]

    def run(task):
        key, fn, arg = task
        for _ in range(2):  # big boards sometimes time out under parallel load; one retry
            try:
                return key, list(fn(arg)), None
            except Exception as e:  # one dead feed must not sink the run; it is reported on the page
                err = f"{type(e).__name__}: {e}"[:160]
        return key, [], err

    with cf.ThreadPoolExecutor(24) as ex:
        return list(ex.map(run, tasks))


def keep(j):
    if not j["region"] or not title_fits(j["title"]):
        return False
    if not re.match(r"https?://", j["url"] or ""):
        return False
    posted = to_dt(j["posted"]) or to_dt(j.get("first_seen"))
    return posted is not None and NOW - posted <= MAX_AGE


def dedupe_key(j):
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return norm(j["company"]) + "|" + norm(j["title"])


def company_hash(name):
    """Network companies are stored hashed so the public repo does not list them."""
    norm = re.sub(r"[^a-z0-9]", "", re.sub(r"\|.*", "", name).lower())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def build(results, prev_jobs, seen, network=frozenset()):
    failed = {k for k, _, err in results if err}
    jobs, out, keys = [], [], set()
    for _, items, _ in results:
        jobs += items
    # A feed that failed this run keeps its last good jobs instead of looking closed.
    jobs += [j for j in prev_jobs if j["board"] in failed]
    for j in jobs:
        j["first_seen"] = seen.setdefault(j["id"], j.get("first_seen") or NOW.isoformat())
        if not keep(j):
            continue
        k = dedupe_key(j)
        if k in keys:
            continue
        keys.add(k)
        if "_text" in j:  # carried-over jobs already have their fit fields
            j["tags"], j["fit"] = fit(j, j["title"] + " " + j.pop("_text"))
            j["network"] = company_hash(j["company"]) in network
            j["fit"] += 2 if j["network"] else 0
        out.append(j)
    out.sort(key=lambda j: j["posted"] or j["first_seen"], reverse=True)
    return out


def health(results):
    by_source = {}
    for key, items, err in results:
        src = key.split(":")[0]
        h = by_source.setdefault(src, {"feeds": 0, "failed": 0, "jobs": 0})
        h["feeds"] += 1
        h["failed"] += bool(err)
        h["jobs"] += len(items)
    return by_source


def render(jobs, health_info):
    now_cairo = NOW.astimezone(CAIRO)
    payload = {"generated": NOW.isoformat(), "generated_cairo": now_cairo.strftime("%a %d %b %Y, %H:%M"),
               "health": health_info, "jobs": jobs}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = (ROOT / "template.html").read_text().replace("__DATA__", data)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(page)
    # Same data as the page, for the local recruiter desk (outreach.py) to join against.
    (ROOT / "docs" / "jobs.json").write_text(json.dumps(payload, ensure_ascii=False))
    (ROOT / "docs" / ".nojekyll").write_text("")


def set_output(ran):
    """Tell the workflow whether later steps (commit, deploy) should run."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"ran={'yes' if ran else 'no'}\n")


def main():
    sched = os.environ.get("SCHEDULE")
    offset = int(NOW.astimezone(CAIRO).utcoffset().total_seconds() // 3600)
    if sched and SCHEDULES.get(offset) != sched:
        print(f"Skip: cron '{sched}' does not match Cairo UTC+{offset}")
        set_output(False)
        return 0
    companies = json.loads((ROOT / "companies.json").read_text())
    state = ROOT / "data"
    state.mkdir(exist_ok=True)
    seen = json.loads((state / "seen.json").read_text()) if (state / "seen.json").exists() else {}
    prev = json.loads((state / "jobs.json").read_text()) if (state / "jobs.json").exists() else []
    net_file = ROOT / "network.txt"
    network = frozenset(net_file.read_text().split()) if net_file.exists() else frozenset()
    results = collect(companies)
    jobs = build(results, prev, seen, network)
    cutoff = (NOW - timedelta(days=45)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    (state / "seen.json").write_text(json.dumps(seen, indent=0, sort_keys=True))
    (state / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1))
    h = health(results)
    render(jobs, h)
    regions = {r: sum(j["region"] == r for j in jobs) for r in ("AE", "SA", "REMOTE")}
    print(f"{len(jobs)} jobs {regions}; failed feeds: {sum(v['failed'] for v in h.values())}/{sum(v['feeds'] for v in h.values())}")
    set_output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
