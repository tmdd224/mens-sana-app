#!/usr/bin/env python3
"""Mens Sana : application web (Python 3.8+, bibliothèque standard uniquement).
Lancer :  python server.py   puis ouvrir http://127.0.0.1:8000
Mot de passe de tous les comptes de démonstration : Demo2026!"""
import sqlite3, json, hashlib, secrets, os, re, time, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse

DEMO_MODE = os.environ.get('MENSSANA_DEMO') == '1'
COOKIE_SECURE = os.environ.get('MENSSANA_COOKIE_SECURE') == '1'
DEMO_EMAILS = {
    'admin@menssana.sn', 'dr.diagne@menssana.sn', 'm.seck@menssana.sn',
    'a.niang@menssana.sn', 'dr.gueye@menssana.sn', 'awa@demo.sn',
    'moussa@demo.sn', 'khady@demo.sn', 'ibrahima@demo.sn',
    'parent@demo.sn', 'parrain@demo.sn', 'partenaire@demo.sn'}
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.abspath(os.environ.get('MENSSANA_DB_PATH', os.path.join(BASE, 'mens_sana.db')))
ST = os.path.join(BASE, 'static')
CENTRE = 'Centre Mens Sana, Dakar (adresse à confirmer)'
FORMULES = {  # prix de démonstration, à fixer après étude de marché
    'normal':  {'label': 'Normal',  'prix': 10000, 'inclus': ['consultations', 'activités']},
    'premium': {'label': 'Premium', 'prix': 25000, 'inclus': ['consultations', 'activités', 'ateliers', 'programmes spéciaux']},
    'famille': {'label': 'Famille', 'prix': 40000, 'inclus': ['consultations', 'activités', 'ateliers', 'programmes spéciaux']}}
