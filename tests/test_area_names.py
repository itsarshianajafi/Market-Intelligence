"""Area names come from recorded sales only; nothing is guessed."""
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.dld_data.area_names import area_names, build


def sales(rows):
    """rows: (area, master project, count)."""
    return pd.DataFrame([{'area_name_en': area, 'master_project_en': project}
                         for area, project, count in rows for _ in range(count)])


class AreaNameTests(unittest.TestCase):
    def test_majority_project_names_the_area(self):
        names = area_names(sales([('Marsa Dubai', 'Dubai Marina', 6), ('Marsa Dubai', 'Dubai Harbour', 3),
                                  ('Marsa Dubai', '', 1), ('  Al  Hebiah Third ', 'DAMAC HILLS', 5)])).set_index('area')
        self.assertEqual(names.loc['Marsa Dubai', 'common_name'], 'Dubai Marina')
        self.assertEqual(names.loc['Marsa Dubai', 'share'], 0.6)           # blank projects count against the share
        self.assertEqual(names.loc['Marsa Dubai', 'also_includes'], 'Dubai Harbour')
        self.assertEqual(names.loc['Al Hebiah Third', 'common_name'], 'Damac Hills')   # tidied like Part 1's areas

    def test_spread_out_area_keeps_its_dld_name(self):
        names = area_names(sales([('Split', 'One', 4), ('Split', 'Two', 3), ('Split', 'Three', 3),
                                  ('Thin', 'One', 3), ('Thin', '', 7)])).set_index('area')
        self.assertEqual(names.loc['Split', 'common_name'], 'One / Three / Two')   # together they cover the area
        self.assertEqual(names.loc['Thin', 'common_name'], '')                     # 30% is not enough to rename it

    def test_build_filters_sales_and_applies_corrections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = pd.DataFrame({'area_name_en': 'Al Thanyah Fifth', 'master_project_en': 'DMCC Master Community',
                                'instance_date': ['2021-05-01', '2019-05-01', '2022-01-01', '2023-01-01'],
                                'trans_group_en': ['Sales', 'Sales', 'Mortgages', 'Sales'],
                                'property_type_en': ['Unit', 'Unit', 'Unit', 'Land']})
            raw.to_csv(root / 'export.csv', index=False)
            (root / 'fixes.csv').write_text('area,common_name\nAl Thanyah Fifth,Jumeirah Lakes Towers\n')
            plain = build([root / 'export.csv'], root / 'names.csv', overrides=root / 'none.csv')
            self.assertEqual(plain.common_name.tolist(), ['DMCC Master Community'])
            fixed = build([root / 'export.csv'], root / 'names.csv', overrides=root / 'fixes.csv')
            self.assertEqual(fixed.common_name.tolist(), ['Jumeirah Lakes Towers'])
            raw.drop(columns='master_project_en').to_csv(root / 'other.csv', index=False)
            with self.assertRaisesRegex(ValueError, 'master project'):
                build([root / 'other.csv'], root / 'names.csv')


if __name__ == '__main__':
    unittest.main()
