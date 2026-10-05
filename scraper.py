import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse, urljoin
from collections import Counter

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
MAX_WORKERS = 20
TECHNOLOGIES_FILE = BASE_DIR / "technologies.json"
DOMAINS_FILE = BASE_DIR / (
    "part-00000-66e0628d-2c7f-425a-"
    "8f5b-738bcd6bf198-c000.snappy.parquet"
)
RESULTS_FILE = BASE_DIR / "results.json"

with open(TECHNOLOGIES_FILE, "r", encoding="utf-8") as file:
    technologies = json.load(file)

def known_technologies(script_url, technologies):
    # Comparam URL-ul scriptului cu regulile existente. Daca il recunoastem,
    # nu mai trebuie trimis la cercetare ca un candidat nou.
    for info in technologies.values():
        patterns = info.get("patterns", {}).get("scripts", [])

        for pattern in patterns:
            if re.search(pattern, script_url, re.IGNORECASE):
                return True
    return False

def unknown_technologies(web_data, technologies):
    # Pastram pentru cercetare doar scripturile de pe alte hosturi, pe care
    # regulile actuale nu le recunosc. Un candidat nu este inca o tehnologie confirmata.
    page_url = web_data["url"][0]
    page_host = urlparse(page_url).hostname
    candidates = []

    for script in web_data["scripts"]:
        absolute_url = urljoin(page_url, script)
        script_host = urlparse(absolute_url).hostname

        if not script_host:
            continue

        if script_host == page_host:
            continue

        if known_technologies(absolute_url, technologies):
            continue

        candidates.append({
            "host": script_host,
            "url": absolute_url
        })

    return candidates

def is_html_response(response):
    # Verificam intai tipul declarat de server, apoi inceputul paginii.
    # Unele pagini contin HTML chiar daca headerul lipseste sau este gresit.
    content_type = response.headers.get("Content-Type", "").lower()

    acceptable_types = [
        "text/html",
        "application/xhtml+xml",
    ]

    if any(content_type.startswith(ctype) for ctype in acceptable_types):
        return True

    beginning = response.text[:2000].lower()

    html_indicators = [
        "<html",
        "<!doctype html",
        "<head",
        "<body",
    ]

    return any(indicator in beginning for indicator in html_indicators)