METHODES = ['Wave', 'Orange Money', 'Free Money', 'Carte bancaire']
DUREE_RDV = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, nom TEXT, role TEXT, pw TEXT, salt TEXT, actif INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE REFERENCES users(id), numero TEXT UNIQUE, date_naissance TEXT, famille TEXT);
CREATE TABLE IF NOT EXISTS psychologues(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE REFERENCES users(id), specialite TEXT, annees_exp INTEGER, langues TEXT, bio TEXT);
CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, patient_id INTEGER REFERENCES patients(id), psy_id INTEGER REFERENCES psychologues(id), debut TEXT, fin TEXT, motif TEXT);
CREATE TABLE IF NOT EXISTS groupes(id INTEGER PRIMARY KEY, nom TEXT);
CREATE TABLE IF NOT EXISTS groupe_psy(groupe_id INTEGER, psy_id INTEGER, PRIMARY KEY(groupe_id,psy_id));
CREATE TABLE IF NOT EXISTS groupe_membres(groupe_id INTEGER, patient_id INTEGER, PRIMARY KEY(groupe_id,patient_id));
CREATE TABLE IF NOT EXISTS ateliers(id INTEGER PRIMARY KEY, titre TEXT, type TEXT, date_heure TEXT, lieu TEXT, capacite INTEGER, description TEXT);
CREATE TABLE IF NOT EXISTS atelier_psy(atelier_id INTEGER, psy_id INTEGER, PRIMARY KEY(atelier_id,psy_id));
CREATE TABLE IF NOT EXISTS atelier_groupes(atelier_id INTEGER, groupe_id INTEGER, PRIMARY KEY(atelier_id,groupe_id));
CREATE TABLE IF NOT EXISTS atelier_inscriptions(atelier_id INTEGER, patient_id INTEGER, PRIMARY KEY(atelier_id,patient_id));
CREATE TABLE IF NOT EXISTS liens(user_id INTEGER, patient_id INTEGER, type TEXT, consentement INTEGER DEFAULT 0, PRIMARY KEY(user_id,patient_id,type));
CREATE TABLE IF NOT EXISTS rendez_vous(id INTEGER PRIMARY KEY, patient_id INTEGER, psy_id INTEGER, date_heure TEXT, mode TEXT, lieu TEXT, statut TEXT DEFAULT 'prévu');
CREATE UNIQUE INDEX IF NOT EXISTS uq_rdv_psy_slot ON rendez_vous(psy_id,date_heure) WHERE statut='prévu';
CREATE TABLE IF NOT EXISTS disponibilites(id INTEGER PRIMARY KEY, psy_id INTEGER NOT NULL REFERENCES psychologues(id), date_heure TEXT NOT NULL, duree INTEGER NOT NULL DEFAULT 60, actif INTEGER NOT NULL DEFAULT 1, UNIQUE(psy_id,date_heure));
CREATE TABLE IF NOT EXISTS seances(id INTEGER PRIMARY KEY, rdv_id INTEGER UNIQUE REFERENCES rendez_vous(id), resume TEXT, date TEXT);
CREATE TABLE IF NOT EXISTS programmes(id INTEGER PRIMARY KEY, nom TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS programme_psy(programme_id INTEGER, psy_id INTEGER, PRIMARY KEY(programme_id,psy_id));
CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY, patient_id INTEGER, medecin_id INTEGER, etat TEXT, programme_id INTEGER, date TEXT);
CREATE TABLE IF NOT EXISTS abonnements(id INTEGER PRIMARY KEY, patient_id INTEGER, formule TEXT, debut TEXT, fin TEXT, statut TEXT DEFAULT 'actif');
CREATE TABLE IF NOT EXISTS paiements(id INTEGER PRIMARY KEY, abonnement_id INTEGER, payeur_id INTEGER, montant INTEGER, methode TEXT, statut TEXT, ref TEXT, date TEXT);
CREATE TABLE IF NOT EXISTS communautes(id INTEGER PRIMARY KEY, nom TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS communaute_membres(communaute_id INTEGER, user_id INTEGER, PRIMARY KEY(communaute_id,user_id));
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, communaute_id INTEGER, user_id INTEGER, contenu TEXT, date TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expire REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, cible TEXT);
"""

# ---------- base de données ----------
def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def q(sql, a=(), one=False):
    c = _c()
    try:
        r = c.execute(sql, a).fetchall()
    finally:
        c.close()
    return (dict(r[0]) if r else None) if one else [dict(x) for x in r]

def x(sql, a=()):
    c = _c()
    try:
        cur = c.execute(sql, a); c.commit(); return cur.lastrowid
    finally:
        c.close()

def hp(p, salt=None):
    salt = salt or secrets.token_hex(16)
    return hashlib.pbkdf2_hmac('sha256', p.encode(), bytes.fromhex(salt), 200000).hex(), salt

def now(): return dt.datetime.now().strftime('%Y-%m-%dT%H:%M')
def plus(d, h=10): return (dt.datetime.now() + dt.timedelta(days=d)).replace(hour=h, minute=0).strftime('%Y-%m-%dT%H:%M')

class Err(Exception):
    def __init__(s, m, c=400): s.m, s.c = m, c

def audit(u, a, cible=''): x('INSERT INTO audit(ts,user_id,action,cible) VALUES(?,?,?,?)', (now(), u['id'] if u else None, a, cible))

def creer_user(email, nom, role, pw, **k):
    h, s = hp(pw)
    uid = x('INSERT INTO users(email,nom,role,pw,salt) VALUES(?,?,?,?,?)', (email.lower(), nom, role, h, s))
    if role == 'patient':
        n = q('SELECT COUNT(*) n FROM patients', one=True)['n'] + 1
        x('INSERT INTO patients(user_id,numero,date_naissance,famille) VALUES(?,?,?,?)', (uid, 'MS-%04d' % n, k['naissance'], k.get('famille', '')))
    if role == 'psychologue':
        x('INSERT INTO psychologues(user_id,specialite,annees_exp,langues,bio) VALUES(?,?,?,?,?)', (uid, k.get('specialite', 'Psychologie clinique'), k.get('exp', 1), k.get('langues', 'Français, Wolof'), k.get('bio', '')))
    return uid

def creer_creneaux_demo():
    if q('SELECT 1 FROM disponibilites LIMIT 1', one=True): return
    for psy in q('SELECT y.id FROM psychologues y JOIN users u ON u.id=y.user_id WHERE u.actif=1'):
        for days, hour in ((2, 14), (3, 10), (4, 16)):
            x('INSERT OR IGNORE INTO disponibilites(psy_id,date_heure,duree) VALUES(?,?,60)', (psy['id'], plus(days, hour)))

def seed():
    c = _c(); c.executescript(SCHEMA); c.close()
    if not DEMO_MODE: return
    if q('SELECT 1 FROM users LIMIT 1', one=True):
        creer_creneaux_demo()
        return
    pw = 'Demo2026!'; U = {}
    for e, n, r, k in [
        ('admin@menssana.sn', 'Administrateur Mens Sana', 'admin', {}),
        ('dr.diagne@menssana.sn', 'Fatima Diagne', 'psychologue', dict(specialite='Psychologie clinique, anxiété et stress', exp=12, langues='Français, Wolof', bio='Douze ans de pratique en milieu hospitalier et en cabinet.')),
        ('m.seck@menssana.sn', 'Mamadou Seck', 'psychologue', dict(specialite='Thérapies brèves, jeunes adultes', exp=7, langues='Français, Wolof, Pulaar', bio='Accompagne les étudiants et jeunes actifs.')),
        ('a.niang@menssana.sn', 'Aïssatou Niang', 'psychologue', dict(specialite='Enfants et adolescents', exp=9, langues='Français, Wolof, Sérère', bio='Spécialiste du suivi des mineurs et des familles.')),
        ('dr.gueye@menssana.sn', 'Cheikh Gueye', 'medecin', {}),
        ('awa@demo.sn', 'Awa Sow', 'patient', dict(naissance='1998-04-12', famille='Vit avec sa mère et deux sœurs.')),
        ('moussa@demo.sn', 'Moussa Fall', 'patient', dict(naissance='1995-09-03', famille='Célibataire, famille à Kaolack.')),
        ('khady@demo.sn', 'Khady Ba', 'patient', dict(naissance='2001-01-22', famille='Étudiante, vit en résidence.')),
        ('ibrahima@demo.sn', 'Ibrahima Sarr', 'patient', dict(naissance='2011-06-30', famille='Mineur, vit avec sa mère.')),
        ('parent@demo.sn', 'Ndèye Sarr', 'parent', {}),
        ('parrain@demo.sn', 'Oumar Ndao', 'parrain', {}),
        ('partenaire@demo.sn', 'Fondation Teranga', 'partenaire', {})]:
        U[e.split('@')[0]] = creer_user(e, n, r, pw, **k)
    P = {n: q('SELECT id FROM patients WHERE user_id=?', (U[n],), True)['id'] for n in ('awa', 'moussa', 'khady', 'ibrahima')}
    Y = {n: q('SELECT id FROM psychologues WHERE user_id=?', (U[n],), True)['id'] for n in ('dr.diagne', 'm.seck', 'a.niang')}
    x('INSERT INTO assignments(patient_id,psy_id,debut,fin,motif) VALUES(?,?,?,?,?)', (P['khady'], Y['a.niang'], plus(-120), plus(-30), 'Changement : nouveau stade d’avancement'))
    for p, y, d in [('awa', 'dr.diagne', -60), ('moussa', 'dr.diagne', -45), ('khady', 'm.seck', -30), ('ibrahima', 'a.niang', -20)]:
        x('INSERT INTO assignments(patient_id,psy_id,debut) VALUES(?,?,?)', (P[p], Y[y], plus(d)))
    for u, p, t, c_ in [('parent', 'ibrahima', 'parent', 1), ('parrain', 'moussa', 'parrain', 1), ('partenaire', 'khady', 'partenaire', 1), ('partenaire', 'awa', 'partenaire', 0)]:
        x('INSERT INTO liens VALUES(?,?,?,?)', (U[u], P[p], t, c_))
    g1 = x('INSERT INTO groupes(nom) VALUES(?)', ('Groupe stress et anxiété',)); g2 = x('INSERT INTO groupes(nom) VALUES(?)', ('Groupe adolescents',))
    for g, y in [(g1, 'dr.diagne'), (g1, 'm.seck'), (g2, 'a.niang')]: x('INSERT INTO groupe_psy VALUES(?,?)', (g, Y[y]))
    for g, p in [(g1, 'awa'), (g1, 'moussa'), (g2, 'ibrahima')]: x('INSERT INTO groupe_membres VALUES(?,?)', (g, P[p]))
    for t, ty, d, cap, desc, ys, gs in [
        ('Gérer son stress au quotidien', 'groupe', plus(5, 15), 12, 'Techniques de respiration et d’ancrage, en petit groupe.', ['dr.diagne', 'm.seck'], [g1]),
        ('Écrire pour dire (atelier individuel)', 'individuel', plus(8, 11), 1, 'Atelier d’expression écrite guidé.', ['m.seck'], []),
        ('Adolescents : confiance en soi', 'groupe', plus(10, 16), 10, 'Atelier de parole pour les 12–17 ans.', ['a.niang'], [g2])]:
        a = x('INSERT INTO ateliers(titre,type,date_heure,lieu,capacite,description) VALUES(?,?,?,?,?,?)', (t, ty, d, CENTRE, cap, desc))
        for y in ys: x('INSERT INTO atelier_psy VALUES(?,?)', (a, Y[y]))
        for g in gs: x('INSERT INTO atelier_groupes VALUES(?,?)', (a, g))
    pr = [x('INSERT INTO programmes(nom,description) VALUES(?,?)', v) for v in [('Soutien après un traumatisme', 'Suivi renforcé, séances rapprochées.'), ('Gestion de l’anxiété', 'Parcours de 8 semaines : séances et ateliers.'), ('Accompagnement adolescents', 'Suivi du mineur avec la famille.')]]
    for p, y in [(pr[0], 'dr.diagne'), (pr[1], 'dr.diagne'), (pr[1], 'm.seck'), (pr[2], 'a.niang')]: x('INSERT INTO programme_psy VALUES(?,?)', (p, Y[y]))
    x('INSERT INTO evaluations(patient_id,medecin_id,etat,programme_id,date) VALUES(?,?,?,?,?)', (P['awa'], U['dr.gueye'], 'Anxiété modérée, suivi renforcé', pr[1], plus(-10)))
    x('INSERT INTO evaluations(patient_id,medecin_id,etat,programme_id,date) VALUES(?,?,?,?,?)', (P['ibrahima'], U['dr.gueye'], 'Isolement scolaire, accompagnement famille', pr[2], plus(-8)))
    for p, y, d, m, l in [('awa', 'dr.diagne', 3, 'centre', CENTRE), ('moussa', 'dr.diagne', 4, 'appel', 'À organiser manuellement — aucun lien d’appel généré'), ('khady', 'm.seck', 6, 'centre', CENTRE), ('ibrahima', 'a.niang', 7, 'centre', CENTRE)]:
        x('INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu) VALUES(?,?,?,?,?)', (P[p], Y[y], plus(d, 9), m, l))
    r = x('INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu,statut) VALUES(?,?,?,?,?,?)', (P['awa'], Y['dr.diagne'], plus(-7, 9), 'centre', CENTRE, 'réalisé'))
    x('INSERT INTO seances(rdv_id,resume,date) VALUES(?,?,?)', (r, 'Première séance : mise en place d’un suivi, travail sur la respiration.', plus(-7, 10)))
    for p, f, payer, m in [('awa', 'premium', 'awa', 'Wave'), ('moussa', 'normal', 'parrain', 'Orange Money'), ('ibrahima', 'famille', 'parent', 'Wave')]:
        a = x('INSERT INTO abonnements(patient_id,formule,debut,fin) VALUES(?,?,?,?)', (P[p], f, plus(-20), plus(10)))
        x('INSERT INTO paiements(abonnement_id,payeur_id,montant,methode,statut,ref,date) VALUES(?,?,?,?,?,?,?)', (a, U[payer], FORMULES[f]['prix'], m, 'payé', 'DEMO-' + secrets.token_hex(3).upper(), plus(-20)))
    cm = [x('INSERT INTO communautes(nom,description) VALUES(?,?)', v) for v in [('Parler sans filtre', 'Un espace de discussion bienveillant, ouvert à tous.'), ('Étudiants', 'Stress des examens, vie étudiante, orientation.'), ('Familles et proches', 'Comprendre et soutenir un proche.')]]
    for c_, u in [(0, 'awa'), (0, 'moussa'), (0, 'khady'), (1, 'khady'), (2, 'parent'), (0, 'dr.diagne')]: x('INSERT INTO communaute_membres VALUES(?,?)', (cm[c_], U[u]))
    for c_, u, t in [(0, 'moussa', 'Bonjour à tous. Aujourd’hui, j’ai réussi à sortir me promener un peu. Petit pas, mais un pas.'), (0, 'dr.diagne', 'Bravo. Les petits pas comptent. N’hésitez pas à partager ce qui vous aide.'), (1, 'khady', 'Quelqu’un a des astuces pour la période des examens ?')]:
        x('INSERT INTO posts(communaute_id,user_id,contenu,date) VALUES(?,?,?,?)', (cm[c_], U[u], t, plus(-1)))
    creer_creneaux_demo()

# ---------- droits d'accès ----------
def pat_of(u): return q('SELECT * FROM patients WHERE user_id=?', (u['id'],), True)
def psy_of(u): return q('SELECT * FROM psychologues WHERE user_id=?', (u['id'],), True)

def acces(u, pid):
    r = u['role']
    if r in ('admin', 'medecin'): return True
    if r == 'patient': p = pat_of(u); return bool(p and p['id'] == pid)
    if r == 'psychologue':
        y = psy_of(u); return bool(y and q('SELECT 1 FROM assignments WHERE patient_id=? AND psy_id=? AND fin IS NULL', (pid, y['id']), True))
    if r in ('parrain', 'partenaire'): return bool(q('SELECT 1 FROM liens WHERE user_id=? AND patient_id=? AND type=? AND consentement=1', (u['id'], pid, r), True))
    if r == 'parent':
        p = q('SELECT p.date_naissance FROM liens l JOIN patients p ON p.id=l.patient_id WHERE l.user_id=? AND l.patient_id=? AND l.type=? AND l.consentement=1', (u['id'], pid, r), True)
        return bool(p and age(p['date_naissance']) < 18)
    return False

def cible(u, b):
    """Patient visé : le sien, ou celui indiqué si l'accès est autorisé."""
    if u['role'] == 'patient': return pat_of(u)['id']
    pid = b.get('patient_id')
    if not isinstance(pid, int) or not acces(u, pid): raise Err('Patient non autorisé', 403)
    return pid

