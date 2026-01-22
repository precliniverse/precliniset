#!/usr/bin/env python3
import sys
import argparse
import os
import subprocess
import platform

def check_dependencies():
    """Check if critical dependencies are installed."""
    missing = []
    try:
        import flask
    except ImportError:
        missing.append("flask")
    
    try:
        import rich
    except ImportError:
        missing.append("rich")
        
    try:
        import deepdiff
    except ImportError:
        missing.append("deepdiff")
        
    return missing

def install_dependencies():
    """Create venv and install requirements."""
    import subprocess
    import sys
    import os

    venv_dir = ".venv"
    print(f"\n[info] Setting up environment in {venv_dir}...")
    
    try:
        if not os.path.exists(venv_dir):
            subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)
            print(f"[success] Virtual environment created.")
        
        if os.name == 'nt':
            pip_exec = os.path.join(venv_dir, "Scripts", "pip.exe")
            python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            pip_exec = os.path.join(venv_dir, "bin", "pip")
            python_exec = os.path.join(venv_dir, "bin", "python")

        print("[info] Installing requirements.txt...")
        subprocess.run([pip_exec, "install", "-r", "requirements.txt"], check=True)
        print("[success] Dependencies installed successfully.")
        
        print("\n" + "="*50)
        print(" 🎉 ENVIRONMENT READY")
        print("="*50)
        print(f" To continue, run: {python_exec} manage.py")
        print("="*50 + "\n")
        sys.exit(0)
    except Exception as e:
        print(f"[error] Installation failed: {e}")
        sys.exit(1)

