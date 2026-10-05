# Website Technologies Scraper

This project detects technologies used by websites and provides
evidence for each detection.

I used Python, requests, and BeautifulSoup to fetch and parse pages.
The detection rules are regex patterns stored in technologies.json.

## Installation

Create a virtual environment and install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The supplied Parquet file should be in the same folder as scraper.py.
It needs a root_domain column. Its filename is set in DOMAINS_FILE.

## Running the Scraper

```powershell
.\.venv\Scripts\python.exe scraper.py
```

The scraper processes domains using 20 worker threads and saves the
output in results.json. Detections include the technology name,
category, matched pattern, and evidence. Failed requests include an error.

The summary shows successful and failed scrapes, detection count,
and execution time. The detection count is not the number of unique
technologies, since the same technology can appear on multiple websites.

## Results

In one run on the supplied dataset:
- Input domains: 200
- Successfully scraped: 148
- Failed: 52
- Distinct technologies detected: 26
- Total detections across websites: 445
- Execution time: 42.53 seconds

These results are saved in results.json.
Results may vary between runs because websites and network availability change.

## Finding New Technologies

I also added an experimental script called research.py.
It takes unknown script URLs from the scraper, searches for information
using Tavily, and uses OpenAI to suggest the technology name.

To run it, create a .env file using .env.example as a template and add
your own API keys. These services may charge for usage.

```powershell
.\.venv\Scripts\python.exe research.py
```

Currently, it processes the first five candidates.
It checks the supporting quotes and tests the proposed regex patterns.
Accepted rules are saved in technologies.json after creating a backup.
Research details are saved in research_results.json.

Run scraper.py again to detect technologies using the new rules.

## Main Issues

One problem was detecting Bootstrap just from the word "bootstrap".
This also matched "captcha-bootstrap", which is unrelated to the
Bootstrap framework. I changed the rules to use more specific patterns.

The scraper does not run JavaScript, so it can miss technologies loaded
after the page opens. Some websites also block requests or fail to load.
Using a browser-based tool for some pages could help.

The research part can make mistakes. Finding a script URL in a source
does not always prove which product it belongs to. Passing the regex
checks does not guarantee that the suggested technology is correct.
Rules containing exact versions may also miss other versions.

I checked selected examples manually, but the project does not have
a complete automated test suite.

## Scaling to Millions of Domains

I would split the domains between workers using a task queue and save
results as they finish, so interrupted runs could continue later.
I would add caching, limited retries, and per-host request limits.
I would also respect robots.txt and relevant website restrictions.

Before choosing how many workers to use, I would measure processing
speed and failure rates on a larger sample.

## Future Technology Discovery

The research script is a first attempt at automating this.
I would improve it by caching searches, investigating common unknown
scripts first, and requiring stronger evidence before adding rules.
I would also check new rules against independent examples, not only
the generated URLs.