def age(d):
    n = dt.date.today(); y, m, j = map(int, d.split('-')); return n.year - y - ((n.month, n.day) < (m, j))

def date_future(value):
    try: scheduled = dt.datetime.strptime(str(value), '%Y-%m-%dT%H:%M')
    except ValueError: raise Err('Date invalide')
    if scheduled <= dt.datetime.now().replace(second=0, microsecond=0): raise Err('Choisissez une date future')
    if scheduled.minute % 15: raise Err('Choisissez un horaire par tranche de 15 minutes')
    return scheduled

def est_mineur(pid):
    p = q('SELECT date_naissance FROM patients WHERE id=?', (pid,), True)
    return bool(p and age(p['date_naissance']) < 18)

def abo(pid):
    a = q("SELECT * FROM abonnements WHERE patient_id=? AND statut='actif' AND fin>=? ORDER BY id DESC LIMIT 1", (pid, now()), True)
    if a: a.update(FORMULES[a['formule']])
    return a

def exige(pid, service):
    a = abo(pid)
    if not a or service not in a['inclus']: raise Err('Votre abonnement ne couvre pas ce service : « %s ». Voir l’onglet Abonnement.' % service, 402)

def suivi(pid):
    return {'rdv': q('SELECT r.id,r.date_heure,r.mode,r.lieu,r.statut,u.nom psy FROM rendez_vous r JOIN psychologues y ON y.id=r.psy_id JOIN users u ON u.id=y.user_id WHERE r.patient_id=? ORDER BY r.date_heure DESC', (pid,)),
            'ateliers': q('SELECT a.titre,a.type,a.date_heure FROM atelier_inscriptions i JOIN ateliers a ON a.id=i.atelier_id WHERE i.patient_id=? ORDER BY a.date_heure', (pid,)),
            'groupes': q('SELECT g.nom FROM groupe_membres m JOIN groupes g ON g.id=m.groupe_id WHERE m.patient_id=?', (pid,)),
            'evaluations': q('SELECT e.date,e.etat,p.nom programme FROM evaluations e LEFT JOIN programmes p ON p.id=e.programme_id WHERE e.patient_id=? ORDER BY e.id DESC', (pid,)),
            'abonnement': abo(pid)}

