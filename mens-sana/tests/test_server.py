import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import server


class ServerRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = os.path.join(self.temp_dir.name, 'test.db')
        connection = server._c()
        connection.executescript(server.SCHEMA)
        connection.executemany(
            'INSERT INTO users(id,email,nom,role,pw,salt) VALUES(?,?,?,?,?,?)',
            [
                (1, 'parent@example.test', 'Parent', 'parent', '', ''),
                (2, 'minor@example.test', 'Minor', 'patient', '', ''),
                (3, 'adult@example.test', 'Adult', 'patient', '', ''),
                (4, 'psy@example.test', 'Psychologue', 'psychologue', '', ''),
                (5, 'admin@menssana.sn', 'Admin démo', 'admin', '', ''),
            ],
        )
        connection.executemany(
            'INSERT INTO patients(id,user_id,numero,date_naissance) VALUES(?,?,?,?)',
            [(1, 2, 'MS-0001', '2011-06-30'), (2, 3, 'MS-0002', '1990-06-30')],
        )
        connection.executemany(
            'INSERT INTO liens(user_id,patient_id,type,consentement) VALUES(?,?,?,?)',
            [(1, 1, 'parent', 1), (1, 2, 'parent', 1)],
        )
        connection.execute('INSERT INTO psychologues(id,user_id) VALUES(1,4)')
        connection.execute('INSERT INTO sessions(token,user_id,expire) VALUES(?,?,?)',
                           ('demo-session', 5, server.time.time() + 3600))
        connection.executemany(
            'INSERT INTO assignments(patient_id,psy_id,debut) VALUES(?,?,?)',
            [(1, 1, server.now()), (2, 1, server.now())],
        )
        self.first_slot = (dt.datetime.now() + dt.timedelta(days=2)).replace(
            hour=14, minute=0, second=0, microsecond=0
        ).strftime('%Y-%m-%dT%H:%M')
        self.overlapping_slot = (dt.datetime.strptime(self.first_slot, '%Y-%m-%dT%H:%M')
                                 + dt.timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M')
        connection.executemany(
            'INSERT INTO disponibilites(psy_id,date_heure,duree) VALUES(?,?,60)',
            [(1, self.first_slot), (1, self.overlapping_slot)],
        )
        connection.executemany(
            'INSERT INTO abonnements(patient_id,formule,debut,fin) VALUES(?,?,?,?)',
            [(1, 'normal', server.now(), '9999-12-31T23:59'),
             (2, 'normal', server.now(), '9999-12-31T23:59')],
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        server.DB = self.previous_db
        self.temp_dir.cleanup()

    def test_parent_can_access_linked_minor_but_not_adult(self):
        parent = {'id': 1, 'role': 'parent'}

        self.assertTrue(server.acces(parent, 1))
        self.assertFalse(server.acces(parent, 2))

    def test_demo_login_is_disabled_outside_demo_mode(self):
        with mock.patch.object(server, 'DEMO_MODE', False):
            with self.assertRaises(server.Err) as raised:
                server.login(None, {'email': 'admin@menssana.sn', 'password': 'Demo2026!'})

        self.assertEqual(raised.exception.c, 401)

    def test_existing_demo_session_is_disabled_outside_demo_mode(self):
        request = SimpleNamespace(headers={'Cookie': 'ms=demo-session'})

        with mock.patch.object(server, 'DEMO_MODE', False):
            self.assertIsNone(server.H.user(request))

    def test_psychologist_cannot_be_double_booked_for_overlapping_slots(self):
        first_id = server.q('SELECT id FROM disponibilites WHERE date_heure=?', (self.first_slot,), True)['id']
        overlapping_id = server.q('SELECT id FROM disponibilites WHERE date_heure=?', (self.overlapping_slot,), True)['id']
        first_patient = {'id': 2, 'role': 'patient'}
        second_patient = {'id': 3, 'role': 'patient'}

        server.rdv(first_patient, {'slot_id': first_id, 'mode': 'centre'})
        with self.assertRaises(server.Err) as raised:
            server.rdv(second_patient, {'slot_id': overlapping_id, 'mode': 'centre'})

        self.assertIn('créneau', raised.exception.m)

    def test_cancelled_booking_releases_its_slot(self):
        slot = server.q('SELECT id FROM disponibilites WHERE date_heure=?', (self.first_slot,), True)
        patient = {'id': 2, 'role': 'patient'}
        server.rdv(patient, {'slot_id': slot['id'], 'mode': 'centre'})
        appointment = server.q('SELECT id FROM rendez_vous WHERE date_heure=?', (self.first_slot,), True)

        server.annuler_rdv(patient, {}, str(appointment['id']))

        available = server.creneaux(patient, {}, '1')
        self.assertIn(slot['id'], [item['id'] for item in available])

    def test_new_patient_requires_and_stores_date_of_birth(self):
        admin = {'id': 5, 'role': 'admin'}
        data = {
            'role': 'patient',
            'email': 'new.patient@example.test',
            'nom': 'Nouveau Patient',
            'password': 'TemporaryPass123',
            'date_naissance': '2012-01-01',
        }

        server.nouvel(admin, data)
        patient = server.q(
            'SELECT p.date_naissance FROM patients p JOIN users u ON u.id=p.user_id WHERE u.email=?',
            (data['email'],),
            True,
        )

        self.assertEqual(patient['date_naissance'], data['date_naissance'])

    def test_link_creation_requires_consent_and_minor_for_parent(self):
        admin = {'id': 5, 'role': 'admin'}
        base = {'user_id': 1, 'patient_id': 1, 'type': 'parent'}

        with self.assertRaises(server.Err):
            server.lier_proche(admin, dict(base, consentement=False))
        with self.assertRaises(server.Err):
            server.lier_proche(admin, dict(base, patient_id=2, consentement=True))

        server.lier_proche(admin, dict(base, consentement=True))


if __name__ == '__main__':
    unittest.main()
