import os
import shutil
try:
    from rich.prompt import Prompt, Confirm
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class Prompt:
        @staticmethod
        def ask(prompt, choices=None, default=None, password=False, show_default=True):
            # Basic fallback
            p_text = prompt.replace("[warning]", "").replace("[/warning]", "")\
                           .replace("[cyan]", "").replace("[/cyan]", "")
            
            if choices:
                p_text += f" ({'/'.join(choices)})"
            if default and show_default:
                p_text += f" [{default}]"
            
            p_text += ": "
            
            while True:
                if password:
                    import getpass
                    val = getpass.getpass(p_text)
                else:
                    val = input(p_text)
                
                val = val.strip()
                if not val and default is not None:
                    return default
                
                if choices:
                    if val in choices:
                        return val
                    print(f"Please select one of: {', '.join(choices)}")
                else:
                    return val

    class Confirm:
        @staticmethod
        def ask(prompt, default=False): # Note: rich Confirm defaults to True usually check usage
            from .utils import confirm_action
            clean_prompt = prompt.replace("[warning]", "").replace("[/warning]", "")
            return confirm_action(clean_prompt, default=default)

from .utils import console, confirm_action, get_architecture
from .config import ConfigManager, generate_secret, ENV_FILE
from .diagnostics import DatabaseManager, PortManager, RedisManager