def fiche(u, pid):
    p = q('SELECT p.id,p.numero,p.date_naissance,p.famille,u.nom FROM patients p JOIN users u ON u.id=p.user_id WHERE p.id=?', (pid,), True)
    p['age'] = age(p['date_naissance']); p['mineur'] = p['age'] < 18
    if u['role'] not in ('psychologue', 'medecin', 'patient', 'parent'): p['famille'] = None
    p['psy'] = q('SELECT y.id,u.nom,y.specialite,y.annees_exp FROM assignments a JOIN psychologues y ON y.id=a.psy_id JOIN users u ON u.id=y.user_id WHERE a.patient_id=? AND a.fin IS NULL', (pid,), True)
    p['historique'] = q('SELECT a.debut,a.fin,a.motif,u.nom psy FROM assignments a JOIN psychologues y ON y.id=a.psy_id JOIN users u ON u.id=y.user_id WHERE a.patient_id=? ORDER BY a.id DESC', (pid,))
    p.update(suivi(pid))
    if u['role'] == 'psychologue': p['seances'] = q('SELECT s.resume,r.date_heure FROM seances s JOIN rendez_vous r ON r.id=s.rdv_id WHERE r.patient_id=? ORDER BY r.date_heure DESC', (pid,))
    return p

def affecter(pid, yid, motif):
    if q('SELECT 1 FROM assignments WHERE patient_id=? AND psy_id=? AND fin IS NULL', (pid, yid), True): raise Err('Ce psychologue suit déjà ce patient')
    x('UPDATE assignments SET fin=? WHERE patient_id=? AND fin IS NULL', (now(), pid))
    x('INSERT INTO assignments(patient_id,psy_id,debut,motif) VALUES(?,?,?,?)', (pid, yid, now(), motif))

# ---------- routes ----------
R = []
def route(m, p, roles='*'):
    def d(f): R.append((m, re.compile('^' + p + '$'), roles, f)); return f
    return d

LOCK = {}
@route('POST', '/login', None)
def login(u, b):
    e = str(b.get('email', '')).lower().strip(); k = LOCK.get(e, (0, 0))
    if not DEMO_MODE and e in DEMO_EMAILS: raise Err('Identifiants incorrects', 401)
    if k[1] > time.time(): raise Err('Trop de tentatives. Réessayez dans une minute.', 429)
    r = q('SELECT * FROM users WHERE email=? AND actif=1', (e,), True)
    if not r or not secrets.compare_digest(hp(str(b.get('password', '')), r['salt'])[0], r['pw']):
        n = k[0] + 1; LOCK[e] = (n, time.time() + 60 if n >= 5 else 0); audit(None, 'connexion refusée', e); raise Err('Identifiants incorrects', 401)
    LOCK.pop(e, None); t = secrets.token_urlsafe(32)
    x('INSERT INTO sessions VALUES(?,?,?)', (t, r['id'], time.time() + 28800)); audit(r, 'connexion')
    secure = '; Secure' if COOKIE_SECURE else ''
    return {'id': r['id'], 'nom': r['nom'], 'role': r['role']}, [('Set-Cookie', 'ms=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800%s' % (t, secure))]

@route('POST', '/logout')
def logout(u, b):
    x('DELETE FROM sessions WHERE user_id=?', (u['id'],)); audit(u, 'déconnexion')
    secure = '; Secure' if COOKIE_SECURE else ''
    return {'ok': 1}, [('Set-Cookie', 'ms=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0%s' % secure)]

@route('GET', '/config', None)
def config(u, b): return {'demo': DEMO_MODE}

@route('GET', '/me')
def me(u, b): return {'id': u['id'], 'nom': u['nom'], 'role': u['role']}

@route('GET', '/formules')
def formules(u, b): return {'formules': FORMULES, 'methodes': METHODES}

@route('GET', '/psychologues')
def psychologues(u, b):
    return q('SELECT y.id,u.nom,y.specialite,y.annees_exp,y.langues,y.bio,(SELECT COUNT(*) FROM assignments a WHERE a.psy_id=y.id AND a.fin IS NULL) patients FROM psychologues y JOIN users u ON u.id=y.user_id WHERE u.actif=1')

@route('GET', '/patient/home', ['patient'])
def phome(u, b): return fiche(u, pat_of(u)['id'])

