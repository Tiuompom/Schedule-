"""
flask_bridge.py
===============
Pont entre l'interface web (index.html) et le backend Python (StaffManager, OptimizerManager).

Toutes les routes retournent du JSON sauf la route racine (/) qui sert index.html.

Initialisation : appelé depuis main.py via init(sm, cfg, bp, lg).
Les 4 globals (staff_manager, config, base_path, logger) sont ensuite accessibles
dans toutes les routes sans avoir à les passer en paramètre.

Structure des routes :
  GET  /                          → sert l'UI (index.html)
  GET  /api/staff                 → liste du register staff
  POST /api/staff                 → sauvegarde le register staff
  GET  /api/availability          → disponibilités parsées depuis le CSV Google Form
  POST /api/upload/availability   → upload d'un nouveau CSV de disponibilités
  GET  /api/demand                → besoins par shift (nested dict)
  POST /api/demand                → sauvegarde les besoins
  GET  /api/schedule              → dernier planning généré (depuis xlsx)
  POST /api/run                   → lance le solver PuLP et retourne le planning
  POST /api/schedule/finalize     → sauvegarde le planning ajusté manuellement
  GET  /api/shortage              → rapport de pénuries (fichier txt)
  GET  /api/export/<filename>     → téléchargement d'un fichier output
"""

from flask import Flask, jsonify, request, send_from_directory
import os
import pandas as pd

app = Flask(__name__, static_folder='../web')

# ── Globals injectés par main.py via init() ────────────────────────────────
staff_manager = None   # Instance de StaffManager (register, availability, demand)
config        = None   # Dict de configuration (structure des jours/shifts/rôles, chemins)
base_path     = None   # Chemin racine du projet (parent de /outputs)
data_path     = None   # Chemin complet vers /data (passé directement pour éviter ambiguïté)
logger        = None   # Logger optionnel

def init(sm, cfg, bp, dp, lg=None):
    """Appelé depuis main.py pour injecter les dépendances dans ce module.
    dp = data_path (chemin complet vers le dossier data/) passé explicitement
    pour éviter toute ambiguïté sur la reconstruction du chemin.
    """
    global staff_manager, config, base_path, data_path, logger
    staff_manager = sm
    config        = cfg
    base_path     = bp
    data_path     = dp
    logger        = lg


# ══════════════════════════════════════════════════════════════════
# SERVE UI
# ══════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Sert l'interface web principale (index.html depuis ../web/)."""
    return send_from_directory('../web', 'index.html')


# ══════════════════════════════════════════════════════════════════
# STAFF REGISTER
# Route GET  : retourne la liste du register au format attendu par l'UI
# Route POST : reçoit la liste modifiée depuis l'UI et la persiste en CSV
# ══════════════════════════════════════════════════════════════════

@app.route('/api/staff', methods=['GET'])
def get_staff():
    """
    Retourne le staff register sous forme de liste de dicts.
    Clés en minuscules pour correspondre au format attendu par l'UI JS.
    Exemple : [{ name, email, role, till, manager }, ...]
    """
    try:
        def to_bool(v): return str(v).strip().lower() in ('yes', 'true', '1')
        rows = []
        for _, r in staff_manager.staff_register.iterrows():
            rows.append({
                'name':    str(r.get('Name', '')),
                'email':   str(r.get('Email', '')),
                'role':    str(r.get('Role', 'Waiter')),
                'till':    to_bool(r.get('Till_Authorized', False)),
                'manager': to_bool(r.get('Is_Manager', False)),
            })
        return jsonify(rows)
    except Exception as e:
        if logger: logger.error(f'/api/staff GET error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/staff', methods=['POST'])
