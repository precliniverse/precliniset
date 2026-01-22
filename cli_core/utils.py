import os
import sys
import subprocess
import platform
try:
    from rich.console import Console
    from rich.theme import Theme
    
    # Define custom theme matching original colors but better
    custom_theme = Theme({
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "green",
        "header": "bold magenta"
    })
    console = Console(theme=custom_theme)
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class SimpleConsole:
        def print(self, text, *args, **kwargs):
            # Strip simple tags if possible or just print
            # Minimal tag stripping
            clean_text = text.replace("[bold]", "").replace("[/bold]", "")\
                             .replace("[red]", "").replace("[/red]", "")\
                             .replace("[green]", "").replace("[/green]", "")\
                             .replace("[cyan]", "").replace("[/cyan]", "")\
                             .replace("[yellow]", "").replace("[/yellow]", "")\
                             .replace("[magenta]", "").replace("[/magenta]", "")\
                             .replace("[dim]", "").replace("[/dim]", "")\
                             .replace("[header]", "").replace("[/header]", "")\
                             .replace("[info]", "").replace("[/info]", "")\
                             .replace("[warning]", "").replace("[/warning]", "")\
                             .replace("[error]", "").replace("[/error]", "")\
                             .replace("[success]", "").replace("[/success]", "")
            print(clean_text)
        
        def input(self, prompt):
            clean_prompt = prompt.replace("[warning]", "").replace("[/warning]", "")
            return input(clean_prompt)
            
        def rule(self, title=""):
            print("-" * 60)
            if title:
                # simple tag strip
                clean = title.split("]")[1].split("[")[0] if "]" in title else title
                print(clean.center(60))
                print("-" * 60)
                
    console = SimpleConsole()

IS_WINDOWS = os.name == 'nt'

def get_architecture() -> str:
    """Get system architecture normalized."""
    arch = platform.machine().lower()
    if arch in ['armv7l', 'armv6l']:
        return 'armv7l'
    elif arch in ['aarch64', 'arm64']:
        return 'aarch64'
    return 'x86_64'

def run_command(command: str, shell: bool = True, check: bool = True, cwd: str = None, capture_output: bool = False, env: dict = None) -> str:
    """Run a shell command with error handling."""
    try:
        if capture_output:
            result = subprocess.run(command, shell=shell, check=check, cwd=cwd, capture_output=True, text=True, env=env)
            return result.stdout.strip()
        else:
            subprocess.run(command, shell=shell, check=check, cwd=cwd, env=env)
            return ""
    except subprocess.CalledProcessError as e:
        console.print(f"[error]Command failed: {command}[/error]")
        if capture_output and e.stdout:
            console.print(f"[dim]{e.stdout}[/dim]")
        if capture_output and e.stderr:
            console.print(f"[error]{e.stderr}[/error]")
        
        if check:
            sys.exit(e.returncode)
        return ""

def print_banner(text: str):
    """Print a styled banner."""
    console.print(f"[header]{'='*60}[/header]")
    console.print(f"[header]{text.center(60)}[/header]")
    console.print(f"[header]{'='*60}[/header]")

def confirm_action(message: str, default: bool = False) -> bool:
    """Ask for user confirmation."""
    suffix = "[Y/n]" if default else "[y/N]"
    response = console.input(f"[warning]{message} {suffix}: [/warning]").strip().lower()
    
    if not response:
        return default
    return response in ['y', 'yes']
