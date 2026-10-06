# Job Pack

Senior product design roles in the UAE, Saudi Arabia, the wider GCC, and remote roles open worldwide or to EMEA/MENA.

- `fetch.py` reads public job feeds (company Greenhouse, Lever, Ashby, Workable and Recruitee boards, plus Remotive, Remote OK, Himalayas, Jobicy, We Work Remotely and Working Nomads), filters by title, place and age, and renders `docs/index.html`. Standard library only, no LLM calls.
- `.github/workflows/refresh.yml` runs it at 07:40 and 19:40 Africa/Cairo so the page is fresh by 08:00 and 20:00.
- A role drops when it disappears from its source feed (closed) or passes the age cap (90 days for company boards, 30 for remote boards).
- `companies.json` lists the boards to read. Add a line to cover a new company.
