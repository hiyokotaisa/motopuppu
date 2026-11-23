"""手動実行するPostgreSQL連携試験。専用DBは既存の環境変数で指定する。"""
import os
import io
import json
from html import unescape
from datetime import date
import unittest
import uuid
from urllib.parse import parse_qs, urlsplit

from flask import template_rendered
from sqlalchemy import event, inspect

TEST_DATABASE_URI = os.environ.get('LAP_IMPORT_TEST_DATABASE_URI')
if TEST_DATABASE_URI:
    os.environ['DATABASE_URI'] = TEST_DATABASE_URI

from motopuppu import create_app, db, limiter
from motopuppu.constants import CIRCUIT_METADATA
from motopuppu.models import User, Motorcycle, ActivityLog, SessionLog, Team


@unittest.skipUnless(TEST_DATABASE_URI, '専用のPostgreSQLテストDBが未指定')
class CircuitViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        limiter.enabled = False
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        with self.app.app_context():
            users = [User(misskey_user_id=uuid.uuid4().hex) for _ in range(3)]
            db.session.add_all(users)
            db.session.flush()
            self.owner_id, self.member_id, self.other_id = [user.id for user in users]
            bike = Motorcycle(user_id=users[0].id, name='走行ログ試験用')
            db.session.add(bike)
            db.session.flush()
            activity = ActivityLog(user_id=users[0].id, motorcycle_id=bike.id,
                                   activity_date=date(2026, 11, 21), location_type='circuit',
                                   circuit_name=next(iter(CIRCUIT_METADATA)))
            db.session.add(activity)
            db.session.flush()
            self.track = [
                {'lat': 35.0, 'lng': 139.0, 'speed': 60.0, 'runtime': 100.0},
                {'lat': 35.001, 'lng': 139.001, 'speed': 70.0, 'runtime': 101.0},
            ]
            session = SessionLog(activity_log_id=activity.id,
                                 lap_times=['1:10.000', '1:11.000', '1:12.000', '1:13.000'],
                                 best_lap_seconds=70,
                                 gps_tracks={'laps': [{'lap_number': 3, 'track': self.track},
                                                      {'lap_number': 4, 'track': self.track}]})
            empty = SessionLog(activity_log_id=activity.id, lap_times=['1:20.000'],
                               best_lap_seconds=80, gps_tracks={'laps': []})
            team = Team(owner_id=users[0].id, name='試験チーム')
            team.members.extend(users[:2])
            db.session.add_all([session, empty, team])
            db.session.commit()
            self.activity_id, self.session_id, self.empty_id = activity.id, session.id, empty.id
        self.detail_url = f'/activity/{self.activity_id}/detail'
        self.gps_url = f'/activity/session/{self.session_id}/gps_data'

    def client_for(self, user_id):
        client = self.app.test_client()
        if user_id is not None:
            with client.session_transaction() as state:
                state['_user_id'] = str(user_id)
                state['_fresh'] = True
        return client

    def set_shared(self, shared):
        with self.app.app_context():
            db.session.get(ActivityLog, self.activity_id).share_with_teams = shared
            db.session.commit()

    def enable_beta(self):
        with self.app.app_context():
            db.session.get(User, self.owner_id).use_beta_ui = True
            db.session.commit()

    def test_beta_course_filter_and_navigation_preserve_list_conditions(self):
        self.enable_beta()
        with self.app.app_context():
            activity = db.session.get(ActivityLog, self.activity_id)
            course, bike_id = activity.circuit_name, activity.motorcycle_id
            another = ActivityLog(user_id=self.owner_id, motorcycle_id=bike_id,
                                  activity_date=date(2026, 11, 22), location_type='circuit',
                                  circuit_name=course + ' 別コース')
            db.session.add(another)
            db.session.commit()
        captured = {}

        def capture(sender, template, context, **extra):
            if 'logs' in context:
                captured['ids'] = [log['obj'].id for log in context['logs']]
                captured['list_url'] = context['current_list_url']
                captured['bike_url'] = context['activity_filter_url'](vehicle_id=bike_id)
                captured['touring_url'] = context['activity_filter_url'](log_type='touring')

        client = self.client_for(self.owner_id)
        with template_rendered.connected_to(capture, self.app):
            response = client.get('/activity/', query_string={
                'circuit_name': course, 'start_date': '2026-11-01',
                'sort_by': 'vehicle', 'order': 'asc', 'page': 1,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['ids'], [self.activity_id])
        params = parse_qs(urlsplit(captured['bike_url']).query)
        self.assertEqual(params['circuit_name'], [course])
        self.assertEqual(params['start_date'], ['2026-11-01'])
        self.assertEqual(params['sort_by'], ['vehicle'])
        self.assertEqual(params['vehicle_id'], [str(bike_id)])
        self.assertNotIn('page', params)
        self.assertNotIn('circuit_name', parse_qs(urlsplit(captured['touring_url']).query))
        response = client.get(self.detail_url, query_string={'return_to': captured['list_url'],
                                                             'session_id': self.session_id})
        self.assertIn('href="' + captured['list_url'] + '"', unescape(response.get_data(as_text=True)))
        self.assertIn(f'id="collapseSession{self.session_id}" class="accordion-collapse collapse show"',
                      response.get_data(as_text=True))

    def test_return_url_rejects_external_and_preserves_team_navigation(self):
        self.enable_beta()
        seen = []

        def capture(sender, template, context, **extra):
            seen.append(context['back_url'])

        client = self.client_for(self.owner_id)
        with template_rendered.connected_to(capture, self.app):
            for value in ('https://outside.test/', '//outside.test/', '/\\outside.test/'):
                client.get(self.detail_url, query_string={'return_to': value})
            client.get(self.detail_url, headers={'Referer': 'http://localhost/teams/1'})
        self.assertEqual(seen[:3], ['/activity/'] * 3)
        self.assertEqual(seen[3], 'http://localhost/teams/1')

    def test_import_script_is_available_without_google_maps_in_both_uis(self):
        self.app.config['GOOGLE_MAPS_API_KEY'] = ''
        for beta in (False, True):
            with self.app.app_context():
                db.session.get(User, self.owner_id).use_beta_ui = beta
                db.session.commit()
            html = self.client_for(self.owner_id).get(self.detail_url).get_data(as_text=True)
            self.assertIn('/static/js/lap_import.js', html)

    def test_new_session_import_returns_summary_and_focused_gps_link(self):
        from test_lap_import import drogger_csv
        response = self.client_for(self.owner_id).post(f'/activity/{self.activity_id}/import_laps', data={
            'target_session': 'new', 'new_session_name': 'CSVで作成', 'device_type': 'drogger',
            'csv_file': (io.BytesIO(drogger_csv()), 'track.csv'), 'remove_outliers': 'y',
            'outlier_threshold': '2.0', 'append_mode': 'true',
        }, headers={'Accept': 'application/x-ndjson'})
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        done = events[-1]
        self.assertEqual(done['stage'], 'done')
        self.assertEqual(done['summary'], {'imported_laps': 3, 'removed_laps': 1,
                                          'gps_laps': 3, 'best_lap': '1:00.000'})
        self.assertEqual(parse_qs(urlsplit(done['gps_url']).query)['gps'], ['1'])
        self.assertEqual(urlsplit(done['redirect_url']).fragment, f"session-{done['session_id']}")
        with self.app.app_context():
            saved = db.session.get(SessionLog, done['session_id'])
            self.assertEqual(saved.activity_log_id, self.activity_id)
            self.assertEqual(saved.session_name, 'CSVで作成')
            self.assertEqual(len(saved.lap_times), 3)

    def test_invalid_new_import_and_wrong_target_do_not_create_sessions(self):
        with self.app.app_context():
            count = SessionLog.query.filter_by(activity_log_id=self.activity_id).count()
        for target, expected in (('new', 200), ('99999999', 400)):
            response = self.client_for(self.owner_id).post(f'/activity/{self.activity_id}/import_laps', data={
                'target_session': target, 'device_type': 'drogger',
                'csv_file': (io.BytesIO(b'invalid CSV'), 'track.csv'), 'outlier_threshold': '2.0',
            }, headers={'Accept': 'application/x-ndjson'})
            self.assertEqual(response.status_code, expected)
            self.assertIn('error', response.get_data(as_text=True))
            with self.app.app_context():
                self.assertEqual(SessionLog.query.filter_by(activity_log_id=self.activity_id).count(), count)
        response = self.client_for(self.member_id).post(f'/activity/{self.activity_id}/import_laps')
        self.assertEqual(response.status_code, 404)

    def test_activity_import_can_append_and_replace_the_selected_session(self):
        client = self.client_for(self.owner_id)
        for append, expected_count in (('true', 6), ('false', 2)):
            response = client.post(f'/activity/{self.activity_id}/import_laps', data={
                'target_session': str(self.session_id), 'device_type': 'simple_csv',
                'csv_file': (io.BytesIO(b'1:05.000\n1:06.000\n'), 'times.csv'),
                'outlier_threshold': '2.0', 'append_mode': append,
            }, headers={'Accept': 'application/x-ndjson'})
            done = json.loads(response.get_data(as_text=True).splitlines()[-1])
            self.assertEqual(done['stage'], 'done')
            self.assertEqual(done['session_id'], self.session_id)
            with self.app.app_context():
                saved = db.session.get(SessionLog, self.session_id)
                self.assertEqual(len(saved.lap_times), expected_count)
                self.assertEqual(bool(saved.gps_tracks), append == 'true')

    def test_beta_dashboard_links_latest_untimed_log_and_unmeasured_course(self):
        self.enable_beta()
        with self.app.app_context():
            activity = db.session.get(ActivityLog, self.activity_id)
            latest = ActivityLog(user_id=self.owner_id, motorcycle_id=activity.motorcycle_id,
                                 activity_date=date(2026, 11, 23), location_type='circuit',
                                 circuit_name=activity.circuit_name)
            unmeasured = ActivityLog(user_id=self.owner_id, motorcycle_id=activity.motorcycle_id,
                                     activity_date=date(2026, 11, 23), location_type='circuit',
                                     circuit_name='未計測コース')
            db.session.add_all([latest, unmeasured])
            db.session.commit()
            latest_id, unmeasured_id = latest.id, unmeasured.id
        seen = {}

        def capture(sender, template, context, **extra):
            seen.update(context)

        with template_rendered.connected_to(capture, self.app):
            response = self.client_for(self.owner_id).get('/circuit-dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen['circuit_data'][0]['latest_activity_id'], latest_id)
        self.assertEqual(seen['unmeasured_circuits'][0].id, unmeasured_id)
        self.assertIn('import_csv=1', response.get_data(as_text=True))

    def test_team_members_cannot_open_unshared_log_or_any_gps_variant(self):
        client = self.client_for(self.member_id)
        for url in (self.detail_url, self.gps_url, self.gps_url + '?summary=1', self.gps_url + '?lap_number=3'):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 403)

    def test_shared_log_is_visible_to_members_but_not_unrelated_users(self):
        self.set_shared(True)
        for user_id, expected in ((self.owner_id, 200), (self.member_id, 200), (self.other_id, 403)):
            for url in (self.detail_url, self.gps_url + '?summary=1', self.gps_url + '?lap_number=3'):
                with self.subTest(user_id=user_id, url=url):
                    self.assertEqual(self.client_for(user_id).get(url).status_code, expected)

    def test_owner_can_view_private_log_in_both_uis_without_loading_gps(self):
        for beta in (False, True):
            with self.app.app_context():
                db.session.get(User, self.owner_id).use_beta_ui = beta
                db.session.commit()
            seen = []

            def capture(sender, template, context, **extra):
                seen.extend((session.id, session.has_gps_tracks, inspect(session).unloaded)
                            for session in context['sessions'])

            with template_rendered.connected_to(capture, self.app):
                response = self.client_for(self.owner_id).get(self.detail_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual({row[0]: row[1] for row in seen}, {self.session_id: True, self.empty_id: False})
            self.assertTrue(all('gps_tracks' in row[2] for row in seen))

    def test_summary_contains_lap_numbers_without_track_data(self):
        response = self.client_for(self.owner_id).get(self.gps_url + '?summary=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['laps'], [{'lap_number': 3}, {'lap_number': 4}])
        self.assertEqual(len(response.json['lap_times']), 4)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_selected_lap_response_preserves_its_number_and_coordinates(self):
        response = self.client_for(self.owner_id).get(self.gps_url + '?lap_number=4')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['laps']), 1)
        lap = response.json['laps'][0]
        self.assertEqual(lap['lap_number'], 4)
        self.assertEqual(lap['track'], self.track)
        self.assertEqual(lap['map_track'], self.track)

    def test_invalid_missing_and_empty_laps(self):
        client = self.client_for(self.owner_id)
        for number, status in (('0', 400), ('-1', 400), ('bad', 400), ('3.5', 400), ('1', 404), ('999', 404)):
            self.assertEqual(client.get(self.gps_url + '?lap_number=' + number).status_code, status)
        for suffix in ('', '?summary=1', '?lap_number=1'):
            self.assertEqual(client.get(f'/activity/session/{self.empty_id}/gps_data' + suffix).status_code, 404)

    def test_legacy_full_gps_response_remains_available(self):
        response = self.client_for(self.owner_id).get(self.gps_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([lap['lap_number'] for lap in response.json['laps']], [3, 4])

    def test_lightweight_requests_do_not_hydrate_the_gps_column(self):
        loaded = []

        def capture(target, context):
            loaded.append(target)

        event.listen(SessionLog, 'load', capture)
        try:
            client = self.client_for(self.owner_id)
            for query in ('?summary=1', '?lap_number=4'):
                self.assertEqual(client.get(self.gps_url + query).status_code, 200)
        finally:
            event.remove(SessionLog, 'load', capture)
        self.assertTrue(loaded)
        self.assertTrue(all('gps_tracks' in inspect(session).unloaded for session in loaded))

    def test_dashboard_does_not_load_lap_times_or_gps_in_either_ui(self):
        for beta in (False, True):
            with self.app.app_context():
                db.session.get(User, self.owner_id).use_beta_ui = beta
                db.session.commit()
            seen = []

            def capture(sender, template, context, **extra):
                seen.extend(inspect(item['best_session']).unloaded for item in context['circuit_data'])

            with template_rendered.connected_to(capture, self.app):
                response = self.client_for(self.owner_id).get('/circuit-dashboard/')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(seen)
            self.assertTrue(all({'lap_times', 'gps_tracks'} <= fields for fields in seen))

    def test_public_link_uses_same_lightweight_api_and_honors_revocation(self):
        token = str(uuid.uuid4())
        with self.app.app_context():
            session = db.session.get(SessionLog, self.session_id)
            session.public_share_token = token
            session.is_public = True
            db.session.commit()
        client = self.client_for(None)
        url = f'/activity/share/session/{token}/gps_data'
        for suffix in ('?summary=1', '?lap_number=4', ''):
            response = client.get(url + suffix)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.app.app_context():
            db.session.get(SessionLog, self.session_id).is_public = False
            db.session.commit()
        self.assertEqual(client.get(url + '?summary=1').status_code, 404)
        self.assertEqual(client.get(url + '?lap_number=4').status_code, 404)


if __name__ == '__main__':
    unittest.main()