@route('GET', '/creneaux/(\\d+)', ['patient', 'parent'])
def creneaux(u, b, pid):
    pid = int(pid)
    if not acces(u, pid): raise Err('Patient non autorisé', 403)
    assignment = q('SELECT psy_id FROM assignments WHERE patient_id=? AND fin IS NULL', (pid,), True)
    if not assignment: return []
    return q("""SELECT d.id,d.date_heure,d.duree
        FROM disponibilites d
        WHERE d.psy_id=? AND d.actif=1 AND datetime(d.date_heure)>=datetime(?)
        AND NOT EXISTS (
            SELECT 1 FROM rendez_vous r WHERE r.psy_id=d.psy_id AND r.statut='prévu'
            AND datetime(r.date_heure)<datetime(d.date_heure,'+'||d.duree||' minutes')
            AND datetime(r.date_heure,'+'||?||' minutes')>datetime(d.date_heure))
        ORDER BY d.date_heure""", (assignment['psy_id'], now(), DUREE_RDV))

@route('GET', '/psy/creneaux', ['psychologue'])
def psy_creneaux(u, b):
    y = psy_of(u)
    return q("""SELECT d.id,d.date_heure,d.duree,d.actif,
        r.id rdv_id,pu.nom patient
        FROM disponibilites d
        LEFT JOIN rendez_vous r ON r.psy_id=d.psy_id AND r.date_heure=d.date_heure AND r.statut='prévu'
        LEFT JOIN patients p ON p.id=r.patient_id
        LEFT JOIN users pu ON pu.id=p.user_id
        WHERE d.psy_id=? AND datetime(d.date_heure)>=datetime(?)
        ORDER BY d.date_heure""", (y['id'], now()))

@route('POST', '/psy/creneaux', ['psychologue'])
def ajouter_creneau(u, b):
    scheduled = date_future(b.get('date_heure', ''))
    y = psy_of(u)
    start = scheduled.strftime('%Y-%m-%dT%H:%M')
    c = _c()
    try:
        c.execute('BEGIN IMMEDIATE')
        overlap = c.execute("""SELECT 1 FROM disponibilites
            WHERE psy_id=? AND actif=1
            AND datetime(date_heure)<datetime(?,'+60 minutes')
            AND datetime(date_heure,'+'||duree||' minutes')>datetime(?) LIMIT 1""",
            (y['id'], start, start)).fetchone()
        booked = c.execute("""SELECT 1 FROM rendez_vous
            WHERE psy_id=? AND statut='prévu'
            AND datetime(date_heure)<datetime(?,'+60 minutes')
            AND datetime(date_heure,'+60 minutes')>datetime(?) LIMIT 1""",
            (y['id'], start, start)).fetchone()
        if overlap or booked: raise Err('Ce créneau chevauche une disponibilité ou un rendez-vous existant')
        c.execute('INSERT INTO disponibilites(psy_id,date_heure,duree) VALUES(?,?,?)', (y['id'], start, DUREE_RDV))
        c.commit()
    except sqlite3.IntegrityError:
        c.rollback()
        raise Err('Ce créneau existe déjà')
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    audit(u, 'créneau ajouté', start); return {'ok': 1}

@route('POST', '/psy/creneaux/(\\d+)/annuler', ['psychologue'])
def annuler_creneau(u, b, slot_id):
    y = psy_of(u); slot_id = int(slot_id)
    c = _c()
    try:
        c.execute('BEGIN IMMEDIATE')
        slot = c.execute('SELECT * FROM disponibilites WHERE id=? AND psy_id=? AND actif=1', (slot_id, y['id'])).fetchone()
        if not slot: raise Err('Créneau introuvable')
        booked = c.execute("SELECT 1 FROM rendez_vous WHERE psy_id=? AND date_heure=? AND statut='prévu'", (y['id'], slot['date_heure'])).fetchone()
        if booked: raise Err('Un patient a déjà réservé ce créneau')
        c.execute('UPDATE disponibilites SET actif=0 WHERE id=?', (slot_id,))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    audit(u, 'créneau retiré', slot['date_heure']); return {'ok': 1}

@route('POST', '/rdv', ['patient', 'parent', 'psychologue'])
def rdv(u, b):
    pid = cible(u, b); slot_id = b.get('slot_id'); mode = b.get('mode')
    if not isinstance(slot_id, int): raise Err('Choisissez un créneau disponible')
    if mode not in ('centre', 'appel'): raise Err('Mode invalide')
    exige(pid, 'consultations')
    c = _c()
    try:
        c.execute('BEGIN IMMEDIATE')
        psy = c.execute('SELECT psy_id FROM assignments WHERE patient_id=? AND fin IS NULL', (pid,)).fetchone()
        if not psy: raise Err('Aucun psychologue affecté')
        slot = c.execute("SELECT * FROM disponibilites WHERE id=? AND psy_id=? AND actif=1", (slot_id, psy['psy_id'])).fetchone()
        if not slot: raise Err('Ce créneau n’est plus disponible')
        scheduled = date_future(slot['date_heure'])
        end = (scheduled + dt.timedelta(minutes=slot['duree'])).strftime('%Y-%m-%dT%H:%M')
        occupied = c.execute("""SELECT 1 FROM rendez_vous
            WHERE psy_id=? AND statut='prévu'
            AND datetime(date_heure)<datetime(?)
            AND datetime(date_heure,'+60 minutes')>datetime(?) LIMIT 1""",
            (psy['psy_id'], end, slot['date_heure'])).fetchone()
        if occupied: raise Err('Ce créneau n’est plus disponible')
        lieu = CENTRE if mode == 'centre' else 'À organiser manuellement — aucun lien d’appel généré'
        c.execute('INSERT INTO rendez_vous(patient_id,psy_id,date_heure,mode,lieu) VALUES(?,?,?,?,?)', (pid, psy['psy_id'], slot['date_heure'], mode, lieu))
        c.commit()
    except sqlite3.IntegrityError:
        c.rollback()
        raise Err('Ce créneau n’est plus disponible')
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    audit(u, 'rendez-vous créé', 'patient %d' % pid); return {'ok': 1}

@route('POST', '/rdv/(\\d+)/annuler', ['patient', 'parent'])
def annuler_rdv(u, b, rid):
    r = q('SELECT * FROM rendez_vous WHERE id=?', (int(rid),), True)
    if not r or not acces(u, r['patient_id']): raise Err('Accès refusé', 403)
    if r['statut'] != 'prévu': raise Err('Ce rendez-vous ne peut plus être annulé')
    if dt.datetime.strptime(r['date_heure'], '%Y-%m-%dT%H:%M') <= dt.datetime.now(): raise Err('Un rendez-vous passé ne peut pas être annulé')
    x("UPDATE rendez_vous SET statut='annulé' WHERE id=?", (r['id'],))
    audit(u, 'rendez-vous annulé', 'rdv %d' % r['id']); return {'ok': 1}

