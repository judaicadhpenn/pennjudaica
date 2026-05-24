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

def clean_year(date_str):
    """Extracts a 4-digit integer year for timeline sorting."""
    match = re.search(r'\b(1[0-9]{3})\b', str(date_str))
    return int(match.group(1)) if match else 1700

def determine_source(callno, desc):
    """Dynamically categorizes items based on call numbers and descriptions."""
    callno_upper = callno.upper()
    if "KET Z" in callno_upper: return "zucker"
    if "LJS" in callno_upper: return "ljs"
    if "MIKVEH" in callno_upper or "MIKVEH" in desc.upper(): return "mikveh"
    if "HALPER" in callno_upper or "CAJS" in callno_upper or "GENIZAH" in desc.upper(): return "genizah"
    return "other"

def main():
    url = "https://openn.library.upenn.edu/html/judaica_contents.html"
    print(f"Starting master HTML harvest from {url}...", flush=True)
    
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}", flush=True)
        return

    items = []
    current_id = 1
    
    # Split the HTML into readable chunks based on standard line/list breaks
    chunks = re.split(r'</li>|</tr>|<br\s*/?>', response.text, flags=re.IGNORECASE)
    
    for chunk in chunks:
        # Clean HTML tags to get plain text
        text = re.sub(r'<[^>]+>', ' ', chunk).strip()
        text = re.sub(r'\s+', ' ', text) # Normalize spaces
        
        # We only care about chunks that contain standard OPenn record indicators
        if "Browse" not in text or ":" not in text:
            continue
            
        parts = text.split(":", 1)
        if len(parts) < 2:
            continue
            
        callno = parts[0].strip()
        
        if not callno:
            continue
            
        raw_desc = parts[1].split("Browse")[0].strip()
        
        # Extract the year
        year = clean_year(raw_desc)
        
        # Extract the place (usually the first item in parentheses)
        place_match = re.search(r'\(([^,)]+)', raw_desc)
        place = place_match.group(1).strip() if place_match else "Unknown Place"
        
        # Format a clean title
        title = raw_desc.split('.')[0] if '.' in raw_desc else raw_desc.split('(')[0].strip()
        if not title:
            title = f"Document ({callno})"
            
        # Extract the specific href for the "Browse" link
        link_match = re.search(r'href=["\']([^"\']+)["\'][^>]*>\s*Browse', chunk, re.IGNORECASE)
        href = link_match.group(1) if link_match else ""
        
        # Ensure the URL is absolute
        if href.startswith("http"):
            srcUrl = href
        else:
            href_clean = href.lstrip('/')
            srcUrl = f"https://openn.library.upenn.edu/{href_clean}"
            
        source_key = determine_source(callno, raw_desc)
        
        item = {
            "id": current_id,
            "title": title,
            "creator": "Unknown",
            "year": year,
            "dateText": raw_desc,
            "place": place,
            "region": "Global",
            "lat": 0.0,
            "lng": 0.0,
            "lang": "Hebrew",
            "type": "Ketubah" if source_key == "zucker" else "Manuscript",
            "collection": SOURCES[source_key]["label"],
            "source": source_key,
            "iiif": False, 
            # Using a generic fallback thumbnail
            "img": "https://openn.library.upenn.edu/Data/0001/ljs204/data/thumb/0015_0016_thumb.jpg", 
            "srcUrl": srcUrl,
            "callno": callno,
            "desc": raw_desc,
            "pages": []
        }
        items.append(item)
        current_id += 1
        
    print(f"Extracted {len(items)} items from the master list.", flush=True)

    if not items:
        print("No items found. Aborting.", flush=True)
        return

    # Auto-feature the first 4 items
    featured_ids = [it["id"] for it in items[:4]] if len(items) >= 4 else []

    payload = {
        "sources": SOURCES,
        "items": items,
        "featured": featured_ids,
        "harvestedAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    }
    
    output_content = f"""/* ============================================================================
   Penn Judaica Portal — AUTOMATICALLY GENERATED INDEX
   Generated on: {payload['harvestedAt']}
   ============================================================================ */
(function () {{
  window.PJP = {json.dumps(payload, ensure_ascii=False, indent=2)};
}})();
"""
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(output_content)
        
    print(f"Successfully harvested {len(items)} total items and wrote them to data.js!", flush=True)

if __name__ == "__main__":
    main()
