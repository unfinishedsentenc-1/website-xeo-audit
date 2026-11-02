# Website audit

A tool that audits a website and up to five competitors in three areas.

- **Google search** (SEO)
- **AI answers** (AEO)
- **AI trust** (GEO)

It crawls each site, scores every page and the whole site from 0 to 100, and
lists what to fix with numbered steps a non-expert can follow.

No company names live in this code. You enter every site in the tool's form.

## What is here

| Folder | What it holds |
| --- | --- |
| `audit/` | The crawler, the checks, the scores and the fix library |
| `config/settings.json` | Every threshold and weight. Change a number and the next audit uses it |
| `tests/` | A small practice website and tests that prove each check works |

## How scoring works

- Each check is weighted high (3), medium (2) or low (1).
- A page's score in an area is the points it earned divided by the points possible. Checks that do not apply to a page are left out.
- The site's score in an area is 80 percent the average page score and 20 percent the site-level checks, such as robots.txt and the sitemap.
- The overall score is the average of the three areas.

## Run it on your own computer

```bash
pip install -r requirements.txt
python -m audit.run --site yoursite.com --brand "Your brand" --competitor rival.com --out results/audit.json
```

## Run the tests

```bash
python -m unittest discover -s tests -t .
```

## Privacy

Results are never saved here in plain form. The `results/` folder is ignored
by git. Later stages encrypt each audit before it is stored.

## Polite crawling

The crawler reads robots.txt and skips anything it disallows. It waits one
second between requests, or longer if the site asks. When a site blocks it,
the audit says so and does not try to get around the block.