class ConfigWizard:
    def __init__(self):
        # Load existing config for defaults
        self.config = ConfigManager.load_env()
        # Ensure minimal defaults if completely empty
        if not self.config:
            self.config = {}

    def _pre_deployment_checks(self):
        """Run pre-deployment system checks to guide user."""
        console.print("\n[yellow]--- Pre-Deployment System Check ---[/yellow]")
        console.print("Checking your system readiness...\n")
        
        import platform
        system = platform.system().lower()
        arch = get_architecture()
        
        # OS and Architecture
        console.print(f"[cyan]OS:[/cyan] {system.capitalize()} ({arch})")
        
        # Docker check if planning Docker
        console.print("[cyan]Docker:[/cyan] Checking availability...")
        try:
            import subprocess
            subprocess.run("docker info", shell=True, check=True, capture_output=True, timeout=5)
            console.print("[green]✓ Docker is running[/green]")
            
            # Check compose
            try:
                result = subprocess.run("docker compose version", shell=True, capture_output=True, text=True)
                console.print(f"[cyan]Docker Compose:[/cyan] {result.stdout.strip()}")
            except:
                console.print("[red]✗ Docker Compose not available[/red]")
        except subprocess.CalledProcessError:
            console.print("[red]✗ Docker not running or not installed[/red]")
            console.print("[dim]For Docker deployment, ensure Docker Desktop (Windows/Mac) or Docker Engine (Linux) is installed and running.[/dim]")
        except subprocess.TimeoutExpired:
            console.print("[red]✗ Docker check timeout[/red]")
        
        # Python version
        import sys
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        console.print(f"[cyan]Python:[/cyan] {py_version}")
        if sys.version_info < (3, 8):
            console.print("[red]✗ Python 3.8+ required[/red]")
        else:
            console.print("[green]✓ Python version OK[/green]")
        
        # Required directories
        dirs = ["uploads", "logs", "instance", "migrations"]
        missing = [d for d in dirs if not os.path.exists(d)]
        if missing:
            console.print(f"[yellow]⚠ Missing directories: {', '.join(missing)}[/yellow]")
            console.print("[dim]These will be created during deployment.[/dim]")
        else:
            console.print("[green]✓ Required directories present[/green]")
        
        # Port check (basic)
        console.print(f"[cyan]Port 8000:[/cyan] Checking availability...")
        if PortManager.check_port_available("8000"):
            console.print("[green]✓ Port 8000 available[/green]")
        else:
            console.print("[yellow]⚠ Port 8000 in use - wizard will suggest alternatives[/yellow]")
        
        console.print("\n[dim]Note: Full system validation will be performed during 'manage.py health'[/dim]")
        console.print("=" * 60)

    def run(self):
        console.rule("[bold magenta]Configuration Wizard[/bold magenta]")
        
        mode = "New"
        if os.path.exists(ENV_FILE):
             if Confirm.ask(f"Existing configuration found. Edit it?", default=True):
                 mode = "Edit"
                 console.print("[info]Loaded existing settings. Press Enter to keep current values.[/info]")
             else:
                 if Confirm.ask("Overwrite with fresh defaults?"):
                     self.config = {}
                     mode = "New"
                 else:
                     return

        self._pre_deployment_checks()
        self._ask_deployment_mode()
        self._ask_env_basic()
        self._ask_security()
        self._ask_database()
        self._ask_redis()
        self._ask_mail()
        self._save()

    def _ask_deployment_mode(self):
        console.print("\n[cyan]--- Deployment Mode ---[/cyan]")
        console.print("1. Docker (Recommended for ease of use)")
        console.print("2. Native (Python + Systemd - Recommended for performance/servers)")
        
        current_mode = self.config.get('DEPLOYMENT_MODE', 'docker')
        default_choice = "1" if current_mode == 'docker' else "2"
        
        choice = Prompt.ask("Choice", choices=["1", "2"], default=default_choice)
        self.config['DEPLOYMENT_MODE'] = 'docker' if choice == '1' else 'native'

    def _ask_env_basic(self):
        self.config['APP_PORT'] = Prompt.ask("Application Port", default=self.config.get('APP_PORT', '8000'))
        
        console.print("\n[cyan]--- Environment Profile ---[/cyan]")
        console.print("1. Production")
        console.print("2. Development")
        
        is_debug = self.config.get('FLASK_DEBUG') == '1'
        default_choice = "2" if is_debug else "1"
        
        if Prompt.ask("Choice", choices=["1", "2"], default=default_choice) == "2":
            self.config['FLASK_DEBUG'] = '1'
            self.config['APP_LOG_LEVEL'] = 'DEBUG'
        else:
            self.config['FLASK_DEBUG'] = '0'
            self.config['APP_LOG_LEVEL'] = Prompt.ask("Log Level", default=self.config.get('APP_LOG_LEVEL', 'INFO'))

    def _ask_security(self):
        if 'SECRET_KEY' not in self.config:
            self.config['SECRET_KEY'] = generate_secret(50)
        if 'SECURITY_PASSWORD_SALT' not in self.config:
            self.config['SECURITY_PASSWORD_SALT'] = generate_secret(20)
        
        console.print("\n[cyan]--- Super Admin ---[/cyan]")
        self.config['SUPERADMIN_EMAIL'] = Prompt.ask("Admin Email", default=self.config.get('SUPERADMIN_EMAIL', "admin@precliniverse.com"))
        
        # Don't show existing password, but allow changing
        pwd_prompt = "Admin Password (leave empty to keep current)" if 'SUPERADMIN_PASSWORD' in self.config else "Admin Password"
        new_pwd = Prompt.ask(pwd_prompt, password=True)
        
        if new_pwd:
             self.config['SUPERADMIN_PASSWORD'] = new_pwd
        elif 'SUPERADMIN_PASSWORD' not in self.config:
             self.config['SUPERADMIN_PASSWORD'] = generate_secret(12)
        
        console.print("\n[cyan]--- Inter-App Communication Keys ---[/cyan]")
        self.config['SERVICE_API_KEY'] = generate_secret(32)
        console.print("[green]Generated SERVICE_API_KEY for ecosystem communication.[/green]")
        
        self.config['SSO_SECRET_KEY'] = generate_secret(32)
        console.print("[green]Generated SSO_SECRET_KEY for seamless login.[/green]")
        
        console.print("\n[cyan]--- Training Manager Integration ---[/cyan]")
        current_tm = self.config.get('TM_ENABLED', 'False') == 'True'
        if Confirm.ask("Configure Training Manager integration?", default=current_tm):
            default_tm_url = "http://training-manager:5001" if self.config.get('DEPLOYMENT_MODE') == 'docker' else "http://localhost:5001"
            # Use existing if available
            tm_backend = self.config.get('TM_API_URL', default_tm_url)
            self.config['TM_API_URL'] = Prompt.ask("Training Manager API URL (Backend)", default=tm_backend, show_default=True)
            self.config['TM_PUBLIC_URL'] = Prompt.ask("Training Manager Public URL (Frontend)", default="http://localhost:5001")
            self.config['TM_API_KEY'] = generate_secret(32)
            console.print(f"[green]Generated TM_API_KEY: {self.config['TM_API_KEY']}[/green]")
            console.print("[bold yellow]IMPORTANT: Copy this key to Training Manager's .env as SERVICE_API_KEY[/bold yellow]")
            self.config['TM_ENABLED'] = 'True'
        else:
            self.config['TM_ENABLED'] = 'False'
            console.print("[dim]Training Manager integration disabled.[/dim]")

    def _ask_database(self):
        console.print("\n[cyan]--- Database ---[/cyan]")
        profiles = self.config.get('COMPOSE_PROFILES', '').split(',')
        profiles = [p for p in profiles if p] # clean empty
        
        if self.config['DEPLOYMENT_MODE'] == 'docker':
            console.print("1. Internal Container (MariaDB)")
            console.print("2. External (e.g. Host/Cloud)")
            c = Prompt.ask("Choice", choices=["1", "2"], default="1")
            
            if c == '1':
                self.config['DB_TYPE'] = 'mysql'
                self.config['DB_HOST'] = 'db'
                self.config['DB_NAME'] = 'precliniverse'
                self.config['DB_USER'] = 'appuser'
                self.config['DB_PASSWORD'] = generate_secret(16)
                self.config['DB_ROOT_PASSWORD'] = generate_secret(16)
                
                arch = get_architecture()
                if arch == 'armv7l':
                    self.config['DB_IMAGE'] = 'yobasystems/alpine-mariadb'
                else:
                    self.config['DB_IMAGE'] = 'mariadb:latest'
                
                if 'mysql' not in profiles: profiles.append('mysql')
            else:
                self._ask_external_db()
                if 'mysql' in profiles: profiles.remove('mysql')
        else:
            console.print("1. SQLite (Easiest for Native)")
            console.print("2. External/Local MySQL/MariaDB")
            
            default_choice = "2" if self.config.get('DB_TYPE') == 'mysql' else "1"
            
            c = Prompt.ask("Choice", choices=["1", "2"], default=default_choice)
            if c == '1':
                self.config['DB_TYPE'] = 'sqlite'
            else:
                self._ask_external_db()
        
        self.config['COMPOSE_PROFILES'] = ','.join(profiles)

    def _ask_external_db(self):
        default_host = "host.docker.internal" if self.config.get('DEPLOYMENT_MODE') == 'docker' else "localhost"
        
        self.config['DB_TYPE'] = 'mysql'
        self.config['DB_HOST'] = Prompt.ask("DB Host", default=self.config.get('DB_HOST', default_host))
        self.config['DB_PORT'] = Prompt.ask("DB Port", default=self.config.get('DB_PORT', "3306"))
        self.config['DB_NAME'] = Prompt.ask("DB Name", default=self.config.get('DB_NAME', "precliniverse"))
        self.config['DB_USER'] = Prompt.ask("DB User", default=self.config.get('DB_USER'))
        
        # Careful with password prompt default
        if 'DB_PASSWORD' in self.config:
            new_pass = Prompt.ask("DB Password (leave empty to keep)", password=True)
            if new_pass:
                self.config['DB_PASSWORD'] = new_pass
        else:
            self.config['DB_PASSWORD'] = Prompt.ask("DB Password", password=True)
        
        # Test connection?
        # Note: In Docker mode, we can't easily test connection to 'host.docker.internal' from HOST script 
        # unless we assume 'localhost' maps to it, which isn't always true. 
        # But if user says "localhost" in Native mode, we CAN test.
        if self.config.get('DEPLOYMENT_MODE') == 'native' or self.config['DB_HOST'] in ['localhost', '127.0.0.1']:
            if Confirm.ask("Test connection now?"):
                console.print("[info]Testing database connection...[/info]")
                success, msg = DatabaseManager.test_connection(self.config)
                if success:
                    console.print(f"[green]{msg}[/green]")
                else:
                    console.print(f"[red]Connection failed: {msg}[/red]")
                    if not Confirm.ask("Continue anyway?"):
                        self._ask_database()
                        return

    def _ask_redis(self):
        console.print("\n[cyan]--- Redis ---[/cyan]")
        profiles = self.config.get('COMPOSE_PROFILES', '').split(',')
        profiles = [p for p in profiles if p]
        
        if self.config['DEPLOYMENT_MODE'] == 'docker':
            console.print("1. Internal Container")
            console.print("2. External (e.g. Host/Cloud)")
            c = Prompt.ask("Choice", choices=["1", "2"], default="1")
            
            if c == '1':
                 self.config['CELERY_BROKER_URL'] = 'redis://redis:6379/1'
                 self.config['CELERY_RESULT_BACKEND'] = 'redis://redis:6379/2'
                 if 'redis' not in profiles: profiles.append('redis')
            else:
                 current_host = "host.docker.internal"
                 current_port = "6379"
                 # Try to parse existing URL if available
                 if 'redis:6379' not in self.config.get('CELERY_BROKER_URL', '') and 'redis://' in self.config.get('CELERY_BROKER_URL', ''):
                     try:
                         # Very basic parse: redis://host:port/db
                         parts = self.config['CELERY_BROKER_URL'].split('://')[1].split('/')[0].split(':')
                         if len(parts) >= 1: current_host = parts[0]
                         if len(parts) >= 2: current_port = parts[1]
                     except: pass

                 redis_host = Prompt.ask("Redis Host", default=current_host)
                 redis_port = Prompt.ask("Redis Port", default=current_port)
                 self.config['CELERY_BROKER_URL'] = f'redis://{redis_host}:{redis_port}/1'
                 self.config['CELERY_RESULT_BACKEND'] = f'redis://{redis_host}:{redis_port}/2'
                 if 'redis' in profiles: profiles.remove('redis')
        else:
             redis_host = Prompt.ask("Redis Host", default="localhost")
             redis_port = Prompt.ask("Redis Port", default="6379")
             url = f'redis://{redis_host}:{redis_port}/1'
             self.config['CELERY_BROKER_URL'] = url
             self.config['CELERY_RESULT_BACKEND'] = f'redis://{redis_host}:{redis_port}/2'
             
             # Test connection
             from .diagnostics import RedisManager
             if Confirm.ask("Test Redis connection?"):
                 success, msg = RedisManager.test_connection(url)
                 if success:
                     console.print(f"[green]{msg}[/green]")
                 else:
                     console.print(f"[red]Connection failed: {msg}[/red]")
                     if not Confirm.ask("Continue anyway?"):
                         self._ask_redis()
                         return

        self.config['COMPOSE_PROFILES'] = ','.join(profiles)

    def _ask_mail(self):
        console.print("\n[cyan]--- Email Configuration (SMTP) ---[/cyan]")
        has_mail = 'MAIL_SERVER' in self.config
        if Confirm.ask("Configure Email?", default=has_mail):
            self.config['MAIL_SERVER'] = Prompt.ask("SMTP Server", default=self.config.get('MAIL_SERVER'))
            self.config['MAIL_PORT'] = Prompt.ask("SMTP Port", default=self.config.get('MAIL_PORT', "587"))
            self.config['MAIL_Use_TLS'] = 'True'
            self.config['MAIL_USERNAME'] = Prompt.ask("Username", default=self.config.get('MAIL_USERNAME'))
            
            if 'MAIL_PASSWORD' in self.config:
                new_pass = Prompt.ask("Password (leave empty to keep)", password=True)
                if new_pass:
                    self.config['MAIL_PASSWORD'] = new_pass
            else:
                self.config['MAIL_PASSWORD'] = Prompt.ask("Password", password=True)

            self.config['MAIL_DEFAULT_SENDER'] = Prompt.ask("Sender Email", default=self.config.get('MAIL_DEFAULT_SENDER'))

    def _save(self):
        # Check port
        app_port = self.config.get('APP_PORT', '8000')
        console.print(f"[info]Checking port {app_port} availability...[/info]")
        
        if not PortManager.check_port_available(app_port):
            console.print(f"[warning]Port {app_port} is already in use![/warning]")
            alternatives = PortManager.suggest_alternative_ports(app_port, 3)
            
            if alternatives:
                choice = Prompt.ask(f"Choose alternative or use {app_port}", choices=[str(p) for p in alternatives] + [app_port], default=app_port)
                self.config['APP_PORT'] = choice
        else:
            console.print(f"[green]Port {app_port} is available[/green]")
        
        with open(ENV_FILE, 'w') as f:
            for k, v in self.config.items():
                f.write(f"{k}={v}\n")
        console.print(f"[success]Configuration saved to {ENV_FILE}[/success]")
