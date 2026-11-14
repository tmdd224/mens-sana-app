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
                (6, 'doctor@example.test', 'Médecin', 'medecin', '', ''),
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
        connection.execute('INSERT INTO medecins(user_id,specialite) VALUES(6,?)', ('Médecine générale',))
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

    def test_professionals_can_register_and_sign_in_without_admin_approval(self):
        response, headers = server.inscription_compte(None, {
            'role': 'psychologue',
            'email': 'new.psy@example.test',
            'nom': 'Nouveau Psychologue',
            'password': 'TemporaryPass123',
            'specialite': 'Psychologie clinique',
            'annees_exp': '4',
        })

        user = server.q('SELECT id,role,actif FROM users WHERE email=?',
                        ('new.psy@example.test',), True)
        profile = server.q('SELECT specialite,annees_exp FROM psychologues WHERE user_id=?',
                           (user['id'],), True)
        self.assertEqual(response['role'], 'psychologue')
        self.assertEqual(user['actif'], 1)
        self.assertEqual(profile, {'specialite': 'Psychologie clinique', 'annees_exp': 4})
        self.assertIn('ms=', dict(headers)['Set-Cookie'])
        self.assertFalse(server.acces({'id': user['id'], 'role': 'psychologue'}, 1))

        with self.assertRaises(server.Err):
            server.inscription_compte(None, {
                'role': 'admin',
                'email': 'new.admin@example.test',
                'nom': 'Admin',
                'password': 'TemporaryPass123',
            })

    def test_registration_rejects_reserved_addresses_when_seed_accounts_are_disabled(self):
        user_count = server.q('SELECT COUNT(*) count FROM users', one=True)['count']
        with mock.patch.object(server, 'DEMO_MODE', False):
            with self.assertRaises(server.Err) as raised:
                server.inscription_compte(None, {
                    'role': 'patient',
                    'email': 'admin@menssana.sn',
                    'nom': 'Compte réservé',
                    'password': 'TemporaryPass123',
                    'date_naissance': '1990-01-01',
                })

        self.assertIn('réservée', raised.exception.m)
        self.assertEqual(server.q('SELECT COUNT(*) count FROM users', one=True)['count'], user_count)

    def test_initial_admin_is_created_from_deployment_environment(self):
        database = os.path.join(self.temp_dir.name, 'bootstrap.db')
        with mock.patch.object(server, 'DB', database), mock.patch.dict(os.environ, {
            'MENSSANA_ADMIN_EMAIL': 'initial.admin@example.test',
            'MENSSANA_ADMIN_NAME': 'Administrateur initial',
            'MENSSANA_ADMIN_PASSWORD': 'LongTemporaryPassword123',
        }):
            connection = server._c()
            connection.executescript(server.SCHEMA)
            connection.close()

            server.provision_admin()
            admin = server.q('SELECT email,nom,role FROM users WHERE role=?', ('admin',), True)

        self.assertEqual(admin, {
            'email': 'initial.admin@example.test',
            'nom': 'Administrateur initial',
            'role': 'admin',
        })

    def test_reserved_previous_admin_is_reconfigured_with_deployment_credentials(self):
        with mock.patch.object(server, 'DEMO_MODE', False), mock.patch.dict(os.environ, {
            'MENSSANA_ADMIN_EMAIL': 'replacement.admin@example.test',
            'MENSSANA_ADMIN_NAME': 'Administrateur actif',
            'MENSSANA_ADMIN_PASSWORD': 'LongTemporaryPassword123',
        }):
            server.provision_admin()
            admin = server.q('SELECT id,email,nom FROM users WHERE role=?', ('admin',), True)
            authenticated, _ = server.login(None, {
                'email': 'replacement.admin@example.test',
                'password': 'LongTemporaryPassword123',
            })

        self.assertEqual(admin['email'], 'replacement.admin@example.test')
        self.assertEqual(admin['nom'], 'Administrateur actif')
        self.assertEqual(authenticated['id'], admin['id'])
        self.assertIsNone(server.q('SELECT 1 FROM sessions WHERE token=?', ('demo-session',), True))

    def test_doctor_can_access_only_patients_assigned_to_them(self):
        doctor = {'id': 6, 'role': 'medecin'}
        admin = {'id': 5, 'role': 'admin'}

        self.assertFalse(server.acces(doctor, 1))
        server.affecter_medecin(admin, {'medecin_user_id': 6, 'patient_id': 1})

        self.assertTrue(server.acces(doctor, 1))
        self.assertFalse(server.acces(doctor, 2))
        with self.assertRaises(server.Err):
            server.evaluer(doctor, {'patient_id': 2, 'etat': 'Évaluation non autorisée'})

    def test_call_report_is_visible_only_to_assigned_care_team(self):
        appointment = server.x(
            "INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu,statut) "
            "VALUES(1,1,?,'appel','À distance','réalisé')",
            (server.now(),),
        )
        server.x('INSERT INTO seances(rdv_id,resume,date) VALUES(?,?,?)',
                 (appointment, 'Résumé réservé aux soignants', server.now()))
        server.x(
            'INSERT INTO appels(rdv_id,duree_min,statut,date,rapporte_par,rapport_bref) VALUES(?,?,?,?,?,?)',
            (appointment, 35, 'réalisé', server.now(), 4, 'Résumé réservé aux soignants'),
        )
        patient_calls = server.historique_appels({'id': 2, 'role': 'patient'}, {})
        psychologist_calls = server.historique_appels({'id': 4, 'role': 'psychologue'}, {})

        self.assertNotIn('rapport_bref', patient_calls[0])
        self.assertEqual(psychologist_calls[0]['rapport_bref'], 'Résumé réservé aux soignants')
        self.assertEqual(psychologist_calls[0]['duree_min'], 35)
        self.assertEqual(server.historique_appels({'id': 6, 'role': 'medecin'}, {}), [])
        server.affecter_medecin({'id': 5, 'role': 'admin'}, {'medecin_user_id': 6, 'patient_id': 1})
        doctor_calls = server.historique_appels({'id': 6, 'role': 'medecin'}, {})
        self.assertEqual(doctor_calls[0]['rapport_bref'], 'Résumé réservé aux soignants')

    def test_session_and_medical_assessments_are_stored_separately(self):
        appointment = server.x(
            "INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu) "
            "VALUES(1,1,?,'centre','Centre')",
            (server.now(),),
        )

        server.seance({'id': 4, 'role': 'psychologue'}, {
            'resume': 'Résumé de séance',
            'evaluation': 'Progression observée',
        }, str(appointment))

        self.assertEqual(server.q('SELECT resume FROM seances WHERE rdv_id=?',
                                  (appointment,), True)['resume'], 'Résumé de séance')
        self.assertEqual(server.q('SELECT observation FROM evaluations_psy WHERE rdv_id=?',
                                  (appointment,), True)['observation'], 'Progression observée')
        self.assertEqual(server.q('SELECT COUNT(*) n FROM evaluations', one=True)['n'], 0)

    def test_community_and_partner_pages_are_admin_managed(self):
        community = server.creer_communaute(
            {'id': 4, 'role': 'psychologue'},
            {'nom': 'Espace soutien', 'description': 'Échanges encadrés'},
        )
        self.assertTrue(community['ok'])
        self.assertEqual(server.q('SELECT nom FROM communautes WHERE nom=?',
                                  ('Espace soutien',), True)['nom'], 'Espace soutien')

        partner = server.ajouter_partenaire(
            {'id': 5, 'role': 'admin'},
            {
                'nom': 'Organisation partenaire',
                'type': 'ong',
                'description': 'Accompagnement communautaire',
                'logo_url': 'https://example.test/logo.png',
                'site_url': 'https://example.test',
            },
        )
        public_partners = server.partenaires(None, {})
        self.assertTrue(partner['ok'])
        self.assertEqual(public_partners[0]['nom'], 'Organisation partenaire')
        with self.assertRaises(server.Err):
            server.ajouter_partenaire(
                {'id': 4, 'role': 'psychologue'},
                {'nom': 'Non autorisé', 'type': 'ong'},
            )


if __name__ == '__main__':
    unittest.main()