def main():
    # 1. Dependency Check
    missing = check_dependencies()
    if missing:
        # --- AUTO-PIVOT TO VENV ---
        import os
        import subprocess
        venv_dir = ".venv" if os.path.exists(".venv") else "venv"
        
        if os.name == 'nt':
            python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            python_exec = os.path.join(venv_dir, "bin", "python")

        # If venv exists and we are not already using it, pivot!
        if os.path.exists(python_exec) and os.path.abspath(sys.executable) != os.path.abspath(python_exec):
            # Check if this venv actually has the dependencies (don't loop if it's broken)
            # We don't want to loop, so we just try to run it. If it fails there, it will show the prompt.
            print(f" [info] Virtual environment detected at {venv_dir}. Switching interpreter...")
            try:
                # Pass all arguments to the venv interpreter
                res = subprocess.run([python_exec] + sys.argv)
                sys.exit(res.returncode)
            except Exception as e:
                print(f" [warning] Switch to venv failed: {e}")

        # Show friendly notification instead of blocking prompt
        print("\n" + "ℹ"*50)
        print(" ℹ️  OPTIONAL: Enhanced experience available")
        print("ℹ"*50)
        print(f" Missing packages: {', '.join(missing)}")
        print("\n For the full development experience with all features:")
        print("   → Run: pip install -r requirements.txt")
        print("   → Or use: python manage.py (and select 'Yes' to auto-install)")
        print("\n Docker deployment works fine without these packages.")
        print("ℹ"*50 + "\n")

    # 2. Lazy imports to avoid crashing before check
    try:
        # Try importing from cli_core first (New architecture)
        try:
            from cli_core.menu import InteractiveMenu
        except ImportError:
            # Fallback to app.cli.menu
            from app.cli.menu import InteractiveMenu
            
        from app.cli.main import main as cli_main
        
        # Interactive menu only when explicitly requested or no arguments provided
        if len(sys.argv) == 1:
            try:
                menu = InteractiveMenu()
                menu.run()
                sys.exit(0)
            except KeyboardInterrupt:
                print("\nGoodbye!")
                sys.exit(0)

        parser = argparse.ArgumentParser(description="Precliniset CLI")
        parser.add_argument('--debug', action='store_true', help='Enable debug mode')
        parser.add_argument('--interactive', action='store_true', help='Launch interactive dashboard')
        args, unknown = parser.parse_known_args()

        if args.interactive:
            try:
                menu = InteractiveMenu()
                menu.run()
            except KeyboardInterrupt:
                print("\nGoodbye!")
        else:
            cli_main()

    except ImportError as e:
        # FALLBACK MODE for missing dependencies (e.g. Flask)
        if "No module named 'flask'" in str(e) or "No module named 'app'" in str(e):
            # Only show warning if we didn't already show the "Missing packages" banner
            if not missing:
                print("\n" + "!"*60)
                print(" RUNNING IN MINIMAL FALLBACK MODE")
                print(" Critical dependencies (Flask) are missing.")
                print(" Only 'deploy' (Docker), 'setup' and 'logs' commands are available.")
                print("!"*60 + "\n")
            
            # Detect Architecture for RPi
            compose_file = "docker-compose.yml"
            arch = platform.machine().lower()
            if arch in ['armv7l', 'armv6l']:
                 compose_file = "docker-compose-rpi2.yml"
                 print(f" Detected Raspberry Pi ({arch}). Using {compose_file}\n")

            # Support basic setup even in fallback
            try:
                from cli_core.wizard import ConfigWizard
                HAS_WIZARD = True
            except ImportError:
                HAS_WIZARD = False

            # Simple Argument Handling
            if len(sys.argv) > 1:
                cmd = sys.argv[1].lower()
            else:
                # DEFAULT to dashboard even in minimal mode!
                cmd = "dashboard"

            if cmd in ['--help', '-h']:
                print("Available commands in Minimal Mode:")
                print("  python manage.py dashboard -> Launch interactive dashboard (Recommended)")
                print("  python manage.py setup     -> Configure environment (.env)")
                print("  python manage.py deploy    -> Build and start Docker containers")
                print("  python manage.py logs      -> View live logs")
                sys.exit(0)

            if cmd == "setup":
                if HAS_WIZARD:
                    wizard = ConfigWizard()
                    wizard.run()
                else:
                    print("[error] Could not launch configuration wizard. Missing cli_core files.")
                    sys.exit(1)

            elif cmd == "dashboard":
                try:
                    from cli_core.menu import InteractiveMenu
                    menu = InteractiveMenu()
                    menu.run()
                except Exception as ex:
                    print(f"[error] Could not launch dashboard: {ex}")
                    print("Try running: python manage.py setup")
                    sys.exit(1)

            elif cmd == "deploy":
                # Check if user specifically requested NATIVE mode in .env
                deployment_mode = "docker" # default
                if os.path.exists(".env"):
                    with open(".env", "r") as f:
                        for line in f:
                            if line.startswith("DEPLOYMENT_MODE="):
                                deployment_mode = line.split("=")[1].strip().lower()
                
                if deployment_mode == "native":
                    print("\n" + "!"*60)
                    print(" ERROR: NATIVE DEPLOYMENT NOT POSSIBLE IN MINIMAL MODE")
                    print("!"*60)
                    print(" You have selected 'native' deployment in your .env file.")
                    print(" This requires the full Python environment and dependencies.")
                    print(" Please run 'python manage.py' and select 'Yes' to auto-install dependencies.")
                    print("!"*60 + "\n")
                    sys.exit(1)

                print("Building and Starting Docker Containers...")
                # Basic environment setup
                env = os.environ.copy()
                try:
                    subprocess.run(f"docker compose -f {compose_file} build", shell=True, check=True, env=env)
                    subprocess.run(f"docker compose -f {compose_file} up -d", shell=True, check=True, env=env)
                    print("\n[SUCCESS] Application deployed via Docker.")
                except subprocess.CalledProcessError:
                    print("\n[ERROR] Docker deployment failed. Ensure Docker is running.")
                    sys.exit(1)
            
            elif cmd == "logs":
                print("Streaming logs (Ctrl+C to stop)...")
                try:
                    subprocess.run(f"docker compose -f {compose_file} logs -f --tail=100", shell=True)
                except KeyboardInterrupt:
                    print("\nStopped.")
            
            else:
                 print(f"Command '{cmd}' not supported in Minimal Mode. Please install dependencies.")
                 sys.exit(1)
        else:
            # Re-raise other errors
            raise e

if __name__ == "__main__":
    main()
