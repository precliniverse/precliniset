import os
import shutil
import time
import subprocess
from .utils import console, run_command, get_architecture, confirm_action, IS_WINDOWS
from .config import ConfigManager
from .diagnostics import DockerManager

def _detect_new_migrations():
    """
    Detect if there are new migrations available that haven't been applied to the database.
    Returns True if new migrations are detected, False otherwise.
    """
    try:
        # Check if we can import Flask-Migrate (Alembic) components
        # This will work in both Docker and Native environments
        result = run_command("flask db current", check=False, capture_output=True)
        if result and "error" not in result.lower():
            # If we get a clean response, check if there are any pending migrations
            result = run_command("flask db heads", check=False, capture_output=True)
            if result and "error" not in result.lower():
                # Compare current head with available migrations
                # If there are new migration files in versions/ that aren't in the current head, we have new migrations
                current_head = run_command("flask db current", check=False, capture_output=True)
                if current_head and "error" not in current_head.lower():
                    # Check if there are migration files that are newer than the current head
                    # This is a simple check - if there are any .py files in versions/ that aren't the current head
                    import glob
                    migration_files = glob.glob("migrations/versions/*.py")
                    # If we have migration files and the current head doesn't match the latest file, we likely have new migrations
                    if migration_files:
                        # Get the latest migration file by timestamp (Alembic uses timestamp-based filenames)
                        latest_migration = max(migration_files)
                        latest_migration_name = os.path.basename(latest_migration).split('_')[0]

                        # Extract current head revision (if any)
                        if current_head and "Current revision for alembic" in current_head:
                            current_revision = current_head.split("Current revision for alembic")[1].strip()
                            if current_revision and current_revision != latest_migration_name:
                                return True

                        # If no current revision, we definitely have migrations to run
                        if "No current revision" in current_head or not current_revision:
                            return True

        # Fallback: Check if there are any migration files at all
        # If there are migration files and we can't determine current state, assume we might need to run them
        if os.path.exists("migrations/versions") and os.listdir("migrations/versions"):
            return True

    except Exception as e:
        console.print(f"[dim]Migration detection check failed: {e}[/dim]")
        # If we can't determine, assume no new migrations to avoid false positives
        pass

    return False

