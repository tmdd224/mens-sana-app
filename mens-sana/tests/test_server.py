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
            'INSERT INTO patients(id,user_id,numero,date_naissance,sexe) VALUES(?,?,?,?,?)',
            [(1, 2, 'MS-0001', '2011-06-30', 'Homme'), (2, 3, 'MS-0002', '1990-06-30', 'Femme')],
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
        connection.execute("INSERT INTO users(id,email,nom,role,pw,salt) VALUES(7,'perso@example.test','Personnalité','personnalite','','')")
        connection.execute("INSERT INTO personnalites(id,user_id,categorie,bio) VALUES(1,7,'Artiste','Bio')")
        connection.commit()
        connection.close()
        server.ensure_schema()

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
            'sexe': 'Femme',
        }

        server.nouvel(admin, data)
        patient = server.q(
            'SELECT p.date_naissance, p.sexe FROM patients p JOIN users u ON u.id=p.user_id WHERE u.email=?',
            (data['email'],),
            True,
        )

        self.assertEqual(patient['date_naissance'], data['date_naissance'])
        self.assertEqual(patient.get('sexe'), data['sexe'])

    def test_link_creation_requires_consent_and_minor_for_parent(self):
        admin = {'id': 5, 'role': 'admin'}
        base = {'user_id': 1, 'patient_id': 1, 'type': 'parent'}

        with self.assertRaises(server.Err):
            server.lier_proche(admin, dict(base, consentement=False))
        with self.assertRaises(server.Err):
            server.lier_proche(admin, dict(base, patient_id=2, consentement=True))

        server.lier_proche(admin, dict(base, consentement=True))

    def test_professional_accounts_are_created_by_admin_not_self_registration(self):
        for role in ('psychologue', 'partenaire'):
            with self.assertRaises(server.Err):
                server.inscription_compte(None, {
                    'role': role,
                    'email': 'new.%s@example.test' % role,
                    'nom': 'Test',
                    'password': 'TemporaryPass123',
                })
        admin = {'id': 5, 'role': 'admin'}
        server.nouvel(admin, {
            'role': 'psychologue',
            'email': 'created.psy@example.test',
            'nom': 'Psy Créé',
            'password': 'TemporaryPass123',
            'specialite': 'Clinique',
            'annees_exp': '5',
        })
        user = server.q('SELECT id,role,actif FROM users WHERE email=?', ('created.psy@example.test',), True)
        self.assertEqual(user['role'], 'psychologue')
        self.assertEqual(user['actif'], 1)
        # patient can still self-register
        response, _ = server.inscription_compte(None, {
            'role': 'patient',
            'email': 'self.patient@example.test',
            'nom': 'Patient Auto',
            'password': 'TemporaryPass123',
            'date_naissance': '2000-01-01',
            'sexe': 'Femme',
        })
        self.assertEqual(response['role'], 'patient')

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
                    'sexe': 'Homme',
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

    def test_personnalite_has_no_patient_dossier_access_and_admin_creates_professional_accounts(self):
        personnalite = {'id': 7, 'role': 'personnalite'}
        admin = {'id': 5, 'role': 'admin'}

        self.assertFalse(server.acces(personnalite, 1))
        server.nouvel(admin, {
            'role': 'psychologue',
            'email': 'new.psy.admin@example.test',
            'nom': 'Psy Admin',
            'password': 'TemporaryPass123',
            'specialite': 'Clinique',
            'annees_exp': '3',
        })
        psy = server.q('SELECT role,actif FROM users WHERE email=?', ('new.psy.admin@example.test',), True)
        self.assertEqual(psy['role'], 'psychologue')
        self.assertEqual(psy['actif'], 1)
        server.nouvel(admin, {
            'role': 'personnalite',
            'email': 'star@example.test',
            'nom': 'Star',
            'password': 'TemporaryPass123',
            'categorie': 'Sportif',
            'bio': 'Ambassadeur',
        })
        perso = server.q('SELECT id FROM users WHERE email=?', ('star@example.test',), True)
        self.assertTrue(server.q('SELECT 1 FROM personnalites WHERE user_id=?', (perso['id'],), True))

    def test_call_report_is_visible_only_to_patient_and_psychologist(self):
        appointment = server.x(
            "INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu,statut) "
            "VALUES(1,1,?,'appel_video','Visio','réalisé')",
            (server.now(),),
        )
        server.x('INSERT INTO seances(rdv_id,resume,date) VALUES(?,?,?)',
                 (appointment, 'Résumé réservé aux soignants', server.now()))
        server.x(
            'INSERT INTO appels(rdv_id,duree_min,statut,date,rapporte_par,rapport_bref,mode_appel) VALUES(?,?,?,?,?,?,?)',
            (appointment, 35, 'réalisé', server.now(), 4, 'Résumé réservé aux soignants', 'video'),
        )
        patient_calls = server.historique_appels({'id': 2, 'role': 'patient'}, {})
        psychologist_calls = server.historique_appels({'id': 4, 'role': 'psychologue'}, {})

        self.assertNotIn('rapport_bref', patient_calls[0])
        self.assertEqual(patient_calls[0].get('mode_appel'), 'video')
        self.assertEqual(psychologist_calls[0]['rapport_bref'], 'Résumé réservé aux soignants')
        self.assertEqual(psychologist_calls[0]['duree_min'], 35)

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
