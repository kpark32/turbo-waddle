"""
NYC Cooling Centers → KML Generator
====================================
Fetches live data from the ArcGIS FeatureServer backing finder.nyc.gov/coolingcenters
and writes a KML file suitable for a Google My Maps Network Link.

Pin label format (per spec):
  "Location Name - Cooling Center"
  "Location Name - Cooling Center (Older Adults Only)"

Usage:
  pip install requests
  python build_kml.py

Output:
  cooling_centers.kml   ← point this at your Google My Maps Network Link
"""

import json
import requests
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Candidate ArcGIS endpoints (script tries each until one works) ──────────
# If both fail, open finder.nyc.gov in Chrome → DevTools → Network tab →
# reload the page → filter for "FeatureServer" or "query?" → copy that URL
# and paste it as the first entry here.
ARCGIS_ENDPOINTS = [
    "https://services6.arcgis.com/yG5s3afENB5iO9fj/arcgis/rest/services/Cool_Options/FeatureServer/0/query",
]

QUERY_PARAMS = {
    "where":           "1=1",
    "outFields":       "*",
    "returnGeometry":  "true",
    "f":               "geojson",
    "resultRecordCount": 2000,
}

KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def tag(name):
    return f"{{{KML_NS}}}{name}"


# ── Field name discovery ─────────────────────────────────────────────────────
# NYC OEM has changed field names across years. This maps common variants.
FIELD_NAME    = ("NAME", "SiteName", "FACILITYNAME", "facilityName", "name", "SITE_NAME")
FIELD_SENIOR  = ("SENIORONLY", "OlderAdultsOnly", "OLDER_ADULTS", "senior_only",
                 "target_pop", "olderAdultsOnly", "SENIOR_ONLY")
FIELD_HOURS   = ("HOURS", "Hours", "hours", "HOURSOFOPERATION", "HoursOfOperation",
                 "operatingHours", "OPERATING_HOURS")
FIELD_ADDRESS = ("ADDRESS", "Address", "address", "LOCATION", "Location",
                 "fullAddress", "FULL_ADDRESS")
FIELD_BOROUGH = ("BOROUGH", "Borough", "borough", "BORO")
FIELD_PHONE   = ("PHONE", "Phone", "phone", "TELEPHONE")


def first(props, candidates, default=""):
    for k in candidates:
        if k in props and props[k] not in (None, ""):
            return str(props[k])
    return default


def is_senior_only(props):
    for k in FIELD_SENIOR:
        val = props.get(k)
        if val is None:
            continue
        if isinstance(val, bool):
            return val
        if str(val).strip().upper() in ("1", "TRUE", "YES", "Y", "OLDER ADULTS"):
            return True
    return False


def build_label(props):
    name   = first(props, FIELD_NAME, "Cooling Center")
    senior = is_senior_only(props)
    label  = f"{name} - Cooling Center"
    if senior:
        label += " (Older Adults Only)"
    return label


def build_description(props):
    hours   = first(props, FIELD_HOURS,   "Hours not listed")
    address = first(props, FIELD_ADDRESS, "")
    borough = first(props, FIELD_BOROUGH, "")
    phone   = first(props, FIELD_PHONE,   "")
    parts   = []
    if address: parts.append(f"📍 {address}{', ' + borough if borough else ''}")
    if hours:   parts.append(f"🕐 {hours}")
    if phone:   parts.append(f"📞 {phone}")
    return "\n".join(parts)


# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch_features():
    for url in ARCGIS_ENDPOINTS:
        try:
            r = requests.get(url, params=QUERY_PARAMS, timeout=30)
            r.raise_for_status()
            data = r.json()
            features = data.get("features", [])
            if features:
                print(f"✓ {len(features)} features from {url}")
                return features
        except Exception as e:
            print(f"  ✗ {url} — {e}")
    raise RuntimeError(
        "All ArcGIS endpoints failed.\n"
        "Fix: open finder.nyc.gov in Chrome, DevTools → Network, reload,\n"
        "filter for 'FeatureServer', copy the URL, paste into ARCGIS_ENDPOINTS[0]."
    )


# ── KML builder ──────────────────────────────────────────────────────────────

def build_kml(features):
    kml      = ET.Element(tag("kml"))
    document = ET.SubElement(kml, tag("Document"))

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    ET.SubElement(document, tag("name")).text        = f"NYC Cooling Centers"
    ET.SubElement(document, tag("description")).text = (
        f"Auto-updated from finder.nyc.gov/coolingcenters. Last run: {now}.\n"
        "🟢 Green = open to all  |  🔴 Red = Older Adults (60+) Only"
    )

    # Two simple styles: green (general) and red (senior-only)
    for style_id, color in [("general", "ff00aa00"), ("senior", "ff0000ff")]:
        style = ET.SubElement(document, tag("Style"))
        style.set("id", style_id)
        icon_style = ET.SubElement(style, tag("IconStyle"))
        ET.SubElement(icon_style, tag("color")).text = color
        icon = ET.SubElement(icon_style, tag("Icon"))
        ET.SubElement(icon, tag("href")).text = (
            "https://maps.google.com/mapfiles/kml/paddle/grn-circle.png"
            if style_id == "general"
            else "https://maps.google.com/mapfiles/kml/paddle/red-circle.png"
        )

    skipped = 0
    for feat in features:
        props  = feat.get("properties") or feat.get("attributes") or {}
        geom   = feat.get("geometry", {})

        coords = None
        if geom.get("type") == "Point":
            coords = geom["coordinates"]          # [lon, lat]
        elif "x" in geom and "y" in geom:        # ArcGIS native geometry
            coords = [geom["x"], geom["y"]]

        if not coords:
            skipped += 1
            continue

        lon, lat = float(coords[0]), float(coords[1])
        senior   = is_senior_only(props)
        label    = build_label(props)
        desc     = build_description(props)

        pm = ET.SubElement(document, tag("Placemark"))
        ET.SubElement(pm, tag("name")).text        = label
        ET.SubElement(pm, tag("description")).text = desc
        styleUrl = ET.SubElement(pm, tag("styleUrl"))
        styleUrl.text = "#senior" if senior else "#general"
        point = ET.SubElement(pm, tag("Point"))
        ET.SubElement(point, tag("coordinates")).text = f"{lon},{lat},0"

    if skipped:
        print(f"  ⚠ {skipped} features skipped (no geometry)")

    return ET.ElementTree(kml)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    features = fetch_features()
    tree     = build_kml(features)

    out = Path("cooling_centers.kml")
    tree.write(str(out), encoding="utf-8", xml_declaration=True)
    print(f"✓ Written → {out}  ({out.stat().st_size // 1024} KB, {len(features)} pins)")


if __name__ == "__main__":
    main()
