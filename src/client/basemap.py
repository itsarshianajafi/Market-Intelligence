"""Fetch the map the client view draws: Dubai's coastline, motorways and a point for each DLD area.

    python -m src.client.basemap

Source: OpenStreetMap through the Overpass API (© OpenStreetMap contributors, ODbL). Run it by hand
when areas change; the result is committed as data/reference/dubai_map.json, so the client view and
the tests never need the network.

A DLD area gets the centre of the OpenStreetMap place with the same name once number words and
punctuation are normalised ("Al Barsha South Fourth" = "Al Barsha South 4"). Where the two sources
spell a name differently, data/area_place_aliases.csv says which place is meant. Nothing is matched
by similarity, and an area without a match is simply left off the map.
"""
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

BOX = (24.78, 54.88, 25.38, 55.62)      # south, west, north, east
OUTPUT = Path('data/reference/dubai_map.json')
ALIASES = Path('data/area_place_aliases.csv')
ORDINALS = {'first': '1', 'second': '2', 'third': '3', 'fourth': '4', 'fifth': '5', 'sixth': '6',
            'seventh': '7', 'eighth': '8', 'ninth': '9', 'tenth': '10'}
RANK = {'suburb': 0, 'quarter': 1, 'neighbourhood': 2}     # prefer a whole community over a part of one
NAME_TAGS = ['name:en', 'name', 'official_name:en', 'alt_name:en', 'int_name', 'alt_name', 'official_name']


def key(name):
    """Comparable form of a place name: lower case, number words as digits, no spaces or punctuation."""
    words = re.findall(r'[a-z]+|\d+', str(name).lower().replace("'", ''))
    return ''.join(ORDINALS.get(word, word) for word in words)


def simplify(points, tolerance):
    """Douglas-Peucker: drop points closer than `tolerance` (in degrees) to the line through their neighbours."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        worst, index = 0.0, None
        for i in range(first + 1, last):
            x, y = points[i]
            distance = (abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / length if length
                        else ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5)
            if distance > worst:
                worst, index = distance, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [point for point, kept in zip(points, keep) if kept]


def match_places(areas, elements, aliases):
    """{area: {lat, lon, osm_name, match}} for every area with an OpenStreetMap place of the same name."""
    places = {}
    for element in elements:
        centre = element.get('center') or ({'lat': element['lat'], 'lon': element['lon']} if 'lat' in element else None)
        if not centre:
            continue
        rank = RANK.get(element['tags'].get('place'), 3)
        for tag in NAME_TAGS:
            for name in str(element['tags'].get(tag, '')).split(';'):
                if name.strip() and (key(name) not in places or rank < places[key(name)][0]):
                    places[key(name)] = (rank, name.strip(), centre)
    found = {}
    for area in areas:
        wanted, how = (aliases[area], 'alias') if area in aliases else (area, 'name')
        if key(wanted) in places:
            _, name, centre = places[key(wanted)]
            found[area] = {'lat': round(centre['lat'], 4), 'lon': round(centre['lon'], 4), 'osm_name': name, 'match': how}
    return found


def lines(elements, tolerance, shortest=2):
    """Each way as [[lon, lat], ...], simplified and rounded; ways that collapse to almost nothing are dropped."""
    out = []
    for element in elements:
        points = simplify([(p['lon'], p['lat']) for p in element['geometry']], tolerance)
        if len(points) >= shortest:
            out.append([[round(lon, 4), round(lat, 4)] for lon, lat in points])
    return out


def overpass(query):
    request = Request('https://overpass-api.de/api/interpreter', data=urlencode({'data': query}).encode(),
                      headers={'User-Agent': 'market-intelligence-student-project/1.0'})
    for attempt in range(4):        # the public server is often briefly busy
        try:
            with urlopen(request, timeout=240) as response:
                return json.load(response)['elements']
        except HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(30)


def build(areas, output=OUTPUT):
    box = ','.join(map(str, BOX))
    places = overpass(f'[out:json][timeout:150];(nwr["place"~"^(suburb|quarter|neighbourhood|locality|town|village|island)$"]({box});'
                      f'relation["boundary"="administrative"]({box}););out tags center;')
    ways = overpass(f'[out:json][timeout:150];(way["natural"="coastline"]({box});way["highway"="motorway"]({box}););out geom;')
    aliases = dict(pd.read_csv(ALIASES).itertuples(index=False)) if ALIASES.exists() else {}
    result = {
        'source': 'OpenStreetMap via the Overpass API', 'attribution': '© OpenStreetMap contributors, ODbL',
        'fetched': pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d'), 'box': list(BOX),
        'coast': lines([w for w in ways if w['tags'].get('natural') == 'coastline'], 0.0006),
        'roads': lines([w for w in ways if w['tags'].get('highway') == 'motorway'], 0.0015),
        'places': match_places(areas, places, aliases)}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    return result


def main():
    areas = sorted(pd.read_csv('data/shared/monthly_sales.csv').area.unique())
    result = build(areas)
    print(f"{len(result['places'])} of {len(areas)} areas placed, {len(result['coast'])} coast lines, "
          f"{len(result['roads'])} road lines -> {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == '__main__':
    main()
