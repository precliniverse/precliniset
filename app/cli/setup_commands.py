import click
import random
import math
import sys
from datetime import date, timedelta, datetime
from flask import Blueprint, current_app
from flask.cli import with_appcontext
from faker import Faker

from app import db
from app.models import (
    User, Team, Role, Permission, Project, ExperimentalGroup,
    DataTable, ExperimentDataRow, Sample, SampleType, SampleStatus,
    Analyte, AnalyteDataType, Organ, TissueCondition, Anticoagulant,
    ProtocolModel, AnimalModel, ProtocolAnalyteAssociation, AnimalModelAnalyteAssociation,
    TeamMembership, UserTeamRoleLink, Severity, HousingConditionSet,
    HousingConditionItem, HousingSetItemAssociation,
    EthicalApproval, ProjectEthicalApprovalAssociation
)
from app.permissions import AVAILABLE_PERMISSIONS
from app.models.import_pipeline import ImportPipeline
from app.services.admin_service import AdminService

setup_bp = Blueprint('setup', __name__)
fake = Faker()

# --- Shared Logic ---

def _ensure_db_initialized():
    """Checks if critical tables exist, if not, runs migrations."""
    from sqlalchemy import inspect
    from flask_migrate import upgrade

    inspector = inspect(db.engine)
    # Check a core table to see if DB is initialized
    if not inspector.has_table("user"):
        print("   [*] Database incomplete. Running migrations...")
        try:
            upgrade()
            print("   -> Database schema updated via migrations.")
        except Exception as e:
            print(f"   -> Error running migrations: {e}")
            raise e

    db.session.remove() # Clear any potentially poisoned session state

def _init_base_structure():
    """Drops tables using raw SQL (nuclear option) and recreates them."""
    print("1. Clearing Database...")

    # Use raw connection with AUTOCOMMIT to handle DDLs safely without transaction locks
    with db.engine.connect() as connection:
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")

        try:
            # --- 1. Disable Foreign Key Checks ---
            if 'mysql' in db.engine.name:
                connection.execute(db.text("SET FOREIGN_KEY_CHECKS = 0"))
            elif 'sqlite' in db.engine.name:
                connection.execute(db.text("PRAGMA foreign_keys=OFF"))

            # --- 2. Find All Tables ---
            tables = []
            if 'mysql' in db.engine.name:
                # Query information_schema for the current database
                db_name = db.engine.url.database
                query = db.text("SELECT table_name FROM information_schema.tables WHERE table_schema = :db_name AND table_type = 'BASE TABLE'")
                result = connection.execute(query, {"db_name": db_name})
                tables = [row[0] for row in result]
            elif 'sqlite' in db.engine.name:
                query = db.text("SELECT name FROM sqlite_master WHERE type='table'")
                result = connection.execute(query)
                tables = [row[0] for row in result if row[0] != 'sqlite_sequence']

            # --- 3. Drop Each Table Explicitly ---
            # SECURITY FIX: Validate table names against the retrieved list
            valid_tables = set(tables)

            for table in tables:
                if table not in valid_tables:
                    continue

                # Double check for alphanumeric/underscore only to be absolutely safe
                if not table.replace('_', '').isalnum():
                    print(f"      - Skipping suspicious table name: {table}")
                    continue

                print(f"      - Dropping {table}...")

                # Safe quoting based on dialect
                if 'mysql' in db.engine.name:
                    quoted_table = f"`{table}`"
                else:
                    quoted_table = f'"{table}"'

                # We use text() but with a validated, quoted identifier
                drop_stmt = db.text(f"DROP TABLE IF EXISTS {quoted_table}")
                connection.execute(drop_stmt)

            # --- 4. Re-enable Foreign Key Checks ---
            if 'mysql' in db.engine.name:
                connection.execute(db.text("SET FOREIGN_KEY_CHECKS = 1"))
            elif 'sqlite' in db.engine.name:
                connection.execute(db.text("PRAGMA foreign_keys=ON"))

            print("   -> All tables dropped successfully via raw SQL.")

        except Exception as e:
            print(f"   -> Error dropping tables: {e}")
            # We don't verify reraise here to allow create_all to attempt recovery if partial
            raise e

    print("   -> Re-creating tables via Migrations...")
    from flask_migrate import upgrade
    upgrade()

    # print("   -> Stamping DB version to head...")
    # from flask_migrate import stamp
    # stamp()

    print("2. Creating/Updating System Permissions...")
    existing_perms = {(p.resource, p.action) for p in Permission.query.all()}
    for resource, actions in AVAILABLE_PERMISSIONS.items():
        for action in actions:
            if (resource, action) not in existing_perms:
                print(f"      - Adding permission: {resource}:{action}")
                db.session.add(Permission(resource=resource, action=action))
    db.session.commit()

    print("3. Creating Global Roles...")
    if not Role.query.filter_by(name="System Administrator").first():
        sys_admin = Role(name="System Administrator", description="Full system access.")
        all_perms = Permission.query.all()
        # permissions might adhere to previous session constraints, so refresh if needed
        # but here we are in a fresh logic, should be fine.
        sys_admin.permissions.extend(all_perms)
        db.session.add(sys_admin)
        db.session.commit()

