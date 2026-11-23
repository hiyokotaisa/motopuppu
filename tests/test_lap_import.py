"""手動実行用: python -m unittest discover -s tests -v

DB連携試験は専用DBのURIをLAP_IMPORT_TEST_DATABASE_URIに設定した場合だけ実行する。
実ユーザーのCSVはテストコード・リポジトリに含めない。
"""
import io
import os
import tempfile
from datetime import date
import unittest
from unittest.mock import patch
import uuid

TEST_DATABASE_URI = os.environ.get('LAP_IMPORT_TEST_DATABASE_URI')
if TEST_DATABASE_URI:
    os.environ['DATABASE_URI'] = TEST_DATABASE_URI

from werkzeug.datastructures import FileStorage
from wtforms.validators import ValidationError

from motopuppu.parsers.drogger_parser import DroggerParser
from motopuppu.parsers.racechrono_parser import RaceChronoParser
from motopuppu.utils.file_validators import StreamFileSize
from motopuppu.utils.lap_time_utils import non_outlier_lap_indices, filter_outlier_laps


def drogger_csv(times=(60000, 900000, 60000, 61000)):
    rows = ['Lap,Latitude,Longitude,LapTime,Speed,Rpm,ThrottolePos,RunTime']
    for lap, milliseconds in enumerate(times, 1):
        for point in range(2):
            rows.append(f'{lap},{35 + lap / 100},{139 + point / 1000},{milliseconds},72,8000,50,{lap * 60 + point}')
    return ('\n'.join(rows) + '\n').encode()


RACECHRONO_CSV = (
    'RaceChrono,2\nFormat,3\n'
    'timestamp,lap_number,elapsed_time,latitude,longitude,speed,speed\n'
    's,,s,deg,deg,m/s,m/s\n'
    '0,1,10,35,139,10,99\n'
    '1,1,70,35.001,139.001,20,99\n'
    '2,2,75,35.002,139.002,30,99\n'
    '3,2,130,35.003,139.003,40,99\n'
).encode()


class GuardedStream(io.BytesIO):
    def read(self, size=-1):
        if size < 0:
            raise AssertionError('全件readは禁止')
        return super().read(size)

    def readlines(self, hint=-1):
        raise AssertionError('全件readlinesは禁止')


