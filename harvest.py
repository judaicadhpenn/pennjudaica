import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Define collection mapping
SOURCES = {
    "zucker":  {"label": "Zucker Ketubah Collection", "system": "OPenn", "color": "#a8492b"},
    "ljs":     {"label": "Schoenberg Manuscripts",    "system": "OPenn", "color": "#6e7637"},
    "mikveh":  {"label": "Mikveh Israel Records",     "system": "OPenn", "color": "#6a4a7c"},
    "genizah": {"label": "Cairo Genizah (CAJS)",      "system": "OPenn", "color": "#2f6d6a"},
    "other":   {"label": "Penn Special Collections",  "system": "OPenn", "color": "#1d3b6a"}
}

def determine_source(callno, desc):
    callno_upper = callno.upper()
    if "KET Z" in callno_upper: return "zucker"
    if "LJS" in callno_upper: return "ljs"
    if "MIKVEH" in callno_upper or "MIKVEH" in desc.upper(): return "mikveh"
    if "HALPER" in callno_upper or "CAJS" in callno_upper or "GENIZAH" in desc.upper(): return "genizah"
    return "other"

def main():
    url = "https://openn.library.upenn.edu/html/judaica_contents.html"
    print(f"Fetching {url}...", flush=True)
    
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching page: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    items = []
    
    # CRITICAL CHANGE: We find every 'a' tag that contains the word "Browse"
    # This is the anchor for every record, regardless of HTML structure.
    browse_links = soup.find_all('a', string=re.compile(r'Browse', re.IGNORECASE))
    
    print(f"Found {len(browse_links)} 'Browse' links. Processing...", flush=True)

    for idx, link in enumerate(browse_links, start=1):
        # We look at the text block immediately preceding the link
        # This is where the "KET Z1: Ketubah..." string is located.
        # We navigate backwards through the HTML tree to find the text.
        text_content = link.find_previous_sibling(text=True)
        if not text_content:
            text_content = link.parent.get_text()
            
        # Clean up the text
        raw_text = re.sub(r'\s+', ' ', text_content).strip()
        
        # We only care about lines with a colon separator
        if ":" not in raw_text:
            continue
            
        parts = raw_text.split(":", 1)
        callno = parts[0].strip()
        desc = parts[1].split("|")[0].strip() # Cleanup extraneous browser text
        
        source_key = determine_source(callno, desc)
        
        items.append({
            "id": idx,
            "title": desc.split(',')[0].strip(),
            "creator": "Unknown",
            "year": 1800, # Default year
            "dateText": desc,
            "place": "Unknown",
            "region": "Global",
            "lat": 0.0, "lng": 0.0,
            "lang": "Hebrew",
            "type": "Manuscript",
            "collection": SOURCES[source_key]["label"],
            "source": source_key,
            "iiif": False,
            "img": "https://openn.library.upenn.edu/Data/0001/ljs204/data/thumb/0015_0016_thumb.jpg",
            "srcUrl": link.get('href', "https://openn.library.upenn.edu/"),
            "callno": callno,
            "desc": desc,
            "pages": []
        })

    print(f"DEBUG: Successfully processed {len(items)} items.", flush=True)

    payload = {"sources": SOURCES, "items": items, "featured": [1, 2, 3, 4], "harvestedAt": datetime.utcnow().isoformat()}
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(f"window.PJP = {json.dumps(payload, indent=2)};")
    print("Done writing data.js")

if __name__ == "__main__":
    main()
