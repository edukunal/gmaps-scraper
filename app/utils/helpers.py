import re
from typing import Optional
from urllib.parse import urlparse

def clean_text(text: Optional[str]) -> Optional[str]:
    if not text: return None
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text or None

def clean_phone(phone: Optional[str]) -> Optional[str]:
    if not phone: return None
    phone = re.sub(r'[^\d+\-\s().]', '', phone).strip()
    return phone if len(phone) >= 7 else None

def clean_rating(raw: Optional[str]) -> Optional[float]:
    if not raw: return None
    m = re.search(r'(\d+\.?\d*)', str(raw).replace(',','.'))
    if m:
        v = float(m.group(1))
        return v if 0.0 <= v <= 5.0 else None
    return None

def clean_review_count(raw: Optional[str]) -> Optional[int]:
    if not raw: return None
    raw = str(raw).replace(',','').replace('.','')
    m = re.search(r'(\d+)', raw)
    return int(m.group(1)) if m else None

def clean_url(url: Optional[str]) -> Optional[str]:
    if not url: return None
    url = url.strip()
    if url.startswith("//"): url = "https:" + url
    try:
        p = urlparse(url)
        return url if p.scheme in ("http","https") else None
    except Exception:
        return None

def extract_coords_from_url(url: str):
    for pat in [r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', r'!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)', r'll=(-?\d+\.?\d*),(-?\d+\.?\d*)']:
        m = re.search(pat, url)
        if m:
            try:
                lat, lng = float(m.group(1)), float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return lat, lng
            except ValueError:
                continue
    return None, None

def parse_address_components(address: Optional[str]) -> dict:
    result = {"city": None, "state": None, "postal_code": None}
    if not address: return result
    m = re.search(r'\b(\d{6}|\d{5}(?:-\d{4})?)\b', address)
    if m: result["postal_code"] = m.group(1)
    parts = [p.strip() for p in address.split(',') if p.strip()]
    if len(parts) >= 2:
        result["city"] = clean_text(parts[-2])
        last = parts[-1].strip()
        sm = re.match(r'^([A-Za-z\s]+)', last)
        if sm: result["state"] = sm.group(1).strip()
    return result

def deduplicate_results(results: list, key_fields: list = None) -> list:
    if key_fields is None: key_fields = ["name","address"]
    seen, out = set(), []
    for r in results:
        if isinstance(r, dict): key = tuple(str(r.get(f,"")).lower().strip() for f in key_fields)
        else: key = tuple(str(getattr(r,f,"")).lower().strip() for f in key_fields)
        if key not in seen and any(k for k in key):
            seen.add(key); out.append(r)
    return out
