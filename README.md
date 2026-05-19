# Vega Contact Enrichment
Enriches raw contractor contact lists with company size estimates, revenue ranges, website detection, and outreach priority scoring.

## Enrichment fields added
- **Company Size Est** — Small / Small–Medium / Medium–Large
- **Est Annual Revenue** — based on trade type + license age
- **Website Likelihood** — Likely / Possible / Unlikely
- **Likely Domain** — best-guess domain from company name
- **New License** — flags top 15% newest licenses
- **Target Priority** — High / Medium / Lower for Vega outreach

## Usage
```bash
pip install pandas requests beautifulsoup4
python enrich_fast.py
```
