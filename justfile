# Property Pipeline — Kraków
# Run with: just <recipe>
# Pass ts=1 to any recipe to save output to a timestamped file instead of output.jsonl
# e.g.  just scrape-otodom-1 ts=1

set shell := ["powershell", "-Command"]

# Scrape first page of Otodom only (quick test / preview)
scrape-otodom-1 ts="":
    $out = if ("{{ts}}" -ne "") { "output_otodom_$(Get-Date -Format 'yyyyMMdd_HHmmss').jsonl" } else { "output.jsonl" }; cd scrapy_project; poetry run scrapy crawl otodom -a max_pages=1 -O ../scrapy_project/$out

# Scrape first page of Otodom — dom (house) listings
scrape-otodom-dom-1 ts="":
    $out = if ("{{ts}}" -ne "") { "output_otodom_dom_$(Get-Date -Format 'yyyyMMdd_HHmmss').jsonl" } else { "output_dom.jsonl" }; cd scrapy_project; poetry run scrapy crawl otodom -a max_pages=1 -a property_type=dom -O ../scrapy_project/$out