def _create_super_admin(email=None, password=None):
    """Creates the superuser."""
    print("4. Creating Super Admin...")

    # Priority: Function Args -> Config -> Prompt (if interactive) -> Default
    if not email:
        email = current_app.config.get('SUPERADMIN_EMAIL')
    if not password:
        password = current_app.config.get('SUPERADMIN_PASSWORD')

    # Interactive Fallback if still missing and running in interactive mode (not fully possible inside flask cli unless explicit)
    # But we can allow the CLI to pass them.

    if not email:
        print("   [!] No SUPERADMIN_EMAIL found. Using default 'admin@example.com'")
        email = "admin@example.com"
    if not password:
         # SECURITY FIX: Removed default 'password'
         print("   [!] No SUPERADMIN_PASSWORD found in config.")
         password = click.prompt("Please enter a Super Admin Password", hide_input=True, confirmation_prompt=True)

    if not User.query.filter_by(email=email).first():
        user = User(email=email, is_super_admin=True, email_confirmed=True)
        user.set_password(password)
        db.session.add(user)
        db.session.flush() # Flush to get ID if needed, though commit handles it

        # Ensure 'System Administrator' Role is assigned!
        sys_role = Role.query.filter_by(name="System Administrator").first()
        if sys_role:
             # Check if link exists (it shouldn't for new user)
             # UserTeamRoleLink is for TEAMS. System Admin is global?
             # Looking at models, is_super_admin flag is usually enough for global access.
             # But if there's a Global Role concept, we might want to attach it?
             # Based on init_base_structure, we created a Role "System Administrator".
             # Usually roles are linked to users. Let's see if User has 'roles' relationship.
             if hasattr(user, 'roles'):
                 user.roles.append(sys_role)

        db.session.commit()
        print(f"   -> Super Admin created: {email}")
    else:
        print(f"   -> Super Admin {email} already exists.")

