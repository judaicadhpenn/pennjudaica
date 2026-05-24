import json
import re
from datetime import datetime
import requests

OP_BASE = "https://openn.library.upenn.edu"

# OPenn Collection Directory IDs mapped to the Judaica Portal
COLLECTIONS = {
    "0051": {"key": "zucker",  "label": "Zucker Ketubah Collection", "system": "OPenn", "color": "#a8492b"},
    "0001": {"key": "ljs",     "label": "Schoenberg Manuscripts",    "system": "OPenn", "color": "#6e7637"},
    "0039": {"key": "mikveh",  "label": "Mikveh Israel Records",     "system": "OPenn", "color": "#6a4a7c"},
    "0002": {"key": "genizah", "label": "Cairo Genizah (CAJS)",      "system": "OPenn", "color": "#2f6d6a"}
}

def clean_year(date_str):
    """Extracts a 4-digit integer year for timeline sorting."""
    if not date_str:
        return 1700
    match = re.search(r"\b(1[0-9]{3})\b", str(date_str))
    return int(match.group(1)) if match else 1700

def get_value_from_iiif_metadata(metadata_list, target_key):
    """Safely extracts a value from the IIIF manifest metadata array."""
    for item in metadata_list:
        label = item.get("label", "")
        if isinstance(label, list): 
            label = label[0]
        if isinstance(label, dict):
            label = label.get("@value", "")
            
        if label.lower() == target_key.lower():
            val = item.get("value", "")
            if isinstance(val, list):
                val = val[0]
            if isinstance(val, dict):
                return val.get("@value", "")
            return str(val)
    return "Unknown"

def harvest_collection(coll_id, meta):
    items = []
    print(f"Scraping collection {coll_id}: {meta['label']}...")
    index_url = f"{OP_BASE}/Data/{coll_id}/"
    
    try:
        response = requests.get(index_url, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch {index_url}: {e}")
        return items

    # Scrape the HTML directory listing for subfolders
    folders = re.findall(r'href="([a-zA-Z0-9_]+)/"', response.text)
    
    # Filter out OPenn's structural directories
    ignore_dirs = {'html', 'data', 'csv', 'css', 'js', 'fonts', 'images', 'tei', 'thumbnail', 'web', 'master', 'derivs'}
    item_dirs = [f for f in folders if f.lower() not in ignore_dirs and not f.startswith('?')]
    item_dirs = list(dict.fromkeys(item_dirs)) # Remove duplicates

    print(f"  Found {len(item_dirs)} item folders. Fetching IIIF manifests...")

    for item_id in item_dirs:
        manifest_url = f"{OP_BASE}/Data/{coll_id}/{item_id}/data/manifest.json"
        try:
            m_res = requests.get(manifest_url, timeout=10)
            if m_res.status_code != 200:
                continue
                
            manifest = m_res.json()
            metadata = manifest.get('metadata', [])
            
            # Extract metadata
            title = manifest.get('label', f"Item {item_id}")
            desc = manifest.get('description', "")
            date_text = get_value_from_iiif_metadata(metadata, "date")
            callno = get_value_from_iiif_metadata(metadata, "call number")
            if callno == "Unknown": callno = item_id
            lang = get_value_from_iiif_metadata(metadata, "language")
            place = get_value_from_iiif_metadata(metadata, "origin")

            # Extract IIIF Canvases (Pages and Images)
            pages = []
            sequences = manifest.get('sequences', [])
            if sequences:
                canvases = sequences[0].get('canvases', [])
                for c_idx, canvas in enumerate(canvases):
                    page_label = canvas.get('label', f"Page {c_idx+1}")
                    images = canvas.get('images', [])
                    if images:
                        resource = images[0].get('resource', {})
                        img_url = resource.get('@id', '')
                        
                        # Generate specific resolutions using the IIIF Image API
                        service = resource.get('service', {})
                        if service and '@id' in service:
                            base_id = service['@id']
                            thumb_url = f"{base_id}/full/200,/0/default.jpg"
                            web_url = f"{base_id}/full/800,/0/default.jpg"
                        else:
                            thumb_url = img_url
                            web_url = img_url
                        
                        pages.append({
                            "img": web_url,
                            "thumb": thumb_url,
                            "label": page_label
                        })

            if not pages:
                continue

            items.append({
                "id": f"{coll_id}_{item_id}", # Temporary ID, remapped to int later
                "title": title,
                "creator": get_value_from_iiif_metadata(metadata, "author"),
                "year": clean_year(date_text),
                "dateText": date_text if date_text != "Unknown" else "",
                "place": place if place != "Unknown" else "",
                "region": "Global",
                "lat": 0.0,
                "lng": 0.0,
                "lang": lang if lang != "Unknown" else "",
                "type": "Manuscript",
                "collection": meta['label'],
                "source": meta['key'],
                "iiif": True,
                "img": pages[0]["thumb"] if pages else "",
                "srcUrl": f"{OP_BASE}/Data/{coll_id}/html/{item_id}.html",
                "callno": callno,
                "desc": desc,
                "pages": pages
            })
        except Exception as e:
            print(f"  Error processing {item_id}: {e}")
            continue
            
    return items

def main():
    print("Starting direct OPenn IIIF Harvest...")
    
    all_items = []
    for coll_id, meta in COLLECTIONS.items():
        col_items = harvest_collection(coll_id, meta)
        all_items.extend(col_items)
        
    if not all_items:
        print("No items found. Aborting.")
        return

    # App.js requires integer IDs
    for idx, item in enumerate(all_items, start=1):
        item["id"] = idx

    featured_ids = [it["id"] for it in all_items[:4]] if len(all_items) >= 4 else []
    sources = {meta["key"]: {"label": meta["label"], "system": meta["system"], "color": meta["color"]} for meta in COLLECTIONS.values()}

    payload = {
        "sources": sources,
        "items": all_items,
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
        
    print(f"Successfully harvested {len(all_items)} total items and wrote them to data.js!")

if __name__ == "__main__":
    main()