@route('POST', '/rdv/(\\d+)/seance', ['psychologue'])
def seance(u, b, rid):
    r = q('SELECT * FROM rendez_vous WHERE id=?', (int(rid),), True)
    if not r or not acces(u, r['patient_id']): raise Err('Accès refusé', 403)
    t = str(b.get('resume', '')).strip()[:2000]
    if not t: raise Err('Résumé vide')
    x("UPDATE rendez_vous SET statut='réalisé' WHERE id=?", (r['id'],))
    x('INSERT OR REPLACE INTO seances(rdv_id,resume,date) VALUES(?,?,?)', (r['id'], t, now())); audit(u, 'séance enregistrée', 'rdv %d' % r['id']); return {'ok': 1}

@route('POST', '/changer-psy', ['patient'])
def changer(u, b):
    pid = pat_of(u)['id']
    if not q('SELECT 1 FROM psychologues y JOIN users u ON u.id=y.user_id WHERE y.id=? AND u.actif=1', (b.get('psy_id'),), True): raise Err('Psychologue inconnu ou inactif')
    affecter(pid, b['psy_id'], str(b.get('motif', ''))[:200]); audit(u, 'changement de psychologue', 'patient %d' % pid); return {'ok': 1}

@route('GET', '/ateliers')
def ateliers(u, b):
    A = q("SELECT * FROM ateliers WHERE date_heure>=? ORDER BY date_heure", (now(),))
    p = pat_of(u) if u['role'] == 'patient' else None
    for a in A:
        a['animateurs'] = [r['nom'] for r in q('SELECT u.nom FROM atelier_psy s JOIN psychologues y ON y.id=s.psy_id JOIN users u ON u.id=y.user_id WHERE s.atelier_id=?', (a['id'],))]
        a['groupes'] = [r['nom'] for r in q('SELECT g.nom FROM atelier_groupes s JOIN groupes g ON g.id=s.groupe_id WHERE s.atelier_id=?', (a['id'],))]
        a['inscrits'] = q('SELECT COUNT(*) n FROM atelier_inscriptions WHERE atelier_id=?', (a['id'],), True)['n']
        a['inscrit'] = bool(p and q('SELECT 1 FROM atelier_inscriptions WHERE atelier_id=? AND patient_id=?', (a['id'], p['id']), True))
    if u['role'] == 'psychologue':
        y = psy_of(u); A = [a for a in A if q('SELECT 1 FROM atelier_psy WHERE atelier_id=? AND psy_id=?', (a['id'], y['id']), True)]
    return A

@route('POST', '/ateliers/(\\d+)/inscrire', ['patient', 'parent'])
def inscrire(u, b, aid):
    pid = cible(u, b); a = q('SELECT * FROM ateliers WHERE id=?', (int(aid),), True)
    if not a: raise Err('Atelier inconnu', 404)
    exige(pid, 'ateliers')
    c = _c()
    try:
        c.execute('BEGIN IMMEDIATE')
        inscrit = c.execute('SELECT 1 FROM atelier_inscriptions WHERE atelier_id=? AND patient_id=?', (a['id'], pid)).fetchone()
        if not inscrit:
            places = c.execute('SELECT COUNT(*) FROM atelier_inscriptions WHERE atelier_id=?', (a['id'],)).fetchone()[0]
            if places >= a['capacite']: raise Err('Atelier complet')
            c.execute('INSERT INTO atelier_inscriptions VALUES(?,?)', (a['id'], pid))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    audit(u, 'inscription atelier', 'atelier %d' % a['id']); return {'ok': 1}

@route('POST', '/abonnement', ['patient', 'parent', 'parrain', 'partenaire'])
def abonner(u, b):
    pid = cible(u, b); f = b.get('formule'); m = b.get('methode')
    if f not in FORMULES or m not in METHODES: raise Err('Formule ou moyen de paiement invalide')
    # Démonstration : le paiement est simulé. En production, appeler l'agrégateur de paiement et attendre sa confirmation.
    a = x('INSERT INTO abonnements(patient_id,formule,debut,fin) VALUES(?,?,?,?)', (pid, f, now(), plus(30)))
    x('INSERT INTO paiements(abonnement_id,payeur_id,montant,methode,statut,ref,date) VALUES(?,?,?,?,?,?,?)', (a, u['id'], FORMULES[f]['prix'], m, 'payé (simulation)', 'SIM-' + secrets.token_hex(4).upper(), now()))
    audit(u, 'abonnement souscrit', 'patient %d, %s' % (pid, f)); return {'ok': 1}

@route('GET', '/paiements')
def paiements(u, b):
    p = pat_of(u) if u['role'] == 'patient' else None
    return q('SELECT pa.date,pa.montant,pa.methode,pa.statut,pa.ref,a.formule,pt.numero,pu.nom payeur FROM paiements pa JOIN abonnements a ON a.id=pa.abonnement_id JOIN patients pt ON pt.id=a.patient_id JOIN users pu ON pu.id=pa.payeur_id WHERE pa.payeur_id=? OR a.patient_id=? ORDER BY pa.id DESC', (u['id'], p['id'] if p else -1))

@route('GET', '/psy/home', ['psychologue'])
def phome2(u, b):
    y = psy_of(u)
    return {'patients': [dict(r, age=age(r['date_naissance'])) for r in q('SELECT p.id,p.numero,p.date_naissance,u.nom,(SELECT e.etat FROM evaluations e WHERE e.patient_id=p.id ORDER BY e.id DESC LIMIT 1) etat,(SELECT MIN(r.date_heure) FROM rendez_vous r WHERE r.patient_id=p.id AND r.statut="prévu" AND r.date_heure>=?) prochain FROM assignments a JOIN patients p ON p.id=a.patient_id JOIN users u ON u.id=p.user_id WHERE a.psy_id=? AND a.fin IS NULL', (now(), y['id']))],
            'rdv': q('SELECT r.id,r.date_heure,r.mode,r.statut,u.nom patient,p.numero FROM rendez_vous r JOIN patients p ON p.id=r.patient_id JOIN users u ON u.id=p.user_id WHERE r.psy_id=? ORDER BY r.date_heure DESC', (y['id'],)),
            'groupes': q('SELECT g.id,g.nom,(SELECT COUNT(*) FROM groupe_membres m WHERE m.groupe_id=g.id) membres FROM groupe_psy s JOIN groupes g ON g.id=s.groupe_id WHERE s.psy_id=?', (y['id'],))}