def _populate_static_resources():
    """Adds Analytes, Organs, Conditions, etc."""
    _ensure_db_initialized()
    print("5. Populating Static Resources (Analytes, Organs)...")

    analytes = [
        {'name': 'ID', 'data_type': AnalyteDataType.TEXT, 'is_metadata': True, 'is_mandatory': True},
        {'name': 'Date of Birth', 'data_type': AnalyteDataType.DATE, 'is_metadata': True, 'is_mandatory': True},
        {'name': 'Sex', 'data_type': AnalyteDataType.CATEGORY, 'allowed_values': 'Male;Female', 'is_metadata': True, 'is_mandatory': True},
        {'name': 'Body Weight', 'data_type': AnalyteDataType.FLOAT, 'unit': 'g'},
        {'name': 'Tumor Volume', 'data_type': AnalyteDataType.FLOAT, 'unit': 'mm3'},
        {'name': 'Genotype', 'data_type': AnalyteDataType.CATEGORY, 'allowed_values': 'WT;KO;Het', 'is_metadata': True},
        {'name': 'Cage', 'data_type': AnalyteDataType.TEXT, 'is_metadata': True},
        {'name': 'Treatment Group', 'data_type': AnalyteDataType.TEXT, 'is_metadata': True},
        {'name': 'Blinded Group', 'data_type': AnalyteDataType.TEXT, 'is_metadata': True, 'is_sensitive': True},
        {'name': 'Rotarod Latency (Trial 1)', 'data_type': AnalyteDataType.FLOAT, 'unit': 's'},
        {'name': 'Rotarod Latency (Trial 2)', 'data_type': AnalyteDataType.FLOAT, 'unit': 's'},
        {'name': 'Rotarod Latency (Trial 3)', 'data_type': AnalyteDataType.FLOAT, 'unit': 's'},
        {'name': 'Mean Rotarod Latency', 'data_type': AnalyteDataType.FLOAT, 'unit': 's'},
        {'name': 'Grip Strength (Trial 1)', 'data_type': AnalyteDataType.FLOAT, 'unit': 'g'},
        {'name': 'Grip Strength (Trial 2)', 'data_type': AnalyteDataType.FLOAT, 'unit': 'g'},
        {'name': 'Grip Strength (Trial 3)', 'data_type': AnalyteDataType.FLOAT, 'unit': 'g'},
        {'name': 'Mean Grip Strength', 'data_type': AnalyteDataType.FLOAT, 'unit': 'g'},
        {'name': 'Activity Count', 'data_type': AnalyteDataType.INT, 'unit': 'counts/h'},
        {'name': 'Distance Travelled', 'data_type': AnalyteDataType.FLOAT, 'unit': 'cm/h'},
        {'name': 'Rearing', 'data_type': AnalyteDataType.INT, 'unit': 'counts/h'},
        {'name': 'Time Spent Mobile', 'data_type': AnalyteDataType.FLOAT, 'unit': '%'},
        {'name': 'Time Spent Immobile', 'data_type': AnalyteDataType.FLOAT, 'unit': '%'}
    ]
    for a in analytes:
        if not Analyte.query.filter_by(name=a['name']).first():
            db.session.add(Analyte(**a))

    organs = ["Tumor", "Spleen", "Blood", "Liver", "Brain", "Lung", "Heart", "Kidney", "Adrenal Gland"]
    for o in organs:
        if not Organ.query.filter_by(name=o).first():
            db.session.add(Organ(name=o))

    conditions = ["Fresh Frozen", "FFPE", "Snap Frozen", "RNAlater"]
    for c in conditions:
        if not TissueCondition.query.filter_by(name=c).first():
            db.session.add(TissueCondition(name=c))

    anticoags = ["EDTA", "Heparin", "Citrate", "None"]
    for ac in anticoags:
        if not Anticoagulant.query.filter_by(name=ac).first():
            db.session.add(Anticoagulant(name=ac))

    housing_conditions = ["Standard Cage", "Enriched Cage", "Metabolic Cage", "Group Housed", "Individually Housed"]
    for hc in housing_conditions:
        if not HousingConditionSet.query.filter_by(name=hc).first():
            db.session.add(HousingConditionSet(name=hc))

    db.session.commit()
    print("   -> Resources populated.")

# --- Simulation Logic Helpers ---
def get_or_create_analyte(name, dtype, unit=None, allowed=None, is_meta=False):
    a = Analyte.query.filter_by(name=name).first()
    if not a:
        a = Analyte(
            name=name,
            data_type=dtype,
            unit=unit,
            allowed_values=allowed,
            is_metadata=is_meta
        )
        db.session.add(a)
        db.session.flush()
    return a

