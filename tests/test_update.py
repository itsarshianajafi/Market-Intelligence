"""The one-command refresh: quarters move forward, and a failed run leaves everything as it was."""
import json
from pathlib import Path
import tempfile
import unittest

from src.forecasting.run import DEFAULT_CONFIG
from src.update import advance_quarters, restored_on_failure


class UpdateTests(unittest.TestCase):
    def test_quarters_follow_the_newest_complete_quarter(self):
        text = DEFAULT_CONFIG.read_text()
        for date_max, origin, forecast in [('2026-10-27', '2026Q3', '2026Q4'),   # October is not a full quarter
                                           ('2026-12-31', '2026Q4', '2027Q1'),
                                           ('2027-01-05', '2026Q4', '2027Q1')]:
            cfg = json.loads(advance_quarters(text, date_max))
            self.assertEqual((cfg['origin_quarter'], cfg['test_end'], cfg['forecast_quarter']),
                             (origin, origin, forecast))
        unchanged = {k: v for k, v in json.loads(advance_quarters(text, '2027-01-05')).items()
                     if k not in ('origin_quarter', 'test_end', 'forecast_quarter')}
        self.assertEqual(unchanged, {k: v for k, v in json.loads(text).items() if k in unchanged})
        with self.assertRaisesRegex(ValueError, 'origin_quarter'):
            advance_quarters('{}', '2026-10-27')

    def test_failed_run_puts_files_back(self):
        with tempfile.TemporaryDirectory() as folder:
            shared, config = Path(folder) / 'shared', Path(folder) / 'config.json'
            shared.mkdir()
            (shared / 'kept.csv').write_text('old')
            config.write_text('old config')
            with self.assertRaises(ValueError):
                with restored_on_failure([shared, config, Path(folder) / 'never-existed']):
                    (shared / 'kept.csv').write_text('half-written')
                    (shared / 'new.csv').write_text('new')
                    config.write_text('new config')
                    raise ValueError('Part 3 failed')
            self.assertEqual((shared / 'kept.csv').read_text(), 'old')
            self.assertFalse((shared / 'new.csv').exists())
            self.assertEqual(config.read_text(), 'old config')
            with restored_on_failure([shared]):                    # a run that works keeps its changes
                (shared / 'kept.csv').write_text('fresh')
            self.assertEqual((shared / 'kept.csv').read_text(), 'fresh')


if __name__ == '__main__':
    unittest.main()