@route('GET', '/patients/(\\d+)')
def getpatient(u, b, pid):
    pid = int(pid)
    if not acces(u, pid) or u['role'] == 'admin': raise Err('Accès refusé', 403)
    audit(u, 'consultation de fiche', 'patient %d' % pid); return fiche(u, pid)

@route('GET', '/patients', ['medecin', 'admin'])
def patients(u, b):
    return [dict(r, age=age(r['date_naissance'])) for r in q('SELECT p.id,p.numero,p.date_naissance,u.nom,(SELECT e.etat FROM evaluations e WHERE e.patient_id=p.id ORDER BY e.id DESC LIMIT 1) etat,(SELECT un.nom FROM assignments a JOIN psychologues y ON y.id=a.psy_id JOIN users un ON un.id=y.user_id WHERE a.patient_id=p.id AND a.fin IS NULL) psy FROM patients p JOIN users u ON u.id=p.user_id')]

@route('GET', '/programmes', ['medecin', 'admin', 'psychologue'])
def programmes(u, b):
    P = q('SELECT * FROM programmes')
    for p in P: p['psychologues'] = [r['nom'] for r in q('SELECT u.nom FROM programme_psy s JOIN psychologues y ON y.id=s.psy_id JOIN users u ON u.id=y.user_id WHERE s.programme_id=?', (p['id'],))]; p['patients'] = q('SELECT COUNT(DISTINCT patient_id) n FROM evaluations WHERE programme_id=?', (p['id'],), True)['n']
    return P

@route('POST', '/evaluations', ['medecin'])
def evaluer(u, b):
    etat = str(b.get('etat', '')).strip()[:300]
    if not etat or not q('SELECT 1 FROM patients WHERE id=?', (b.get('patient_id'),), True): raise Err('Patient ou état manquant')
    x('INSERT INTO evaluations(patient_id,medecin_id,etat,programme_id,date) VALUES(?,?,?,?,?)', (b['patient_id'], u['id'], etat, b.get('programme_id') or None, now()))
    audit(u, 'évaluation médicale', 'patient %s' % b['patient_id']); return {'ok': 1}

@route('GET', '/suivi', ['parent', 'parrain', 'partenaire'])
def suivi_famille(u, b):
    out = []
    for l in q('SELECT patient_id,consentement,type FROM liens WHERE user_id=? AND type=?', (u['id'], u['role'])):
        if l['type'] != 'parent' and not l['consentement']: continue
        if l['type'] == 'parent' and not acces(u, l['patient_id']): continue
        p = fiche(u, l['patient_id']); out.append(p)
    audit(u, 'suivi consulté'); return out

@route('GET', '/communautes')
def comms(u, b): return q('SELECT c.*,(SELECT COUNT(*) FROM communaute_membres m WHERE m.communaute_id=c.id) membres,EXISTS(SELECT 1 FROM communaute_membres m WHERE m.communaute_id=c.id AND m.user_id=?) membre FROM communautes c', (u['id'],))

@route('POST', '/communautes/(\\d+)/rejoindre')
def rejoindre(u, b, cid): x('INSERT OR IGNORE INTO communaute_membres VALUES(?,?)', (int(cid), u['id'])); return {'ok': 1}

@route('GET', '/communautes/(\\d+)/posts')
def posts(u, b, cid):
    if not q('SELECT 1 FROM communaute_membres WHERE communaute_id=? AND user_id=?', (int(cid), u['id']), True): raise Err('Rejoignez la communauté pour lire les échanges', 403)
    return q("SELECT p.id,p.contenu,p.date,substr(u.nom,1,instr(u.nom||' ',' ')-1) auteur FROM posts p JOIN users u ON u.id=p.user_id WHERE p.communaute_id=? ORDER BY p.id DESC LIMIT 50", (int(cid),))

@route('POST', '/communautes/(\\d+)/posts')
def poster(u, b, cid):
    t = str(b.get('contenu', '')).strip()[:1000]
    if not t or not q('SELECT 1 FROM communaute_membres WHERE communaute_id=? AND user_id=?', (int(cid), u['id']), True): raise Err('Message impossible')
    x('INSERT INTO posts(communaute_id,user_id,contenu,date) VALUES(?,?,?,?)', (int(cid), u['id'], t, now())); return {'ok': 1}

@route('GET', '/admin/stats', ['admin'])
def stats(u, b):
    n = lambda s: q(s, one=True)['n']
    return {'patients': n('SELECT COUNT(*) n FROM patients'), 'psychologues': n('SELECT COUNT(*) n FROM psychologues'), 'rdv_a_venir': n("SELECT COUNT(*) n FROM rendez_vous WHERE statut='prévu'"), 'abonnements': n("SELECT COUNT(*) n FROM abonnements WHERE statut='actif'"),
            'revenus': n("SELECT COALESCE(SUM(montant),0) n FROM paiements WHERE statut LIKE 'payé%'"), 'ateliers': n('SELECT COUNT(*) n FROM ateliers')}

@route('GET', '/admin/users', ['admin'])
def users(u, b): return q('SELECT id,email,nom,role,actif FROM users ORDER BY id')

@route('POST', '/admin/users', ['admin'])
def nouvel(u, b):
    role = b.get('role'); email = str(b.get('email', '')).strip().lower(); nom = str(b.get('nom', '')).strip()
    password = str(b.get('password', ''))
    if role not in ('patient', 'psychologue', 'medecin', 'parent', 'parrain', 'partenaire', 'admin') or len(password) < 10: raise Err('Rôle invalide ou mot de passe trop court (10 caractères minimum)')
    if not re.match(r'^[^@\s]+@[^@\s]+\.\w+$', email) or not nom: raise Err('E-mail ou nom invalide')
    if q('SELECT 1 FROM users WHERE email=?', (email,), True): raise Err('E-mail déjà utilisé')
    extra = {}
    if role == 'patient':
        naissance = str(b.get('date_naissance', '')).strip()
        try: naissance_date = dt.date.fromisoformat(naissance)
        except ValueError: raise Err('Date de naissance invalide')
        if naissance_date > dt.date.today(): raise Err('La date de naissance ne peut pas être future')
        extra['naissance'] = naissance
    try:
        creer_user(email, nom, role, password, **extra)
    except sqlite3.IntegrityError:
        raise Err('E-mail déjà utilisé')
    audit(u, 'utilisateur créé', email); return {'ok': 1}

