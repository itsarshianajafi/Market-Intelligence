"""Names people use for DLD areas, taken from the export's own master project column.

    python -m src.dld_data.area_names --input data/raw/export_1.csv data/raw/export_2.csv

DLD's areas are land names (Marsa Dubai, Al Barsha South Fourth); buyers and agents say Dubai Marina
and Jumeirah Village Circle. Nothing is guessed: a name comes from the recorded sales, and an area
whose sales are spread over many projects keeps its DLD name.
"""
import argparse
from pathlib import Path

import pandas as pd

COLUMNS = ['area_name_en', 'master_project_en', 'instance_date', 'trans_group_en', 'property_type_en']
MAIN_SHARE, LISTED_SHARE = 0.5, 0.2
OVERRIDES = Path('data/area_name_overrides.csv')


def tidy(names):
    """Same whitespace rule as the cleaning step; shouted names (DAMAC HILLS) become title case."""
    names = names.astype('string').str.strip().str.replace(r'\s+', ' ', regex=True)
    return names.mask(names.str.isupper(), names.str.title())


def area_names(sales):
    """One row per area: the master project with most sales, its share, and other sizeable ones.

    common_name is the top project if it has at least half of the area's sales, otherwise every
    project with at least a fifth if together they reach half, otherwise blank.
    """
    sales = sales.assign(area=tidy(sales.area_name_en), project=tidy(sales.master_project_en))
    counts = sales[sales.project.ne('')].groupby(['area', 'project']).size().rename('sales')
    share = (counts / sales.groupby('area').size()).rename('share').reset_index()
    share = share.sort_values(['area', 'share', 'project'], ascending=[True, False, True])
    rows = []
    for area, group in share.groupby('area'):
        listed = group[group.share >= LISTED_SHARE]
        top = group.iloc[0]
        name = top.project if top.share >= MAIN_SHARE else ' / '.join(listed.project)
        if listed.share.sum() < MAIN_SHARE:     # the named projects must cover at least half the sales
            name = ''
        rows.append({'area': area, 'common_name': name, 'share': round(float(top.share), 3),
                     'also_includes': ' / '.join(listed.project[listed.project.ne(name)]) if top.share >= MAIN_SHARE else ''})
    return pd.DataFrame(rows, columns=['area', 'common_name', 'share', 'also_includes'])


def build(inputs, output, start_year=2020, overrides=OVERRIDES):
    frames = []
    for path in inputs:
        header = pd.read_csv(path, nrows=0).columns
        if not set(COLUMNS).issubset(header):
            raise ValueError(f'{Path(path).name} has no master project column; use the Data Dubai export')
        frames.append(pd.read_csv(path, usecols=COLUMNS, dtype='string', keep_default_na=False))
    raw = pd.concat(frames, ignore_index=True)
    sales = raw[raw.trans_group_en.str.casefold().eq('sales') & raw.property_type_en.isin(['Unit', 'Villa'])
                & (raw.instance_date.str.extract(r'(\d{4})')[0] >= str(start_year))]
    names = area_names(sales)
    if Path(overrides).exists():        # corrections from people who know the market win over the data
        fixed = pd.read_csv(overrides, dtype='string').dropna(subset=['area', 'common_name'])
        names = names.set_index('area')
        names.loc[names.index.intersection(fixed.area), 'common_name'] = fixed.set_index('area').common_name
        names = names.reset_index()
    names.to_csv(output, index=False)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, default=Path('data/shared/area_names.csv'))
    args = parser.parse_args()
    try:
        names = build(args.input, args.output)
    except (ValueError, OSError, pd.errors.ParserError) as exc:
        parser.exit(1, f'Area names failed: {exc}\n')
    print(f"{len(names)} areas, {int(names.common_name.ne('').sum())} with a common name -> {args.output}")


if __name__ == '__main__':
    main()