class ParserTests(unittest.TestCase):
    def test_drogger_streams_and_preserves_parse_api(self):
        result = DroggerParser().parse(GuardedStream(drogger_csv()))
        self.assertEqual(result['lap_times'], ['1:00.000', '15:00.000', '1:00.000', '1:01.000'])
        self.assertEqual(list(result['gps_tracks']), [1, 2, 3, 4])
        self.assertEqual(result['gps_tracks'][1][0]['rpm'], 8000)
        self.assertEqual(result['gps_tracks'][1][0]['throttle'], 50)

    def test_first_lap_is_available_before_reading_entire_file(self):
        data = drogger_csv() + b'4,35.04,139,61000,72,8000,50,241\n' * 10000
        stream = GuardedStream(data)
        laps = DroggerParser().iter_laps(stream)
        self.assertEqual(next(laps)[0], '1:00.000')
        self.assertLess(stream.tell(), len(data))
        laps.close()
        self.assertFalse(stream.closed)

    def test_bom_text_stream_and_replacement_decoding(self):
        data = b'\xef\xbb\xbf' + drogger_csv()
        self.assertEqual(len(DroggerParser().parse(io.StringIO(data.decode()))['lap_times']), 4)
        self.assertEqual(len(DroggerParser().parse(io.BytesIO(data.replace(b'Speed', b'Speed\xff')))['lap_times']), 4)

    def test_late_lap_time_and_invalid_gps(self):
        data = b'Lap,Latitude,Longitude,LapTime\n0,35,139,0\n1,35,139,0\n1,0,0,60000\n2,35,139,0\n'
        result = DroggerParser().parse(io.BytesIO(data))
        self.assertEqual(result['lap_times'], ['1:00.000'])
        self.assertEqual(len(result['gps_tracks'][1]), 1)

    def test_racechrono_streams_and_uses_first_speed_column(self):
        stream = GuardedStream(RACECHRONO_CSV)
        result = RaceChronoParser().parse(stream)
        self.assertEqual(result['lap_times'], ['1:00.000', '1:00.000'])
        self.assertEqual(result['gps_tracks'][1][0]['speed'], 36)
        self.assertFalse(stream.closed)

    def test_missing_headers_and_empty_file(self):
        for parser in (DroggerParser(), RaceChronoParser()):
            self.assertEqual(parser.parse(io.BytesIO(b''))['lap_times'], [])
        with self.assertRaises(ValueError):
            DroggerParser().parse(io.BytesIO(b'Lap,LapTime\n1,60000\n'))

    def test_lap_limits_and_reversed_order(self):
        for parser, data in ((DroggerParser(), drogger_csv()), (RaceChronoParser(), RACECHRONO_CSV)):
            parser.MAX_LAPS = 1
            with self.assertRaisesRegex(ValueError, '最大1ラップ'):
                parser.parse(io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, '逆順'):
            DroggerParser().parse(io.BytesIO(drogger_csv().replace(b'2,35.02', b'0,35.02')))

    def test_outlier_indices_preserve_duplicate_times_and_skip_invalid_values(self):
        times = ['1:00.000', '15:00.000', '1:00.000', 'invalid', '1:01.000']
        self.assertEqual(non_outlier_lap_indices(times), [0, 2, 4])
        self.assertEqual(filter_outlier_laps(times), ['1:00.000', '1:00.000', '1:01.000'])

    def test_size_validator_does_not_read_and_restores_position(self):
        stream = GuardedStream(b'1234')
        stream.seek(2)
        field = type('Field', (), {'data': FileStorage(stream, filename='test.csv')})()
        StreamFileSize(max_size=4)(None, field)
        self.assertEqual(stream.tell(), 2)
        with self.assertRaises(ValidationError):
            StreamFileSize(max_size=3, message='サイズ超過')(None, field)
        self.assertEqual(stream.tell(), 2)

    def test_exact_150mb_boundary_without_allocating_file_in_memory(self):
        limit = 150 * 1024 * 1024
        with tempfile.TemporaryFile() as stream:
            field = type('Field', (), {'data': FileStorage(stream, filename='test.csv')})()
            validator = StreamFileSize(max_size=limit, message='サイズ超過')
            stream.truncate(limit)
            validator(None, field)
            stream.truncate(limit + 1)
            with self.assertRaises(ValidationError):
                validator(None, field)