@route('GET', '/admin/liens', ['admin'])
def liens_admin(u, b):
    return q("""SELECT l.user_id,l.patient_id,l.type,l.consentement,
        u.nom responsable,pu.nom patient,p.numero
        FROM liens l JOIN users u ON u.id=l.user_id
        JOIN patients p ON p.id=l.patient_id JOIN users pu ON pu.id=p.user_id
        ORDER BY u.nom,pu.nom""")

@route('POST', '/admin/liens', ['admin'])
def lier_proche(u, b):
    uid = b.get('user_id'); pid = b.get('patient_id'); typ = b.get('type')
    if not isinstance(uid, int) or not isinstance(pid, int) or typ not in ('parent', 'parrain', 'partenaire'):
        raise Err('Lien invalide')
    proche = q('SELECT role FROM users WHERE id=? AND actif=1', (uid,), True)
    if not proche or proche['role'] != typ: raise Err('Le compte choisi ne correspond pas au rôle du lien')
    if not q('SELECT 1 FROM patients WHERE id=?', (pid,), True): raise Err('Patient inconnu')
    if b.get('consentement') is not True: raise Err('Confirmez le lien et le consentement avant de continuer')
    if typ == 'parent' and not est_mineur(pid): raise Err('Un lien parent/tuteur ne peut être créé que pour un patient mineur')
    x('INSERT OR REPLACE INTO liens(user_id,patient_id,type,consentement) VALUES(?,?,?,1)', (uid, pid, typ))
    audit(u, 'lien proche créé ou confirmé', '%s %s patient %s' % (typ, uid, pid)); return {'ok': 1}

@route('POST', '/admin/liens/(\\d+)/(\\d+)/(parent|parrain|partenaire)/retirer', ['admin'])
def retirer_lien(u, b, uid, pid, typ):
    c = _c()
    try:
        cur = c.execute('DELETE FROM liens WHERE user_id=? AND patient_id=? AND type=?', (int(uid), int(pid), typ))
        c.commit()
    finally:
        c.close()
    if not cur.rowcount: raise Err('Lien introuvable')
    audit(u, 'lien proche retiré', '%s %s patient %s' % (typ, uid, pid)); return {'ok': 1}

@route('POST', '/admin/users/(\\d+)/basculer', ['admin'])
def basculer(u, b, uid):
    if int(uid) == u['id']: raise Err('Vous ne pouvez pas vous désactiver')
    x('UPDATE users SET actif=1-actif WHERE id=?', (int(uid),)); x('DELETE FROM sessions WHERE user_id=?', (int(uid),)); audit(u, 'compte activé/désactivé', 'user %s' % uid); return {'ok': 1}

@route('POST', '/admin/affecter', ['admin'])
def aff(u, b):
    if not q('SELECT 1 FROM patients WHERE id=?', (b.get('patient_id'),), True) or not q('SELECT 1 FROM psychologues WHERE id=?', (b.get('psy_id'),), True): raise Err('Patient ou psychologue inconnu')
    affecter(b['patient_id'], b['psy_id'], str(b.get('motif', 'Affectation administrateur'))[:200]); audit(u, 'affectation', 'patient %s vers psy %s' % (b['patient_id'], b['psy_id'])); return {'ok': 1}

@route('GET', '/admin/audit', ['admin'])
def journal(u, b): return q('SELECT a.ts,COALESCE(u.nom,"(anonyme)") utilisateur,a.action,a.cible FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 150')

# ---------- serveur HTTP ----------
SEC = [('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'),
       ('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"), ('Cache-Control', 'no-store')]
MIME = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.webp': 'image/webp'}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, data, ctype='application/json', extra=()):
        b = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', ctype + '; charset=utf-8'); self.send_header('Content-Length', str(len(b)))
        for k, v in list(SEC) + list(extra): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def user(self):
        c = SimpleCookie(self.headers.get('Cookie', ''))
        if 'ms' not in c: return None
        s = q('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expire>? AND u.actif=1', (c['ms'].value, time.time()), True)
        if s and not DEMO_MODE and s['email'].lower() in DEMO_EMAILS: return None
        return s
    def do_GET(self): self.go('GET')
    def do_POST(self): self.go('POST')
    def go(self, m):
        p = urlparse(self.path).path
        if m == 'GET' and not p.startswith('/api/'):
            f = 'index.html' if p == '/' else os.path.basename(p)
            fp = os.path.join(ST, f)
            if not os.path.isfile(fp): return self.out(404, {'erreur': 'Introuvable'})
            return self.out(200, open(fp, 'rb').read(), MIME.get(os.path.splitext(f)[1], 'application/octet-stream'))
        body = {}
        if m == 'POST':
            if self.headers.get('X-Requested-With') != 'fetch': return self.out(403, {'erreur': 'Requête refusée'})
            n = int(self.headers.get('Content-Length') or 0)
            if n > 100000: return self.out(413, {'erreur': 'Trop volumineux'})
            try: body = json.loads(self.rfile.read(n) or b'{}')
            except Exception: return self.out(400, {'erreur': 'JSON invalide'})
            if not isinstance(body, dict): return self.out(400, {'erreur': 'JSON invalide'})
        u = self.user(); pa = p[4:]
        for mm, rx, roles, f in R:
            g = rx.match(pa)
            if mm != m or not g: continue
            if roles is not None and not u: return self.out(401, {'erreur': 'Connexion requise'})
            if roles not in (None, '*') and u['role'] not in roles: audit(u, 'accès refusé', pa); return self.out(403, {'erreur': 'Accès refusé'})
            try:
                res = f(u, body, *g.groups()); ex = ()
                if isinstance(res, tuple): res, ex = res
                return self.out(200, res, extra=ex)
            except Err as e: return self.out(e.c, {'erreur': e.m})
            except Exception as e: print('Erreur', e); return self.out(500, {'erreur': 'Erreur interne'})
        self.out(404, {'erreur': 'Introuvable'})

if __name__ == '__main__':
    seed(); port = int(os.environ.get('PORT', 8000))
    if DEMO_MODE:
        print('Mens Sana : http://127.0.0.1:%d  (mode démo local)' % port)
        print('Comptes démo : mot de passe commun Demo2026! — ne pas utiliser avec de vraies données.')
    else:
        print('Mens Sana : http://127.0.0.1:%d  (mode sans données de démonstration)' % port)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
