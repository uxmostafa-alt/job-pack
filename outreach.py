"""Build outreach.local.html: recruiters from your LinkedIn export, matched to companies hiring on the job page.

Local only. The output holds names and profile links, so it is gitignored (*.local.*) and never published.
Run: python3 outreach.py [path/to/linkedin_dashboard_clean.html]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Downloads" / "linkedin_dashboard_clean.html")
PAGE_URL = "https://uxmostafa-alt.github.io/job-pack/jobs.json"


def main():
    if not SRC.exists():
        sys.exit(f"LinkedIn dashboard not found: {SRC}")
    m = re.search(r'id="ldb-data"[^>]*>(.*?)</script>', SRC.read_text(encoding="utf-8"), re.S)
    if not m:
        sys.exit("No ldb-data block in the dashboard file; was it exported from a different tool?")
    people = json.loads(m.group(1))["people"]
    # Recruiters always show; everyone else shows only when their company is hiring on the page.
    order = ("RECRUIT", "AGENCY", "HIRE", "REFER", "INTRO", "CLIENT")
    recruiters = []
    for p in people:
        kinds = sorted((k for k in p.get("ty") or [] if k in order), key=order.index)
        if not kinds or not p.get("n"):
            continue
        email = p.get("e") if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", str(p.get("e") or ""), re.I) else None
        url = p.get("u") if re.match(r"https://(www\.)?linkedin\.com/", str(p.get("u") or "")) else None
        recruiters.append({"name": p["n"], "title": p.get("t") or "", "company": p.get("c") or "", "region": p.get("rg") or "",
                           "strength": p.get("s") or 0, "kind": kinds[0], "url": url, "email": email})
    snapshot = ROOT / "docs" / "jobs.json"
    jobs = json.loads(snapshot.read_text()) if snapshot.exists() else {"jobs": []}
    data = json.dumps({"recruiters": recruiters, "snapshot": jobs, "live": PAGE_URL}, ensure_ascii=False).replace("</", "<\\/")
    out = ROOT / "outreach.local.html"
    out.write_text((ROOT / "outreach_template.html").read_text().replace("__DATA__", data))
    print(f"{len(recruiters)} people written to {out}")


if __name__ == "__main__":
    main()
