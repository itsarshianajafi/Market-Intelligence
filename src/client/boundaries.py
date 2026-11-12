"""Official community boundaries for the client view's maps.

    python -m src.client.boundaries

Two open datasets from Data Dubai (Dubai Open Data Licence):
- "Communities" (Dubai Municipality, https://data.dubai/en/l/461494): one polygon per community, with
  its municipality number (COMM_NUM).
- "Lookup Dubai Community Areas" (Dubai Land Department, https://data.dubai/en/l/465592): DLD's area id
  and area name next to the municipality number.

DLD areas are joined to the polygons by that number, so nothing is matched by name. The result is
data/reference/dubai_communities.geojson (simplified to about 20 m) plus the lookup as CSV, both
committed so the client view never needs to download them. Pass --kml and --lookup to use files
downloaded by hand instead of the Data Dubai service.
"""
import argparse
import gzip
import json
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pandas as pd

from .basemap import simplify

PORTAL = 'https://data.dubai'
COMMUNITIES, LOOKUP = 461494, 465592
OUTPUT = Path('data/reference/dubai_communities.geojson')
LOOKUP_OUTPUT = Path('data/reference/dld_dm_area_lookup.csv')
KML = '{http://www.opengis.net/kml/2.2}'
TOLERANCE = 0.0002      # degrees, about 20 m: invisible at city zoom, a fifth of the points


def fetch_json(url, dataset):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 market-intelligence-student-project',
                                    'Referer': f'{PORTAL}/en/l/{dataset}'})
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def download_kml():
    """The Communities dataset is a gzipped KML file behind a link that expires after ten minutes."""
    answer = fetch_json(f'{PORTAL}/o/dda/data-services/dataset-download?datasetId={COMMUNITIES}&page=1&pageSize=50&sortDir=desc',
                        COMMUNITIES)
    files = [f for folder in answer['data']['metadata'] for f in folder['files'] if f['file_extension'] == 'kml']
    if not files:
        raise ValueError('The Communities dataset no longer offers a KML file')
    with urlopen(Request(files[0]['file_url'], headers={'User-Agent': 'Mozilla/5.0'}), timeout=120) as response:
        raw = response.read()
    return gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw


def download_lookup():
    answer = fetch_json(f'{PORTAL}/o/dda/data-services/dataset-metadata?datasetId={LOOKUP}', LOOKUP)
    if not answer.get('success'):
        raise ValueError(f"The area lookup could not be read: {answer.get('message')}")
    return pd.DataFrame(answer['data'])


def parse_kml(text):
    """{municipality number: {'name_en', 'name_ar', 'rings': [[(lon, lat), ...], ...]}} from the KML."""
    root = ET.fromstring(text)
    communities = {}
    for placemark in root.iter(f'{KML}Placemark'):
        fields = {d.get('name'): (d.text or '').strip() for d in placemark.iter(f'{KML}SimpleData')}
        rings = []
        for polygon in placemark.iter(f'{KML}Polygon'):
            for boundary in ('outerBoundaryIs', 'innerBoundaryIs'):
                for ring in polygon.findall(f'{KML}{boundary}/{KML}LinearRing/{KML}coordinates'):
                    points = [tuple(map(float, p.split(',')[:2])) for p in (ring.text or '').split()]
                    if len(points) >= 4:
                        rings.append((boundary == 'outerBoundaryIs', points))
        if fields.get('COMM_NUM') and rings:
            communities[fields['COMM_NUM']] = {'name_en': fields.get('CNAME_E', ''), 'name_ar': fields.get('CNAME_A', ''), 'rings': rings}
    return communities


def centre(points):
    """Area-weighted centroid of a ring (the shoelace formula), as (lon, lat)."""
    area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < 1e-12:
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    return cx / (3 * area), cy / (3 * area)


def build(kml_text, lookup, output=OUTPUT, lookup_output=LOOKUP_OUTPUT):
    communities = parse_kml(kml_text)
    lookup = lookup.assign(municipality_number=lookup.municipality_number.astype(str).str.strip(),
                           name_en=lookup.name_en.astype(str).str.strip())
    features, unmatched = [], []
    for row in lookup.sort_values('name_en').itertuples():
        shape = communities.get(row.municipality_number)
        if shape is None:
            if row.municipality_number not in ('0', ''):
                unmatched.append(row.name_en)
            continue
        outer = [ring for is_outer, ring in shape['rings'] if is_outer]
        main = max(outer, key=len)
        lon, lat = centre(main[:-1] if main[0] == main[-1] else main)
        polygon = [[[round(x, 5), round(y, 5)] for x, y in simplify(ring, TOLERANCE)] for _, ring in shape['rings']]
        features.append({'type': 'Feature',
                         'properties': {'area': row.name_en, 'area_id': int(row.area_id), 'comm_num': row.municipality_number,
                                        'dm_name': shape['name_en'].title(), 'centre': [round(lat, 5), round(lon, 5)]},
                         'geometry': {'type': 'Polygon', 'coordinates': [ring for ring in polygon if len(ring) >= 4]}})
    collection = {'type': 'FeatureCollection',
                  'source': 'Data Dubai: Communities (Dubai Municipality) and Lookup Dubai Community Areas (Dubai Land Department)',
                  'licence': 'Dubai Open Data Licence', 'fetched': pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d'),
                  'features': features}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(collection, separators=(',', ':'), ensure_ascii=False) + '\n')
    lookup[['area_id', 'name_en', 'name_ar', 'municipality_number']].sort_values('area_id').to_csv(lookup_output, index=False)
    return collection, unmatched


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kml', type=Path, help='Communities KML (or .kml.gz) downloaded by hand')
    parser.add_argument('--lookup', type=Path, help='Lookup Dubai Community Areas as CSV or JSON, downloaded by hand')
    args = parser.parse_args()
    if args.kml:
        raw = args.kml.read_bytes()
        kml = gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    else:
        kml = download_kml()
    if args.lookup:
        lookup = pd.read_csv(args.lookup) if args.lookup.suffix == '.csv' else pd.DataFrame(json.loads(args.lookup.read_text()).get('data'))
    else:
        lookup = download_lookup()
    collection, unmatched = build(kml, lookup)
    points = sum(len(ring) for f in collection['features'] for ring in f['geometry']['coordinates'])
    print(f"{len(collection['features'])} DLD areas with a boundary ({points:,} points) -> {OUTPUT} "
          f"({OUTPUT.stat().st_size // 1024} KB); lookup -> {LOOKUP_OUTPUT}")
    if unmatched:
        print(f"{len(unmatched)} areas have a municipality number with no polygon: {', '.join(unmatched[:10])}")


if __name__ == '__main__':
    main()