class DockerDeployer:
    """Docker-based deployment manager."""
    
    def __init__(self):
        self.compose_file = "docker-compose.yml"
        self.config = ConfigManager.load_env()
        if get_architecture() == 'armv7l':
             self.compose_file = "docker-compose-rpi2.yml"
             console.print("[info]Detected Raspberry Pi (ARMv7). Using optimized configurations.[/info]")

    def deploy(self, debug=False):
        console.rule("[bold cyan]Docker Deployment[/bold cyan]")
        
        # Pre-flight check
        ok, msg, details = DockerManager.check_docker()
        if not ok:
            console.print(f"[bold red]Cannot Proceed: {msg}[/bold red]")
            console.print(f"[dim]{details}[/dim]")
            console.print(DockerManager.get_install_instructions())
            return
        
        # Ensure directories
        for d in ["uploads", "logs", "instance", "migrations"]:
            if not os.path.exists(d):
                os.makedirs(d)
                console.print(f"[green]Created directory: {d}[/green]")

        # Set debug env
        env = os.environ.copy()
        if debug:
            env['DEBUG'] = '1'

        run_command(f"docker compose -f {self.compose_file} build", env=env)
        run_command(f"docker compose -f {self.compose_file} up -d", env=env)
        self._init_data(debug=debug)
        console.print("[bold green]Application Deployed (Docker)[/bold green]")
        
        config = ConfigManager.load_env()
        port = config.get('APP_PORT', '8000')
        console.print(f"[info]Application should be available at http://localhost:{port}[/info]")

    def update(self):
        console.print("[info]Pulling latest code...[/info]")
        run_command("git pull", check=False)

        # Check for new migrations after pulling code
        if _detect_new_migrations():
            console.print("[warning]New database migrations detected![/warning]")
            if confirm_action("Would you like to run database migrations and restart the application?", default=True):
                console.print("[info]Running database migrations...[/info]")
                env = os.environ.copy()
                run_command(f'docker compose -f {self.compose_file} run --rm web flask db upgrade', env=env)

                console.print("[info]Restarting application services...[/info]")
                run_command(f"docker compose -f {self.compose_file} restart")
                console.print("[success]Database migrations applied and application restarted![/success]")
            else:
                console.print("[info]Skipping database migrations. You can run them later with: docker compose run --rm web flask db upgrade[/info]")
        else:
            console.print("[info]No new database migrations detected.[/info]")

        # Continue with normal deployment process
        self.deploy()

    def _is_running(self):
        """Check if Docker containers are running."""
        try:
            result = subprocess.run(["docker", "compose", "-f", self.compose_file, "ps"], shell=False, capture_output=True, text=True, check=True)
            # Check if any service is running (Up status)
            return "Up" in result.stdout
        except subprocess.CalledProcessError:
            return False

    def start(self):
        if self._is_running():
            console.print("[info]Services are running. Restarting...[/info]")
            run_command(f"docker compose -f {self.compose_file} restart")
        else:
            run_command(f"docker compose -f {self.compose_file} up -d")
    def stop(self): run_command(f"docker compose -f {self.compose_file} stop")
    def logs(self): run_command(f"docker compose -f {self.compose_file} logs -f --tail=100", capture_output=False)
    
    def _init_data(self, debug=False):
        if confirm_action("Run initial migrations & setup?", default=True):
             env = os.environ.copy()
             if debug:
                 env['DEBUG'] = '1'
             script = "flask db upgrade && flask setup init-admin && flask setup static-resources"
             
             # Check if migrations exist, if not, create them first
             if not os.path.exists(os.path.join("migrations", "versions")) or not os.listdir(os.path.join("migrations", "versions")):
                 console.print("[yellow]No migrations found. Generating initial baseline...[/yellow]")
                 script = "flask db migrate -m 'Initial_Baseline' && " + script

             run_command(f'docker compose -f {self.compose_file} run --rm web /bin/bash -c "{script}"', env=env)

    def run_flask(self, command):
        """Run a flask command inside the container."""
        run_command(f'docker compose -f {self.compose_file} run --rm web flask {command}')

    def build_release(self, tag=None):
        """Build a publishable release package."""
        if not tag:
            try:
                with open("VERSION", "r") as f:
                    tag = f.read().strip()
            except FileNotFoundError:
                tag = f"v{time.strftime('%Y.%m.%d')}"
        
        image_name = f"precliniset:{tag}"
        console.print(f"[info]Building release image: [bold]{image_name}[/bold]...[/info]")
        
        # 1. Build the image
        try:
            run_command(f"docker build -t {image_name} .")
        except Exception as e:
            console.print(f"[bold red]Build failed: {e}[/bold red]")
            return

        # 2. Prepare dist folder
        dist_dir = "dist"
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

        # 3. Create production compose file
        try:
            with open(self.compose_file, 'r') as f:
                content = f.read()
            
            # Remove 'build: .' and replace with the new image tag for the 'web' and 'celery_worker' services
            # This is a very basic string replacement, but for our yaml structure it works
            import re
            # Replace build: . for web and celery_worker
            content = re.sub(r'build:\s+\.', f'image: {image_name}', content)
            
            with open(os.path.join(dist_dir, "docker-compose.yml"), 'w') as f:
                f.write(content)
            
            # 4. Create DEPLOY.txt
            with open(os.path.join(dist_dir, "DEPLOY.txt"), 'w') as f:
                f.write("Precliniset Deployment Package\n")
                f.write("="*30 + "\n\n")
                f.write(f"Version: {tag}\n")
                f.write(f"Release Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("To deploy this package:\n")
                f.write("1. Copy the contents of this folder to your server.\n")
                f.write("2. Ensure you have a .env file (you can use 'python manage.py setup' to generate one).\n")
                f.write("3. Run: docker compose up -d\n\n")
                f.write("Note: This package assumes the image 'precliniset:" + tag + "' is available locally or in a registry.\n")

            console.print(f"[bold green]Release created successfully in '{dist_dir}/'[/bold green]")
            console.print(f"Package contains: docker-compose.yml, DEPLOY.txt")
        except Exception as e:
             console.print(f"[bold red]Failed to create dist package: {e}[/bold red]")

class NativeDeployer:
    """Manual deployment manager with robust environment setup."""
    
    def deploy(self, debug=False):
        console.rule("[bold cyan]Native Deployment[/bold cyan]")
        
        # Set debug env
        if debug:
            os.environ['DEBUG'] = '1'
        
        # venv setup
        venv_dir = ".venv" if os.path.exists(".venv") else "venv"
        
        if not os.path.exists(venv_dir):
            console.print("[info]Creating virtual environment...[/info]")
            import venv
            venv.create(venv_dir, with_pip=True)
        
        if IS_WINDOWS:
            python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
            pip_exec = os.path.join(venv_dir, "Scripts", "pip.exe")
        else:
            python_exec = os.path.join(venv_dir, "bin", "python")
            pip_exec = os.path.join(venv_dir, "bin", "pip")
        
        # Dependencies
        console.print("[info]Installing dependencies...[/info]")
        run_command(f'"{pip_exec}" install -r requirements.txt')

        # Build Documentation
        console.print("[info]Building documentation...[/info]")
        run_command(f'"{python_exec}" -m mkdocs build')

        # Directories
        for d in ["uploads", "logs", "instance", "migrations"]:
            if not os.path.exists(d):
                os.makedirs(d)
                
        # Migrations and Init
        console.print("[info]Initializing database...[/info]")
        migrations_env = os.path.join("migrations", "env.py")
        
        if os.path.exists(migrations_env):
             run_command(f'"{python_exec}" -m flask db upgrade', check=False)
        else:
             console.print("[bold red]CRITICAL: 'migrations/' directory missing![/bold red]")
             console.print("   The database schema cannot be initialized without migration scripts.")
             console.print("   Please ensure you have pulled the latest code with 'git pull'.")
             # We do NOT auto-generate migrations here on production/deployment. 
             # That is a development task.
             return
        
        # Precliniset specific custom setup commands
        console.print("[info]Running application setup/seed...[/info]")
        run_command(f'"{python_exec}" -m flask setup init-admin', check=False)
        run_command(f'"{python_exec}" -m flask setup static-resources', check=False)
        
        config = ConfigManager.load_env()
        if config.get('DEMO_DATA', '').lower() == 'true':
            console.print("[info]Populating with demo data...[/info]")
            run_command(f'"{python_exec}" -m flask setup populate-simulation', check=False)
             
        console.print("[bold green]Native deployment complete![/bold green]")

    def update(self):
        console.print("[info]Pulling latest code...[/info]")
        run_command("git pull", check=False)

        # Check for new migrations after pulling code
        if _detect_new_migrations():
            console.print("[warning]New database migrations detected![/warning]")
            if confirm_action("Would you like to run database migrations and restart the application?", default=True):
                console.print("[info]Running database migrations...[/info]")

                # Get the virtual environment path
                venv_dir = ".venv" if os.path.exists(".venv") else "venv"
                if IS_WINDOWS:
                    python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
                else:
                    python_exec = os.path.join(venv_dir, "bin", "python")

                run_command(f'"{python_exec}" -m flask db upgrade')

                console.print("[info]Restarting application services...[/info]")
                self.stop()
                time.sleep(2)  # Give processes time to stop
                self.start()
                console.print("[success]Database migrations applied and application restarted![/success]")
            else:
                console.print("[info]Skipping database migrations. You can run them later with: flask db upgrade[/info]")
        else:
            console.print("[info]No new database migrations detected.[/info]")

        # Continue with normal deployment process
        self.deploy()

    def run_flask(self, command):
        """Run a flask command in the virtual environment."""
        venv_dir = ".venv" if os.path.exists(".venv") else "venv"
        if IS_WINDOWS:
            python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            python_exec = os.path.join(venv_dir, "bin", "python")
        
        run_command(f'"{python_exec}" -m flask {command}')

    def start(self):
        # Stop any running services first to ensure restart behavior
        self.stop()
        time.sleep(1)  # Brief pause to ensure processes are fully stopped

        config = ConfigManager.load_env()
        port = config.get('APP_PORT', '8000')
        venv_dir = ".venv" if os.path.exists(".venv") else "venv"

        # Ensure logs directory
        if not os.path.exists("logs"):
            os.makedirs("logs")

        if IS_WINDOWS:
            python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
            
            # 1. Start Web Service (Waitress)
            web_log = os.path.join("logs", "startup.log")
            web_pid = os.path.join("logs", "waitress.pid")

            web_pid_swapped = web_pid.replace('\\', '/')
            cmd = f'start /B "" "{python_exec}" -c "import os; open(\'{web_pid_swapped}\', \'w\').write(str(os.getpid())); from waitress import serve; from app import create_app; serve(create_app(), host=\'0.0.0.0\', port={port})" > "{web_log}" 2>&1'
            subprocess.run(cmd, shell=True)  # nosec B602
            console.print(f"[success]Started Web service on http://localhost:{port} (Waitress)[/success]")

            # 2. Start Celery Worker
            celery_log = os.path.join("logs", "celery.log")
            celery_pid = os.path.join("logs", "celery.pid")

            # Celery on Windows requires pool=solo for reliability
            cmd = f'start /B "" "{python_exec}" -m celery -A celery_worker.celery_app worker --loglevel=info --pool=solo --pidfile="{celery_pid}" > "{celery_log}" 2>&1'
            subprocess.run(cmd, shell=True)  # nosec B602
            console.print(f"[success]Started Celery worker (solo pool)[/success]")

        else:
            python_exec = os.path.join(venv_dir, "bin", "python")
            
            # 1. Start Web Service (Gunicorn)
            pid_file = os.path.join("logs", "gunicorn.pid")
            log_file = os.path.join("logs", "gunicorn.log")
            cmd = f'"{python_exec}" -m gunicorn -w 4 -b 0.0.0.0:{port} --pid "{pid_file}" --access-logfile "{log_file}" --error-logfile "{log_file}" --capture-output --daemon "app:create_app()"'
            run_command(cmd, check=False)
            console.print(f"[success]Started Web service on http://localhost:{port} (Gunicorn)[/success]")

            # 2. Start Celery Worker (Daemonized on Linux)
            celery_pid = os.path.join("logs", "celery.pid")
            celery_log = os.path.join("logs", "celery.log")
            # For Linux, we use --detach to run in background
            cmd = f'"{python_exec}" -m celery -A celery_worker.celery_app worker --loglevel=info --detach --pidfile="{celery_pid}" --logfile="{celery_log}"'
            run_command(cmd, check=False)
            console.print("[success]Started Celery worker (prefork pool)[/success]")

    def _is_running(self, pid_file):
        """Check if a process is running based on its PID file."""
        if not os.path.exists(pid_file):
            return False
        try:
            with open(pid_file, 'r') as f:
                pid = f.read().strip()
                if not pid: return False
                
            if IS_WINDOWS:
                check_cmd = f'tasklist /FI "PID eq {pid}" /NH'
                res = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)  # nosec B602
                return pid in res.stdout
            else:
                try:
                    os.kill(int(pid), 0)
                    return True
                except OSError:
                    return False
        except Exception:
            return False

    def stop(self):
        services = [
            ("Web", os.path.join("logs", "waitress.pid") if IS_WINDOWS else os.path.join("logs", "gunicorn.pid")),
            ("Celery Worker", os.path.join("logs", "celery.pid"))
        ]
        
        for name, pid_file in services:
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid = f.read().strip()
                    if not pid:
                         os.remove(pid_file)
                         continue

                    if IS_WINDOWS:
                        # Try to kill gracefully first? No, for background start /B, taskkill /F /T is safer
                        subprocess.run(f'taskkill /PID {pid} /F /T', shell=True, capture_output=True)  # nosec B602
                    else:
                        os.kill(int(pid), 15)
                    
                    console.print(f"[info]Stopped {name} (PID: {pid})[/info]")
                except Exception as e:
                    console.print(f"[error]Failed to stop {name}: {e}[/error]")
                finally:
                    if os.path.exists(pid_file):
                        os.remove(pid_file)
            else:
                console.print(f"[dim]No running {name} found (PID file missing)[/dim]")
    
    def logs(self):
        log_files = [
            os.path.join("logs", "celery.log"),
            os.path.join("logs", "startup.log") if IS_WINDOWS else os.path.join("logs", "gunicorn.log")
        ]

        # Check if any log files exist
        existing_logs = [f for f in log_files if os.path.exists(f)]
        if not existing_logs:
            console.print("[warning]No logs found yet. Waiting...[/warning]")
            existing_logs = log_files  # Still try to tail them in case they get created

        try:
            if not IS_WINDOWS:
                # Use system tail -f for better performance on Linux, supports multiple files
                log_args = ' '.join(f'"{f}"' for f in log_files)
                subprocess.run(f'tail -f {log_args}', shell=True)  # nosec B602
            else:
                # Python implementation of tail -f for Windows, extended for multiple files
                positions = {f: 0 for f in log_files}
                while True:
                    for log_file in log_files:
                        try:
                            with open(log_file, 'r') as f:
                                f.seek(positions[log_file])
                                lines = f.readlines()
                                if lines:
                                    print(f"==> {os.path.basename(log_file)} <==")
                                    for line in lines:
                                        print(line, end='')
                                    positions[log_file] = f.tell()
                        except FileNotFoundError:
                            pass  # File might not exist yet
                    time.sleep(0.1)
        except KeyboardInterrupt:
            console.print("\n[info]Log streaming stopped.[/info]")
