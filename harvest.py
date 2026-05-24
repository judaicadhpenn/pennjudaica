import json
import re
from datetime import datetime
import requests

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
    if "HALPER" in callno_upper or "CAJS" in callno_upper: return "genizah"
    return "other"

def main():
    url = "https://openn.library.upenn.edu/html/judaica_contents.html"
    print(f"Fetching {url}...", flush=True)
    
    try:
        response = requests.get(url, timeout=20)
        response.raise_text = response.text
    except Exception as e:
        print(f"Error: {e}")
        return

    # This regex looks for lines that start with a call number pattern
    # It searches for: CALL_NUM: Description Browse | TEI | Data
    pattern = re.compile(r'([A-Za-z0-9\s]+): (.*?) Browse \|', re.IGNORECASE)
    matches = pattern.findall(response.text)
    
    items = []
    for idx, (callno, desc) in enumerate(matches, start=1):
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
            "srcUrl": "https://openn.library.upenn.edu/",
            "callno": callno.strip(),
            "desc": desc,
            "pages": []
        })

    payload = {"sources": SOURCES, "items": items, "featured": [1, 2, 3, 4], "harvestedAt": datetime.utcnow().isoformat()}
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(f"window.PJP = {json.dumps(payload, indent=2)};")
    print(f"Harvested {len(items)} items.")

if __name__ == "__main__":
    main()
