# EGY-CRETE Recruitment Analysis

A Streamlit prototype for testing the first AI-assistant feature: transparent, data-driven recruitment analysis.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run ".\Recrutment app.py" --server.port 8502
```

On Windows, you can also double-click `start_app.bat`. Then open http://localhost:8502.

The prototype includes:

- A catalog of 50+ role options across production, maintenance, quality, engineering, commercial, supply chain, and corporate work
- Role-specific CV keyword matching and missing-signal review
- Independent CV, technical assessment, structured interview, and reference stages
- Weighted 1-5 scoring with written evidence per stage
- Separate human-judgment layer for motivation and role fit
- Candidate shortlist ranking with stage-level scores and salary range
- Salary recommendation using a transparent prototype baseline plus figures from supplied public URLs
- LinkedIn sourcing workflow that generates role-specific searches, exports a review template, and imports recruiter-reviewed leads
- HR-controlled lookup keywords shared by CV scanning and candidate ranking
- Automatic lead ranking using 70% keyword match and 30% experience fit, limited to the first 50 imported records
- Talent sourcing review queue for permitted public lead CSVs and public-page inspection
- 90-day outcome logging to support later model calibration
- Optional workbook upload to inspect an existing `.xlsx` scorecard

The scoring rules are intentionally transparent. CV keyword matching is a screening aid, not an automated rejection mechanism. Public web research must respect robots rules, platform terms, privacy law, and candidate consent; the prototype deliberately does not bypass LinkedIn logins, CAPTCHAs, or scrape protected profiles. LinkedIn results are reviewed manually and imported through the CSV template. A production integration should use an approved LinkedIn partner/API agreement. The later predictive phase should only begin after enough completed hiring outcomes have been collected, with human review and fairness checks kept in the loop.

For automated lead ranking, include `Candidate`, `Profile URL`, and optionally `Headline`, `Years experience`, `CV text`, and `Notes` in the CSV. HR writes the keywords on the Recruitment analysis page; the same list is used by CV evaluation and sourcing. The rank score is `70% keyword score + 30% experience score`, where experience reaches 5/5 at the configured target years.