def generate_realistic_data(protocol_name, sex, genotype, treatment, age_weeks):
    data = {}
    sex_mod = 1.2 if sex == 'Male' else 1.0
    geno_mod = 1.5 if genotype == 'KO' else 1.0
    treat_mod = 0.7 if treatment == 'Drug A' else (0.5 if treatment == 'Drug B' else 1.0)

    if protocol_name == "Glucose Tolerance Test (IPGTT)":
        base_curve = {0: 80, 15: 150, 30: 140, 60: 110, 90: 90, 120: 85}
        for t, val in base_curve.items():
            phenotype_intensity = (geno_mod - 1.0) * treat_mod
            final_val = val * sex_mod * (1 + phenotype_intensity)
            final_val += random.uniform(-10, 10)
            data[f'Glucose T{t}'] = round(final_val, 1)

    elif protocol_name == "Accelerating Rotarod":
        base_time = 100
        phenotype_factor = 0.6 if genotype == 'KO' else 1.0
        for t in [1, 2, 3]:
            learning = 1 + (t * 0.1)
            val = base_time * learning * phenotype_factor * sex_mod
            if genotype == 'KO' and treatment != 'Vehicle':
                val *= 1.2
            val += random.uniform(-15, 15)
            data[f'Rotarod Trial {t}'] = round(val, 1)
        vals = [data[f'Rotarod Trial {t}'] for t in [1, 2, 3]]
        data['Rotarod Mean'] = round(sum(vals) / 3, 1)

    elif protocol_name == "Body Composition (MRI)":
        base_weight = 25 * sex_mod
        if genotype == 'KO': base_weight += 10
        if treatment != 'Vehicle': base_weight -= 5
        total_weight = base_weight + random.uniform(-2, 2)
        fat_mass = total_weight * (0.4 if genotype == 'KO' else 0.15)
        lean_mass = total_weight - fat_mass - 2
        data['Lean Mass'] = round(lean_mass, 2)
        data['Fat Mass'] = round(fat_mass, 2)
        data['Free Water'] = round(random.uniform(1.5, 2.5), 2)

    return data

# --- Commands ---

@setup_bp.cli.command("init")
@click.option('--email', prompt='Super Admin Email', help='Email for Super Admin')
@click.option('--password', prompt='Super Admin Password', hide_input=True, confirmation_prompt=True, help='Password for Super Admin')
def init_cmd(email, password):
    """Reset DB and create Super Admin."""
    if not current_app.config.get('DEBUG') and 'y' != input("This will DESTROY ALL DATA. Continue? [y/N]: "):
        print("Aborted.")
        return
    _init_base_structure()
    _create_super_admin(email, password)
    print("Done.")

@setup_bp.cli.command("reset-password")
@click.option('--email', prompt='User Email', help='Email of the user')
@click.option('--password', prompt='New Password', hide_input=True, confirmation_prompt=True, help='New password')
def reset_password_cmd(email, password):
    """Reset password for a specific user."""
    user = User.query.filter_by(email=email).first()
    if not user:
        print(f"Error: User {email} not found!")
        return

    user.set_password(password)
    db.session.commit()
    print(f"Password for {email} updated successfully.")