def scrape_website(domain):
    # Pentru domeniile fara protocol incercam HTTPS, apoi HTTP daca prima varianta
    # nu merge. Pastram erorile ambelor incercari daca nu obtinem o pagina HTML.
    if domain.startswith("http://") or domain.startswith("https://"):
        urls = [domain]
    else:
        urls = [
            f"https://{domain}",
            f"http://{domain}"
        ]

    errors = []

    for url in urls:
        try:
            response = requests.get(
                url,
                timeout=10,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/58.0.3029.110 Safari/537.3"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )

            response.raise_for_status()

        except requests.RequestException as error:
            errors.append(f"{url}: {error}")
            continue

        if not is_html_response(response):
            content_type = response.headers.get("Content-Type", "missing")

            errors.append(f"{url}: Not an HTML response (Content-Type: {content_type})")
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        scripts = [
            script["src"]
            for script in soup.find_all("script", src=True)
            if script.get("src")
        ]

        stylesheets = [
            link["href"]
            for link in soup.find_all("link", rel="stylesheet")
            if "stylesheet" in link.get("rel", [])
        ]

        meta_tags = [
            meta["content"]
            for meta in soup.find_all("meta")
            if meta.get("content")
        ]

        header_tags = [
            f"{name}: {value}"
            for name, value in response.headers.items()
        ]

        cookies = [
            f"{name}={value}"
            for name, value in response.cookies.items()
        ]

        # Grupam datele dupa sursa. Toate valorile sunt liste, inclusiv HTML-ul,
        # ca detectorul sa poata parcurge orice sursa cu aceeasi logica.
        return {
            "url": [response.url],
            "scripts": scripts,
            "stylesheets": stylesheets,
            "meta": meta_tags,
            "headers": header_tags,
            "cookies": cookies,
            "html": [response.text]
        }, None

    return None, " | ".join(errors)


def create_evidence(text, match, ctx_size=80):
    # Extragem si textul din jurul potrivirii, ca dovada sa aiba context.
    # Limitam fragmentul la marginile textului si eliminam spatiile in plus.
    start = max(0, match.start() - ctx_size)
    end = min(len(text), match.end() + ctx_size)

    snippet = text[start:end]

    return " ".join(snippet.split())


def detector(web_data, technologies):
    # Pentru fiecare tehnologie parcurgem sursele, regulile si valorile extrase.
    # La prima potrivire salvam dovada si trecem la urmatoarea tehnologie,
    # ca aceeasi tehnologie sa nu apara de mai multe ori pentru un domeniu.
    result = []

    for tech, information in technologies.items():
        patterns_by_source = information.get("patterns", {})
        tech_found = False

        for source, patterns in patterns_by_source.items():
            source_values = web_data.get(source, [])

            for pattern in patterns:
                for value in source_values:
                    match = re.search(pattern, value, re.IGNORECASE)
                    if match:
                        evidence = create_evidence(value, match)
                        result.append({
                            "technology": tech,
                            "category": information.get("category", "Unknown"),
                            "source": source,
                            "pattern": pattern,
                            "evidence": evidence
                        })

                        tech_found = True
                        break

                if tech_found:
                    break
            if tech_found:
                break
    return result


def analyze_domain(domain):
    # Procesam un domeniu complet: descarcam pagina, cautam tehnologiile cunoscute
    # si strangem candidatii. Daca descarcarea esueaza, returnam eroarea in rezultat.
    web_data, error = scrape_website(domain) 

    if error:
        return {
            "domain": domain,
            "status": "failed",
            "technologies": [],
            "error": error
        }

    detected_technologies = detector(web_data, technologies)
    candidates = unknown_technologies(web_data, technologies)

    return {
        "domain": domain,
        "status": "success",
        "technologies": detected_technologies,
        "candidates": candidates,
        "error": None
    }


def main():
    # Pornim de la domeniile unice din Parquet. Dupa procesare, calculam sumarul
    # si salvam atat detectiile, cat si domeniile care au esuat.
    data = pd.read_parquet(DOMAINS_FILE)

    domains = (
        data["root_domain"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    all_results = []
    start_time = perf_counter()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Lansam cererile concurent pentru a nu astepta fiecare site pe rand.
        # Legam fiecare task de domeniul lui si preluam rezultatele pe masura
        # ce sunt gata, astfel incat o eroare sa nu opreasca celelalte domenii.
        future_to_domain = {
            executor.submit(analyze_domain, domain): domain
            for domain in domains
        }

        for future in as_completed(future_to_domain):
            domain = future_to_domain[future]
            try:
                result = future.result()
            except Exception as error:
                result = {
                    "domain": domain,
                    "status": "failed",
                    "error": str(error),
                    "technologies": [],
                    "candidates": []
                }
            all_results.append(result)

    elapsed_time = perf_counter() - start_time

    successful_scrapes = sum(
        result["status"] == "success"
        for result in all_results
    )

    failed_scrapes = sum(
        result["status"] == "failed"
        for result in all_results
    )

    total_detections = sum(
        len(result["technologies"])
        for result in all_results
    )

    # Separam numarul de tehnologii distincte de totalul detectiilor:
    # aceeasi tehnologie poate fi detectata pe mai multe domenii.
    distinct_detections = {
        tech["technology"]
        for result in all_results
        for tech in result.get("technologies", [])
    }

    # Numaram pe cate site-uri apare fiecare host necunoscut, nu cate scripturi
    # are pe un singur site. Asa putem prioritiza candidatii mai raspanditi.
    candidate_counter = Counter()
    for result in all_results:
        hosts = {
            candidate["host"]
            for candidate in result.get("candidates", [])
        }
        candidate_counter.update(hosts)

    output = {
        "summary": {
            "total_domains": len(domains),
            "successful_scrapes": successful_scrapes,
            "failed_scrapes": failed_scrapes,
            "total_detections": total_detections,
            "distinct_technologies": len(distinct_detections),
            "elapsed_time_seconds": round(elapsed_time, 2)
        },
        "candidates": [
            {"host": host, "count": count}
            for host, count in candidate_counter.most_common()
        ],
        "results": all_results
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
