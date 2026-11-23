"""手動実行するPostgreSQL連携試験。専用DBは既存の環境変数で指定する。"""
import os
from datetime import date
import unittest
import uuid

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
