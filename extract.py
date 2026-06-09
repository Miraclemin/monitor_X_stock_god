import datetime as dt
import re


CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9.]{0,9})(?![A-Za-z0-9_])")
NOISE_SYMBOLS = {"AI", "I", "A", "USD", "US", "CEO", "ETF", "IPO"}


def parse_x_date(value):
    if not value:
        return None
    parsed = dt.datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def extract_symbols(text, legacy, note):
    found = set()
    for m in CASHTAG_RE.finditer(text or ""):
        found.add(m.group(1).upper())
    entity_sets = [legacy.get("entities") or {}, note.get("entity_set") or {}]
    for entities in entity_sets:
        for item in entities.get("symbols") or []:
            symbol = item.get("text") or (((item.get("tag") or {}).get("info") or {}).get("info") or {}).get("ticker")
            if symbol:
                found.add(symbol.upper())
    cleaned = set()
    for s in found:
        s = s.upper().strip()
        if s.endswith(".") and s.count(".") == 1:
            s = s[:-1]
        cleaned.add(s)
    return sorted(s for s in cleaned if s not in NOISE_SYMBOLS and 1 < len(s) <= 10)