@setup_bp.cli.command("create-superadmin")
@click.option('--email', prompt='New Super Admin Email', help='Email for new Super Admin')
@click.option('--password', prompt='New Super Admin Password', hide_input=True, confirmation_prompt=True, help='Password for new Super Admin')
def create_superadmin_cmd(email, password):
    """Create a new superadmin user without resetting the database."""
    _ensure_db_initialized()
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        print(f"Error: User {email} already exists!")
        print(f"Current status: {'Super Admin' if existing_user.is_super_admin else 'Regular User'}")

        if not existing_user.is_super_admin:
            upgrade = input("Would you like to upgrade this user to Super Admin? [y/N]: ")
            if upgrade.lower() == 'y':
                existing_user.is_super_admin = True

                # Ensure System Administrator role is assigned
                sys_role = Role.query.filter_by(name="System Administrator").first()
                if sys_role and hasattr(existing_user, 'roles') and sys_role not in existing_user.roles:
                    existing_user.roles.append(sys_role)

                db.session.commit()
                print(f"User {email} upgraded to Super Admin successfully.")
            else:
                print("Operation cancelled.")
        return

    # Create new superadmin
    user = User(email=email, is_super_admin=True, email_confirmed=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    # Ensure 'System Administrator' Role is assigned
    sys_role = Role.query.filter_by(name="System Administrator").first()
    if sys_role and hasattr(user, 'roles'):
        user.roles.append(sys_role)

    db.session.commit()
    print(f"Super Admin created successfully: {email}")

@setup_bp.cli.command("static-resources")
def static_cmd():
    """Populate static lists (analytes, organs, etc)."""
    _populate_static_resources()
    print("Done.")

@setup_bp.cli.command("init-admin")
def init_admin_cmd():
    """Create superadmin from env vars (non-interactive, for deployment scripts)."""
    from app.helpers import create_super_admin, ensure_mandatory_analytes_exist

    # 1. Ensure DB is initialized
    _ensure_db_initialized()

    # 2. Ensure permissions/roles exist
    from app.permissions import AVAILABLE_PERMISSIONS
    existing_perms = {(p.resource, p.action) for p in Permission.query.all()}
    for resource, actions in AVAILABLE_PERMISSIONS.items():
        for action in actions:
            if (resource, action) not in existing_perms:
                db.session.add(Permission(resource=resource, action=action))
    db.session.commit()

    if not Role.query.filter_by(name="System Administrator").first():
        sys_admin = Role(name="System Administrator", description="Full system access.")
        sys_admin.permissions.extend(Permission.query.all())
        db.session.add(sys_admin)
        db.session.commit()

    # 3. Create/update superadmin from config
    print("Ensuring Super Admin exists...")
    create_super_admin(current_app, db)

    # 4. Mandatory Analytes
    print("Checking mandatory analytes...")
    ensure_mandatory_analytes_exist(current_app, db)

    print("Initialization complete.")

@setup_bp.cli.command("clean")
@click.option('--email', prompt='Super Admin Email', help='Email for verification')
@click.option('--password', prompt='Super Admin Password', hide_input=True, help='Password for verification')
@click.option('--force', is_flag=True, help='Skip confirmation prompts')
def clean_cmd(email, password, force):
    """Wipe all data (requires Admin auth)."""
    print("Verifying credentials...")
    try:
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password) or not user.is_super_admin:
            print("Error: Invalid credentials or insufficient privileges.")
            return # Strict on credentials unless forced? No, logic below allows bypass.
    except Exception as e:
        print(f"Warning: Could not verify credentials ({e}). Database might be corrupt.")
        if not force and 'y' != input("Proceed with wipe anyway? [y/N]: "):
            return

    # Explicitly release any metadata locks held by the verification query
    db.session.remove()

    if not force and 'y' != input("WARNING: This will PERMANENTLY ERASE ALL DATA. Confirm? [y/N]: "):
        print("Aborted.")
        return

    _init_base_structure()
    print("Database wiped and base structure re-initialized.")

