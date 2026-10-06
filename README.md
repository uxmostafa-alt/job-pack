# Job Pack

Senior product design roles in two tabs: Gulf (UAE and Saudi Arabia only) and Remote (open worldwide or to EMEA/MENA).

- `fetch.py` reads public job feeds (company Greenhouse, Lever, Ashby, Workable and Recruitee boards, plus LinkedIn public job search (UAE, KSA, no login), SmartRecruiters, Remotive, Remote OK, Himalayas, Jobicy, We Work Remotely and Working Nomads), filters by title, place and age, and renders `docs/index.html`. Standard library only, no LLM calls.
- `.github/workflows/refresh.yml` runs it at 07:40, 11:40, 15:40 and 19:40 Africa/Cairo.
- A role drops when it disappears from its source feed (closed) or is older than 7 days.
- `companies.json` lists the boards to read. Add a line to cover a new company.