def save_staff():
    """
    Reçoit la liste staff depuis l'UI [{ name, email, role, till, manager }, ...]
    Reconstruit le DataFrame avec les noms de colonnes attendus par StaffManager
    et persiste en CSV.
    """
    try:
        data = request.json
        df = pd.DataFrame([{
            'Name':            d.get('name', ''),
            'Email':           d.get('email', ''),
            'Role':            d.get('role', 'Waiter'),
            'Till_Authorized': d.get('till', False),
            'Is_Manager':      d.get('manager', False),
        } for d in data])

        staff_manager.staff_register = df

        csv_path = os.path.join(data_path, config['names_df']['staff_register'])
        df.to_csv(csv_path, index=False)

        return jsonify({'status': 'ok', 'count': len(df)})
    except Exception as e:
        if logger: logger.error(f'/api/staff POST error: {e}', exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# AVAILABILITY
# Route GET  : parse le CSV Google Form et retourne un dict structuré
# Route POST : upload d'un nouveau CSV, remplace l'ancien et recharge
# ══════════════════════════════════════════════════════════════════

@app.route('/api/availability', methods=['GET'])
def get_availability():
    """
    Parse staff_availability.csv (format export Google Form) et retourne :
    {
      "Gordon Ramsay": { "Mon": ["14h", "18h"], "Tue": [], "Wed": ["14h"], ... },
      "Jamie Oliver":  { "Mon": ["18h"], ... },
      ...
    }
    Garde uniquement la dernière réponse par email (en cas de soumission multiple).
    Les créneaux sont extraits en cherchant "14h"/"18h"/"19h" dans la cellule de chaque jour.
    """
    try:
        avail_df = staff_manager.staff_availability.copy()

        # Garder uniquement la soumission la plus récente par email
        try:
            avail_df['Horodateur'] = pd.to_datetime(avail_df['Horodateur'], dayfirst=True)
            avail_df = avail_df.sort_values('Horodateur').drop_duplicates('Adresse e-mail', keep='last')
        except Exception as e:
            if logger: logger.warning(f"Horodateur parse warning (using all rows): {e}")

        # Noms complets des jours (ex: "Monday") → abréviations UI (ex: "Mon")
        days_full   = config['structure']['days']
        days_abbr   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        # Labels de créneaux définis dans config (ex: ["14h", "18h", "19h"])
        time_labels = list(config['structure']['time_labels'].values())

        out = {}
        for _, row in avail_df.iterrows():
            name = str(row.get('Name', '')).strip()
            if not name:
                continue
            out[name] = {}
            for full, abbr in zip(days_full, days_abbr):
                # Supprimer les espaces avant de chercher (ex: "14h 18h" → "14h18h")
                cell = str(row.get(full, '')).replace(' ', '')
                out[name][abbr] = [h for h in time_labels if h in cell]

        if logger: logger.info(f'/api/availability: {len(out)} workers retournés')
        return jsonify(out)

    except Exception as e:
        if logger: logger.error(f'/api/availability GET error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload/availability', methods=['POST'])
def upload_availability():
    """
    Reçoit un fichier CSV (export Google Form) via multipart form-data.
    Sauvegarde le fichier, recharge staff_manager.staff_availability,
    et valide les headers — retourne une erreur claire si le format est mauvais.

    Le chemin de sauvegarde utilise paths['data'] (chemin complet) injecté
    via init() pour éviter tout problème de chemin relatif.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'Aucun fichier reçu'}), 400

        f = request.files['file']
        if not f.filename.endswith('.csv'):
            return jsonify({'status': 'error', 'message': 'Le fichier doit être un .csv'}), 400

        # Lire le contenu en mémoire d'abord pour valider avant de sauvegarder
        import io
        content = f.read()
        try:
            df_new = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Fichier CSV illisible : {e}'}), 400

        # Valider les headers avant de remplacer l'ancien fichier
        expected_cols = set(config['headers']['staff_availability'])
        actual_cols   = set(df_new.columns)
        missing = expected_cols - actual_cols
        extra   = actual_cols   - expected_cols
        if missing:
            return jsonify({
                'status':  'error',
                'message': f'Colonnes manquantes : {", ".join(sorted(missing))}'
            }), 400
        if extra:
            return jsonify({
                'status':  'error',
                'message': f'Colonnes inattendues : {", ".join(sorted(extra))}'
            }), 400

        # Headers OK → sauvegarder sur disque
        save_path = os.path.join(
            data_path,                               # chemin complet injecté via init()
            config['names_df']['staff_availability']
        )
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'wb') as out:
            out.write(content)

        # Recharger en mémoire pour que /api/availability soit immédiatement à jour
        staff_manager.staff_availability = df_new

        if logger: logger.info(f'Availability CSV uploadé : {f.filename} ({len(df_new)} lignes)')
        return jsonify({'status': 'ok', 'filename': f.filename, 'rows': len(df_new)})

    except Exception as e:
        if logger: logger.error(f'/api/upload/availability error: {e}', exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# DEMAND (besoins par shift)
# Le CSV need_for_staff.csv a ce format (lignes = rôles, colonnes = "Jour Shift") :
#   Role    | Mon 14h | Mon 18h | Mon 19h | Tue 14h | ...
#   Waiter  |    2    |    3    |    2    |    2    | ...
#   Bartender|   1    |    2    |    1    |    1    | ...
#
# L'UI travaille avec un dict nested :
#   { Mon: { 14h: { Waiter: 2, Bartender: 1 }, 18h: { ... }, ... }, Tue: { ... }, ... }
#
# GET : convertit CSV → dict nested
# POST : convertit dict nested → CSV et persiste
# ══════════════════════════════════════════════════════════════════

@app.route('/api/demand', methods=['GET'])
def get_demand():
    """
    Lit need_for_staff.csv et retourne la structure nested attendue par l'UI.
    """
    try:
        df          = staff_manager.need_for_staff
        days_abbr   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        time_labels = list(config['structure']['time_labels'].values())

        out = {}
        for day in days_abbr:
            out[day] = {}
            for shift in time_labels:
                col = f"{day} {shift}"  # ex: "Mon 14h"
                out[day][shift] = {}
                for _, row in df.iterrows():
                    role = str(row.get('Role', ''))
                    val  = int(row.get(col, 0)) if col in df.columns else 0
                    out[day][shift][role] = val

        return jsonify(out)
    except Exception as e:
        if logger: logger.error(f'/api/demand GET error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/demand', methods=['POST'])
def save_demand():
    """
    Reçoit le dict nested depuis l'UI, le convertit en DataFrame format CSV
    et persiste dans need_for_staff.csv.

    IMPORTANT : l'ordre des colonnes est forcé pour correspondre exactement
    à ce qu'attend OptimizerManager (qui lit par position, pas par nom).
    Ordre : Role | Mon 14h | Mon 18h | Mon 19h | Tue 14h | ...
    """
    try:
        data        = request.json
        days_abbr   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        time_labels = list(config['structure']['time_labels'].values())
        roles       = config['structure']['roles']

        # Construire les colonnes dans l'ordre exact attendu par l'optimizer
        ordered_cols = ['Role'] + [f"{day} {shift}" for day in days_abbr for shift in time_labels]

        rows = []
        for role in roles:
            row = {'Role': role}
            for day in days_abbr:
                for shift in time_labels:
                    col      = f"{day} {shift}"
                    row[col] = data.get(day, {}).get(shift, {}).get(role, 0)
            rows.append(row)

        # Forcer l'ordre des colonnes — critique pour OptimizerManager
        df = pd.DataFrame(rows, columns=ordered_cols)

        # Mettre à jour en mémoire immédiatement (l'optimizer lit staff_manager.need_for_staff)
        staff_manager.need_for_staff = df

        # Persister sur disque (data_path = chemin complet injecté via init())
        csv_path = os.path.join(data_path, config['names_df']['need_for_staff'])
        df.to_csv(csv_path, index=False)

        if logger: logger.info(f'/api/demand POST: besoins sauvegardés ({len(df)} rôles, {len(ordered_cols)-1} slots)')
        return jsonify({'status': 'ok'})
    except Exception as e:
        if logger: logger.error(f'/api/demand POST error: {e}', exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# SCHEDULE — dernier planning généré (lecture depuis xlsx)
# Utilisé au chargement de l'UI pour pré-remplir l'étape Ajuster
# si un planning a déjà été généré lors d'une session précédente.
# ══════════════════════════════════════════════════════════════════

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    """
    Retourne le dernier planning sauvegardé en xlsx, ou [] si aucun n'existe.
    Colonnes attendues : Staff Name, Monday, Tuesday, ..., Sunday
    """
    try:
        xlsx_path = os.path.join(base_path, 'outputs', 'Weekly_Staff_Schedule.xlsx')
        if not os.path.exists(xlsx_path):
            return jsonify([])
        df = pd.read_excel(xlsx_path)
        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        if logger: logger.warning(f'/api/schedule GET error (returning []): {e}')
        return jsonify([])


# ══════════════════════════════════════════════════════════════════
# RUN SCHEDULER
# Lance OptimizerManager (solver BIP PuLP) sur les données courantes
# (availability + need_for_staff + staff_register).
# Génère les fichiers outputs (xlsx, pdf, shortage txt).
# Retourne le planning et le nombre de pénuries.
# ══════════════════════════════════════════════════════════════════

@app.route('/api/run', methods=['POST'])
def run_scheduler():
    """
    Lance l'optimisation et retourne :
    {
      status:    "ok" | "warn" | "error",
      shortages: <int>,   # nombre de slots en pénurie
      schedule:  [{ "Staff Name": ..., "Monday": "14h", ... }, ...]
    }
    """
    try:
        from optimizer_manager import OptimizerManager
        from reporting_manager import ReportingManager

        optimizer = OptimizerManager(staff_manager)
        x, s_work, s_till, s_mana, availability_dict = (
            optimizer.sol,
            optimizer.s_work,
            optimizer.s_till,
            optimizer.s_mana,
            optimizer.availability
        )

        shortage = {'worker': s_work, 'till': s_till, 'manager': s_mana}
        reporting = ReportingManager(x, config, base_path, shortage, availability_dict)
        reporting.save_schedule_toxl()
        reporting.save_schedule_pdf()
        reporting.save_reporting()

        # Compter le nombre total de slots en pénurie (variables slack du solver)
        shortages = 0
        try:
            n_days  = len(config['structure']['days'])
            n_times = config['structure']['shifts']
            roles   = config['structure']['roles']
            for j in range(n_days):
                for t in range(n_times):
                    for role in roles:
                        shortages += int(s_work[j][t][role].varValue or 0)
        except Exception:
            pass  # Si le comptage échoue, on retourne shortages=0

        if logger: logger.info(f'/api/run: terminé, {shortages} pénurie(s)')
        return jsonify({
            'status':    'ok' if shortages == 0 else 'warn',
            'shortages': shortages,
            'schedule':  reporting.df_schedule.to_dict(orient='records')
        })

    except Exception as e:
        if logger: logger.error(f'/api/run error: {e}', exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# FINALIZE — sauvegarde le planning après ajustements manuels
# Reçoit proposedState depuis l'UI après que l'utilisateur a
# modifié des shifts manuellement à l'étape 5 (Ajuster).
# Reconstruit le DataFrame et génère xlsx + pdf.
# ══════════════════════════════════════════════════════════════════

@app.route('/api/schedule/finalize', methods=['POST'])
def finalize_schedule():
    """
    Reçoit proposedState :
    { "Gordon Ramsay": { "Mon": "14h", "Tue": "—", "Wed": "18h", ... }, ... }

    Convertit les abréviations de jours en noms complets pour le CSV/xlsx.
    "—" indique aucun shift ce jour-là → cellule vide dans le fichier.
    """
    try:
        proposed  = request.json
        days_full = config['structure']['days']                   # ["Monday", "Tuesday", ...]
        days_abbr = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

        rows = []
        for name, shifts in proposed.items():
            row = {'Staff Name': name}
            for abbr, full in zip(days_abbr, days_full):
                val      = shifts.get(abbr, '—')
                row[full] = '' if val == '—' else val  # cellule vide si pas de shift
            rows.append(row)

        df          = pd.DataFrame(rows)
        outputs_dir = os.path.join(base_path, 'outputs')
        os.makedirs(outputs_dir, exist_ok=True)

        # Sauvegarde xlsx
        xlsx_path = os.path.join(outputs_dir, 'Weekly_Staff_Schedule.xlsx')
        try:
            import xlsxwriter
            with pd.ExcelWriter(xlsx_path, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Staff Schedule')
        except ImportError:
            df.to_excel(xlsx_path, index=False)

        # Sauvegarde pdf via wkhtmltopdf
        try:
            import importlib, sys, subprocess, tempfile
            for mod in ['reporting_manager']:
                if mod in sys.modules:
                    importlib.reload(sys.modules[mod])
            from reporting_manager import ReportingManager
            rm = ReportingManager.__new__(ReportingManager)
            rm.df_schedule = df
            rm.days        = config['structure']['days']
            rm.time_labels = config['structure']['time_labels']
            rm.roles       = config['structure']['roles']
            rm.base_path   = base_path
            html = rm._build_html()
            with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
                f.write(html)
                tmp_html = f.name
            try:
                subprocess.run([
                    r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
                    '--orientation', 'Landscape', '--page-size', 'A4',
                    '--margin-top', '10mm', '--margin-bottom', '10mm',
                    '--margin-left', '10mm', '--margin-right', '10mm',
                    '--encoding', 'UTF-8', '--quiet',
                    tmp_html, os.path.join(outputs_dir, 'Weekly_Staff_Schedule.pdf')
                ], check=True)
            finally:
                os.unlink(tmp_html)
        except Exception as e:
            if logger: logger.warning(f'PDF finalize failed: {e}')
        return jsonify({'status': 'ok', 'workers': len(df)})

    except Exception as e:
        if logger: logger.error(f'/api/schedule/finalize error: {e}', exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# SHORTAGE REPORT — rapport texte généré par ReportingManager
# ══════════════════════════════════════════════════════════════════

@app.route('/api/shortage', methods=['GET'])
def get_shortage():
    """
    Retourne le contenu du fichier Shortage_Report.txt (généré par /api/run).
    Si le fichier n'existe pas encore, retourne un message d'attente.
    """
    report_path = os.path.join(base_path, 'outputs', 'Shortage_Report.txt')
    if os.path.exists(report_path):
        with open(report_path, 'r') as f:
            return jsonify({'report': f.read()})
    return jsonify({'report': 'Lance le scheduler pour voir le rapport.'})


# ══════════════════════════════════════════════════════════════════
# EXPORT — téléchargement des fichiers outputs
# ══════════════════════════════════════════════════════════════════

@app.route('/api/export/<filename>', methods=['GET'])
def export_file(filename):
    """
    Sert un fichier depuis le dossier outputs/ en téléchargement direct.
    Utilisé par l'UI pour les boutons Download (xlsx, pdf, txt).
    Retourne 404 si le fichier n'existe pas (scheduler pas encore lancé).
    """
    outputs_dir = os.path.join(base_path, 'outputs')
    try:
        return send_from_directory(outputs_dir, filename, as_attachment=True)
    except Exception:
        return jsonify({'error': f'{filename} introuvable — lance le scheduler d\'abord'}), 404


# ══════════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════════

def start(debug=False):
    """Ouvre le navigateur et démarre le serveur Flask sur le port 5000."""
    import webbrowser
    webbrowser.open('http://localhost:5000')
    app.run(port=5000, debug=debug, use_reloader=False)