@setup_bp.cli.command("populate-simulation")
@click.option('--teams', default=2, help='Number of teams')
@click.option('--projects', default=2, help='Projects per team')
@click.option('--groups', default=2, help='Groups per project')
@click.option('--animals', default=5, help='Animals per subgroup')
@click.option('--repetitions', default=1, help='Number of times to repeat each protocol (for repetition analysis)')
@click.option('--repetition-interval', default=2, help='Interval in weeks between repetitions')
def simulation_cmd(teams, projects, groups, animals, repetitions, repetition_interval):
    """Seed DB with scalable simulation data."""
    print("Initializing simulation...")
    # Ensure basics exist
    _ensure_db_initialized()
    needs_init = False
    if not Role.query.first():
         needs_init = True

    if needs_init:
         _init_base_structure()
         _create_super_admin()

    admin_service = AdminService()

    # Scientific Models
    a_id = get_or_create_analyte('ID', AnalyteDataType.TEXT, is_meta=True)
    a_dob = get_or_create_analyte('Date of Birth', AnalyteDataType.DATE, is_meta=True)
    a_sex = get_or_create_analyte('Sex', AnalyteDataType.CATEGORY, allowed='Male;Female', is_meta=True)
    a_geno = get_or_create_analyte('Genotype', AnalyteDataType.CATEGORY, allowed='WT;KO;Tg', is_meta=True)
    a_treat = get_or_create_analyte('Treatment', AnalyteDataType.CATEGORY, allowed='Vehicle;Drug A;Drug B', is_meta=True)

    gtt_analytes = [get_or_create_analyte(f'Glucose T{t}', AnalyteDataType.FLOAT, unit='mg/dL') for t in [0, 15, 30, 60, 90, 120]]
    rot_analytes = [get_or_create_analyte(f'Rotarod Trial {t}', AnalyteDataType.FLOAT, unit='s') for t in [1, 2, 3]]
    rot_mean = get_or_create_analyte('Rotarod Mean', AnalyteDataType.FLOAT, unit='s')
    rot_analytes.append(rot_mean)
    bc_analytes = [
        get_or_create_analyte('Lean Mass', AnalyteDataType.FLOAT, unit='g'),
        get_or_create_analyte('Fat Mass', AnalyteDataType.FLOAT, unit='g'),
        get_or_create_analyte('Free Water', AnalyteDataType.FLOAT, unit='g')
    ]

    model = AnimalModel.query.filter_by(name="Metabolic Mouse Model").first()
    if not model:
        model = AnimalModel(name="Metabolic Mouse Model")
        db.session.add(model)
        db.session.flush()
        for i, a in enumerate([a_id, a_dob, a_sex, a_geno, a_treat]):
            db.session.add(AnimalModelAnalyteAssociation(animal_model=model, analyte=a, order=i))

    protocols = []
    p_gtt = ProtocolModel.query.filter_by(name="Glucose Tolerance Test (IPGTT)").first() or ProtocolModel(name="Glucose Tolerance Test (IPGTT)", severity=Severity.MODERATE)
    if not p_gtt.id:
        db.session.add(p_gtt); db.session.flush()
        for i, a in enumerate(gtt_analytes): db.session.add(ProtocolAnalyteAssociation(protocol_model=p_gtt, analyte=a, order=i))
    protocols.append(p_gtt)

    p_rot = ProtocolModel.query.filter_by(name="Accelerating Rotarod").first() or ProtocolModel(name="Accelerating Rotarod", severity=Severity.LIGHT)
    if not p_rot.id:
        db.session.add(p_rot); db.session.flush()
        for i, a in enumerate(rot_analytes): db.session.add(ProtocolAnalyteAssociation(protocol_model=p_rot, analyte=a, order=i))
    protocols.append(p_rot)

    p_mri = ProtocolModel.query.filter_by(name="Body Composition (MRI)").first() or ProtocolModel(name="Body Composition (MRI)", severity=Severity.NONE)
    if not p_mri.id:
        db.session.add(p_mri); db.session.flush()
        for i, a in enumerate(bc_analytes): db.session.add(ProtocolAnalyteAssociation(protocol_model=p_mri, analyte=a, order=i))
    protocols.append(p_mri)

    h_set = HousingConditionSet.query.filter_by(name="Metabolic Cages").first()
    if not h_set:
        h_set = HousingConditionSet(name="Metabolic Cages"); db.session.add(h_set); db.session.flush()

    # Create Teams, Users, Projects
    for i in range(teams):
        t = Team(name=f"{fake.city()} RC {random.randint(10,99)}")
        db.session.add(t); db.session.flush()

        u = User(email=f"sim_admin_{i}@lab.com", is_active=True, email_confirmed=True)
        u.set_password("password")
        if not User.query.filter_by(email=u.email).first():
            db.session.add(u); db.session.flush()
            admin_service.invite_user_to_team(u.email, t)
        else:
            u = User.query.filter_by(email=u.email).first()

        ea = EthicalApproval(
            reference_number=f"EA-SIM-{i}-{random.randint(100,999)}",
            title=f"Simulation Study {i}",
            start_date=date.today()-timedelta(days=365), end_date=date.today()+timedelta(days=365),
            number_of_animals=1000, team_id=t.id, overall_severity=Severity.MODERATE
        )
        db.session.add(ea); db.session.flush()

        for p_idx in range(projects):
            # Use timestamp + random suffix for unique slugs across simulation runs
            unique_suffix = f"{datetime.now().strftime('%H%M%S')}{random.randint(10,99)}"
            proj = Project(name=f"Proj {fake.word().title()} {p_idx}", slug=f"S{i}P{p_idx}_{unique_suffix}", team_id=t.id, owner_id=u.id)
            db.session.add(proj); db.session.flush()
            db.session.add(ProjectEthicalApprovalAssociation(project_id=proj.id, ethical_approval_id=ea.id))

            for g_idx in range(groups):
                # Use numeric naming for scalability (works with any number of groups)
                group_name = f"Group {g_idx + 1:03d}"
                animal_data = []
                counter = 1
                for sex in ['Male', 'Female']:
                    for geno in ['WT', 'KO']:
                        for _ in range(animals):
                              animal_data.append({
                                  "ID": f"{proj.slug}-G{g_idx}-{counter}",
                                  "Date of Birth": (date.today()-timedelta(weeks=12)).isoformat(),
                                  "Sex": sex, "Genotype": geno, "Treatment": "Vehicle",
                                  "Cage": f"C{math.ceil(counter/5)}", "status": "alive"
                              })
                              counter += 1

                # Include team (i), project (p_idx), and group (g_idx) indices for guaranteed uniqueness
                group_id = f"{proj.slug}-G{g_idx:03d}"

                group = ExperimentalGroup(
                    id=group_id,
                    name=group_name, project_id=proj.id, team_id=t.id, owner_id=u.id, model_id=model.id,
                    ethical_approval_id=ea.id, animal_data=animal_data
                )
                db.session.add(group); db.session.flush()

                # Datatables
                base_date = date.today() - timedelta(weeks=12)

                # Define protocol schedule: (week_offset, protocol_name)
                protocol_schedule = [
                    (0, "Body Composition (MRI)"),
                    (4, "Glucose Tolerance Test (IPGTT)"),
                    (6, "Accelerating Rotarod")
                ]

                for w_offset, p_name in protocol_schedule:
                    proto = next(p for p in protocols if p.name == p_name)

                    # Create multiple repetitions of the same protocol
                    for rep in range(repetitions):
                        # Calculate date for this repetition
                        rep_date = base_date + timedelta(weeks=w_offset + (rep * repetition_interval))

                        # Create datatable for this repetition
                        dt = DataTable(
                            group_id=group.id,
                            protocol_id=proto.id,
                            date=rep_date.isoformat(),
                            creator_id=u.id,
                            housing_condition_set_id=h_set.id
                        )
                        db.session.add(dt); db.session.flush()

                        # Generate data for each animal in this repetition
                        for r_idx, anim in enumerate(animal_data):
                            # Add some variation for repetitions to simulate learning effects or biological variation
                            age_weeks = 12 + w_offset + (rep * repetition_interval)
                            vals = generate_realistic_data(p_name, anim['Sex'], anim['Genotype'], "Vehicle", age_weeks)

                            # For rotarod, add learning effect across repetitions
                            if p_name == "Accelerating Rotarod" and rep > 0:
                                # Learning effect: improve by 5-15% per repetition
                                learning_factor = 1.05 + (rep * 0.10)
                                for key in vals:
                                    if 'Rotarod' in key and isinstance(vals[key], (int, float)):
                                        vals[key] = min(vals[key] * learning_factor, vals[key] + 30)  # Cap the improvement

                            # For GTT, add potential metabolic adaptation
                            elif p_name == "Glucose Tolerance Test (IPGTT)" and rep > 0:
                                # Metabolic adaptation: slight improvement in glucose clearance
                                adaptation_factor = 0.95 - (rep * 0.03)  # Max 15% improvement
                                for key in vals:
                                    if 'Glucose' in key and isinstance(vals[key], (int, float)):
                                        vals[key] = max(vals[key] * adaptation_factor, vals[key] - 20)  # Cap the improvement

                            vals['ID'] = anim['ID']
                            db.session.add(ExperimentDataRow(data_table_id=dt.id, row_index=r_idx, row_data=vals))

    db.session.commit()
    print("Simulation complete.")