@unittest.skipUnless(TEST_DATABASE_URI, '専用のPostgreSQLテストDBが未指定')
class ImportRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from motopuppu import create_app, db, limiter
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        limiter.enabled = False
        cls.db = db
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        from motopuppu.models import User, Motorcycle, ActivityLog, SessionLog
        self.context = self.app.app_context()
        self.context.push()
        user = User(misskey_user_id='lap_test_' + uuid.uuid4().hex)
        self.db.session.add(user)
        self.db.session.flush()
        bike = Motorcycle(user_id=user.id, name='試験用')
        self.db.session.add(bike)
        self.db.session.flush()
        activity = ActivityLog(user_id=user.id, motorcycle_id=bike.id, activity_date=date(2026, 11, 21))
        self.db.session.add(activity)
        self.db.session.flush()
        self.record = SessionLog(activity_log_id=activity.id, lap_times=['0:50.000', '0:51.000'])
        self.db.session.add(self.record)
        self.db.session.commit()
        self.session_id = self.record.id
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_user_id'] = str(user.id)
            state['_fresh'] = True

    def tearDown(self):
        self.db.session.remove()
        self.context.pop()

    def post(self, data=None, device='drogger', append=False, stream=True, filter_outliers=True):
        fields = {'device_type': device, 'outlier_threshold': '2.0',
                  'csv_file': (io.BytesIO(drogger_csv() if data is None else data), 'test.csv')}
        if append:
            fields['append_mode'] = 'y'
        if filter_outliers:
            fields['remove_outliers'] = 'y'
        response = self.client.post(
            f'/activity/session/{self.session_id}/import_laps', data=fields,
            headers={'Accept': 'application/x-ndjson'} if stream else {}, buffered=False,
        )
        body = response.get_data()
        response.close()
        self.db.session.expire_all()
        return response, body

    def test_streaming_import_filters_and_renumbers_gps(self):
        response, body = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"stage": "done"', body)
        self.assertEqual(self.record.lap_times, ['1:00.000', '1:00.000', '1:01.000'])
        laps = self.record.gps_tracks['laps']
        self.assertEqual([lap['lap_number'] for lap in laps], [1, 2, 3])
        self.assertEqual([lap['track'][0]['lat'] for lap in laps], [35.01, 35.03, 35.04])

    def test_append_uses_time_count_when_existing_gps_is_missing(self):
        self.record.gps_tracks = {'laps': [{'lap_number': 1, 'track': [{'lat': 35, 'lng': 139}]}]}
        self.db.session.commit()
        self.post(append=True)
        self.assertEqual(len(self.record.lap_times), 5)
        self.assertEqual([lap['lap_number'] for lap in self.record.gps_tracks['laps']], [1, 3, 4, 5])

    def test_non_ajax_and_all_non_gps_formats(self):
        for device, data in (
            ('simple_csv', b'1:00.000\n1:01.000\n'),
            ('ziix', b'"LAP","LAP TIME"\nBEST,1:00.000\n1,1\'00.000\n2,1\'01.000\n'),
            ('mylaps', b'1,a,b,c,d,1:00.000\n2,a,b,c,d,1:01.000\n'),
            ('racechrono', RACECHRONO_CSV),
        ):
            with self.subTest(device=device):
                response, _ = self.post(data, device, stream=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(len(self.record.lap_times), 2)
                self.assertEqual(self.record.gps_tracks is None, device != 'racechrono')

    def test_invalid_file_preserves_existing_data_and_suggests_format(self):
        response, body = self.post(b'1:00.000\n1:01.000\n')
        self.assertEqual(response.status_code, 200)
        self.assertIn('シンプルCSV'.encode(), body)
        self.assertEqual(self.record.lap_times, ['0:50.000', '0:51.000'])

    def test_database_error_rolls_back(self):
        with patch.object(self.db.session, 'commit', side_effect=RuntimeError('test save failure')):
            _, body = self.post()
        self.assertIn(b'"stage": "error"', body)
        self.assertEqual(self.record.lap_times, ['0:50.000', '0:51.000'])

    def test_disconnect_closes_stream_and_preserves_existing_data(self):
        from motopuppu.views.activity.session_routes import _import_laps_generator
        stream = GuardedStream(drogger_csv())
        events = _import_laps_generator(self.session_id, self.record.activity_log_id, stream,
                                        'drogger', False, 2, False, '/')
        self.assertEqual(next(events)['stage'], 'parsing')
        self.assertEqual(next(events)['stage'], 'optimizing')
        events.close()
        self.assertTrue(stream.closed)
        self.assertEqual(self.record.lap_times, ['0:50.000', '0:51.000'])

    def test_response_owns_upload_until_closed(self):
        from motopuppu.views.activity import session_routes
        original = session_routes._import_laps_generator
        streams = []

        def capture(*args, **kwargs):
            streams.append(args[2])
            return original(*args, **kwargs)

        with patch.object(session_routes, '_import_laps_generator', side_effect=capture):
            response = self.client.post(
                f'/activity/session/{self.session_id}/import_laps',
                data={'device_type': 'drogger', 'outlier_threshold': '2.0',
                      'csv_file': (io.BytesIO(drogger_csv()), 'test.csv')},
                headers={'Accept': 'application/x-ndjson'}, buffered=False,
            )
            self.assertFalse(streams[0].closed)
            response.close()
        self.assertTrue(streams[0].closed)
        self.assertEqual(self.record.lap_times, ['0:50.000', '0:51.000'])


if __name__ == '__main__':
    unittest.main()
