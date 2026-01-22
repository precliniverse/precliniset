import os
import sys
import platform
import time
try:
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.table import Table
    from rich.live import Live
    from rich.prompt import Prompt, Confirm
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .utils import console, get_architecture, IS_WINDOWS, run_command, confirm_action
from .config import ConfigManager, ENV_FILE
from .diagnostics import check_health, PortManager
from .wizard import ConfigWizard
from .deploy import DockerDeployer, NativeDeployer
from .ecosystem import test_ecosystem_link

class InteractiveMenu:
    def __init__(self):
        self.config = ConfigManager.load_env()
        self.mode = self.config.get('DEPLOYMENT_MODE', 'docker')
        self.app_port = self.config.get('APP_PORT', '8000')
        self.system = platform.system()
    
    def _refresh_config(self):
        self.config = ConfigManager.load_env()
        self.mode = self.config.get('DEPLOYMENT_MODE', 'docker')
        self.app_port = self.config.get('APP_PORT', '8000')

    def _get_service_status(self):
        """Quick check if service appears running."""
        running = PortManager.check_port_available(self.app_port, host='localhost') == False
        # Invert logic: check_port_available returns True if free. So False means In Use (Running).
        return "Running" if running else "Stopped"

    def _get_db_status(self):
        """Check DB status based on mode."""
        # This is a bit expensive for a dashboard, maybe just show configuration type?
        return self.config.get('DB_TYPE', 'Unknown').capitalize()

    def _draw_dashboard(self):
        """Create the dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Header
        title = "[bold magenta]🐳 Precliniverse CLI Manager[/bold magenta]"
        subtitle = f"v1.0 | Mode: [bold cyan]{self.mode.upper()}[/bold cyan] | OS: {self.system}"
        layout["header"].update(Panel(subtitle, title=title, border_style="magenta"))
        
        # Body - Split into Status and Menu
        layout["body"].split_row(
            Layout(name="status", ratio=1),
            Layout(name="menu", ratio=2)
        )
        
        # Status Panel
        self._refresh_config()
        status_table = Table(box=None, expand=True)
        status_table.add_column("Metric", style="cyan")
        status_table.add_column("Value", style="green")
        
        status = self._get_service_status()
        status_color = "green" if status == "Running" else "red"
        
        status_table.add_row("App Status", f"[{status_color}]{status}[/{status_color}]")
        status_table.add_row("Port", self.app_port)
        status_table.add_row("Database", self._get_db_status())
        status_table.add_row("Debug Mode", "On" if self.config.get('FLASK_DEBUG') == '1' else "Off")
        
        if not os.path.exists(ENV_FILE):
             layout["status"].update(Panel("[bold red]⚠ No Configuration Found[/bold red]\nRun Setup First!", title="System Status", border_style="red"))
        else:
             layout["status"].update(Panel(status_table, title="System Status", border_style="blue"))
        
        # Menu Panel
        menu_table = Table(box=None, expand=True, show_header=True)
        menu_table.add_column("No.", style="bold cyan", width=4)
        menu_table.add_column("Action")
        menu_table.add_column("Description", style="dim")
        
        menu_table.add_row("1", "Setup / Configure", "Create or edit .env configuration")
        menu_table.add_row("2", "Deploy / Rebuild", "Build images, install dependencies, init DB")
        menu_table.add_row("3", "Start Application", "Start web server, database, worker")
        menu_table.add_row("4", "Stop Application", "Stop all running services")
        menu_table.add_row("5", "View Logs", "Stream live logs (Ctrl+C to exit)")
        menu_table.add_row("6", "System Health", "Run comprehensive diagnostics")
        menu_table.add_row("7", "Ecosystem Link", "Manage Training Manager Integration")
        menu_table.add_row("8", "Update Code", "Git pull and redeploy")
        menu_table.add_row("9", "Demo Data", "Populate simulation data (Dangerous)")
        menu_table.add_row("R", "Build Release", "Create publishable Docker package")
        menu_table.add_row("0", "Exit", "Exit CLI")
        
        layout["menu"].update(Panel(menu_table, title="Actions", border_style="white"))
        
        # Footer
        layout["footer"].update(Panel("[dim]Select an option by entering the number.[/dim]", border_style="none"))
        
        return layout

    def run(self):
        # Clear screen command based on OS
        os.system('cls' if os.name == 'nt' else 'clear')  # nosec B605
        
        if HAS_RICH and hasattr(console, 'print') and not isinstance(console, object) and 'SimpleConsole' not in str(type(console)):
             # Extra check because utils might give us a SimpleConsole even if rich is installed if import failed there?
             # Actually relies on local import success
             self._run_rich()
        else:
            self._run_simple()

    def _run_simple(self):
        """Text-based fallback menu."""
        while True:
            print("\nPrecliniverse CLI Manager")
            print(f"Mode: {self.mode.upper()}")
            print("-" * 30)
            print("1. Setup / Configure")
            print("2. Deploy / Rebuild")
            print("3. Start/Restart Application")
            print("4. Stop Application")
            print("5. View Logs")
            print("6. System Health")
            print("7. Ecosystem Link")
            print("8. Update Code")
            print("9. Demo Data")
            print("R. Build Release")
            print("0. Exit")
            print("-" * 30)
            
            choice = input("Select Option (0-9): ").strip()
            
            if choice == "0":
                print("Goodbye!")
                sys.exit(0)
            
            if choice.upper() not in [str(i) for i in range(10)] + ['R']:
                print("Invalid choice.")
                continue
                
            self.execute_command(choice)
            input("\nPress Enter to return to menu...")
            os.system('cls' if os.name == 'nt' else 'clear')  # nosec B605

    def _run_rich(self):
        # console.clear() # utils console might not have clear if simple? 
        # But we are in _run_rich so we assume real console?
        # utils.console is the one we use.
        os.system('cls' if os.name == 'nt' else 'clear')  # nosec B605
        while True:
            console.print(self._draw_dashboard())
            
            choice = Prompt.ask("Select Option", choices=[str(i) for i in range(10)] + ['r', 'R']).upper()
            console.print() # spacer
            
            if choice == "0":
                console.print("[green]Goodbye![/green]")
                sys.exit(0)
            
            self.execute_command(choice)
            
            if choice != "5": # Don't pause after logs
                Prompt.ask("\n[dim]Press Enter to return to menu...[/dim]")
                os.system('cls' if os.name == 'nt' else 'clear')  # nosec B605

    def execute_command(self, choice):
        if choice == "1":
            wizard = ConfigWizard()
            wizard.run()
        elif choice == "2":
            if confirm_action("This will rebuild containers/virtualenv. Continue?"):
                deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
                deployer.deploy(debug=self.config.get('FLASK_DEBUG') == '1')
        elif choice == "3":
            deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
            deployer.start()
        elif choice == "4":
            deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
            deployer.stop()
        elif choice == "5":
            try:
                deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
                deployer.logs()
            except KeyboardInterrupt:
                pass
        elif choice == "6":
            check_health()
        elif choice == "7":
            # Submenu for ecosystem
            console.print("\n[cyan]Ecosystem Integration[/cyan]")
            console.print("1. Test Connection")
            console.print("2. Re-configure Link")
            
            if HAS_RICH:
                sub = Prompt.ask("Choice", choices=["1", "2"], default="1")
            else:
                 sub = input("Choice [1]: ").strip() or "1"
                 
            if sub == "1":
                test_ecosystem_link()
            else:
                wizard = ConfigWizard()
                wizard._ask_security() # Just re-run the security/link part? Ideally refactor Wizard to allow partial.
                # For now, wizard is monolithic. Let's just do full setup or implement a targeted setup.
                # Actually, running full wizard is safer to ensure consistency.
                console.print("[yellow]Re-running configuration wizard...[/yellow]")
                wizard.run()
                
        elif choice == "8":
            console.print("[info]Pulling latest changes...[/info]")
            run_command("git pull", check=False)
            if confirm_action("Redeploy now?"):
                deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
                deployer.deploy()
        elif choice == "9":
            console.print("[bold red]WARNING: This generates extensive simulation data.[/bold red]")
            if confirm_action("Proceed?"):
                deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
                # Populate demo isn't strictly in deployer, but we can access it via Flask CLI
                # Or invoke utility directly. 
                # Let's use the CLI command we standardized.
                deployer = DockerDeployer() if self.mode == 'docker' else NativeDeployer()
                deployer.run_flask("setup populate-simulation")
        elif choice == "R":
            if HAS_RICH:
                tag = Prompt.ask("Enter release tag (e.g. v1.0.0)", default=f"v{time.strftime('%Y.%m.%d')}")
            else:
                tag = input(f"Enter release tag [v{time.strftime('%Y.%m.%d')}]: ").strip() or f"v{time.strftime('%Y.%m.%d')}"
            deployer = DockerDeployer()
            deployer.build_release(tag=tag)

