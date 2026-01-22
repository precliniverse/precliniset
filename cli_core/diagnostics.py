import os
import subprocess
from .utils import console, IS_WINDOWS, run_command
from .config import ConfigManager

class PortManager:
    """Advanced port management with availability checking and conflict resolution."""
    
    @staticmethod
    def check_port_available(port: str, host: str = 'localhost') -> bool:
        """Check if a port is available."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex((host, int(port)))
                return result != 0
        except Exception as e:
            console.print(f"[warning]Error checking port {port}: {e}[/warning]")
            return False
    
    @staticmethod
    def suggest_alternative_ports(port: str, count: int = 3) -> list:
        """Suggest alternative ports near the requested one."""
        suggestions = []
        for offset in [10, 100, 1000]:
            candidate = int(port) + offset
            if PortManager.check_port_available(str(candidate)) and candidate < 65535:
                suggestions.append(candidate)
                if len(suggestions) >= count:
                    break
        return suggestions
    
    @staticmethod
    def get_port_info(port: str) -> str:
        """Get information about what's using a port (Linux/Mac only)."""
        if IS_WINDOWS:
            try:
                cmd = f'netstat -ano | findstr :{port}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return result.stdout.strip() if result.stdout else "Port in use (details unavailable)"
            except:
                return "Unable to determine"
        else:
            try:
                cmd = f"lsof -i :{port} -sTCP:LISTEN || ss -ltnp | grep :{port}"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return result.stdout.strip() if result.stdout else "Port in use (details unavailable)"
            except:
                return "Unable to determine"

class DatabaseManager:
    """Database connectivity testing."""
    
    @staticmethod
    def test_connection(db_config: dict) -> tuple:
        """Test database connection. Returns (success, message)."""
        db_type = db_config.get('DB_TYPE', 'sqlite')
        
        if db_type == 'sqlite':
            db_path = db_config.get('DATABASE_URL', 'instance/experiment_app.db')
            if db_path.startswith('sqlite:///'):
                db_path = db_path.replace('sqlite:///', '')
            
            db_dir = os.path.dirname(db_path) if '/' in db_path else 'instance'
            if not os.path.exists(db_dir):
                return False, f"Directory '{db_dir}' does not exist"
            return True, f"SQLite database path: {db_path}"
        
        elif db_type == 'mysql':
            try:
                import pymysql
                conn = pymysql.connect(
                    host=db_config.get('DB_HOST', 'localhost'),
                    port=int(db_config.get('DB_PORT', 3306)),
                    user=db_config.get('DB_USER'),
                    password=db_config.get('DB_PASSWORD'),
                    database=db_config.get('DB_NAME'),
                    connect_timeout=5
                )
                conn.close()
                return True, f"Successfully connected to {db_config.get('DB_HOST')}:{db_config.get('DB_PORT')}"
            except ImportError:
                return False, "pymysql not installed"
            except Exception as e:
                return False, f"Connection failed: {str(e)}"
        
        return False, f"Unknown database type: {db_type}"


class RedisManager:
    """Redis connectivity testing."""
    
    @staticmethod
    def test_connection(redis_url: str) -> tuple:
        """Test Redis connection. Returns (success, message)."""
        try:
            import redis
            r = redis.from_url(redis_url, socket_connect_timeout=2)
            r.ping()
            return True, "Successfully connected to Redis"
        except ImportError:
            # Fallback for Minimal Mode: Use raw sockets to PING
            import socket
            from urllib.parse import urlparse
            
            try:
                url = urlparse(redis_url)
                host = url.hostname or 'localhost'
                port = url.port or 6379
                
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((host, port))
                    # Send basic RESP PING
                    s.sendall(b"*1\r\n$4\r\nPING\r\n")
                    response = s.recv(1024)
                    if b"PONG" in response:
                        return True, "Successfully connected to Redis (via Raw Socket)"
                    return False, f"Unexpected Redis response: {response.decode().strip()}"
            except Exception as e:
                return False, f"Redis socket connection failed: {str(e)}"
        except Exception as e:
            return False, f"Redis connection failed: {str(e)}"

class DockerManager:
    """Docker environment checks and recommendations."""

    @staticmethod
    def check_docker() -> tuple:
        """Check if Docker is available and running. Returns (status_code, message, details)."""
        import shutil
        
        # 1. Check binary
        docker_path = shutil.which("docker")
        if not docker_path:
            return False, "Docker is not installed.", "Binary 'docker' not found in PATH."
            
        # 2. Check info (daemon running)
        try:
            subprocess.run("docker info", shell=True, check=True, capture_output=True, timeout=5)
            
            # 3. Check compose
            try:
                res = subprocess.run("docker compose version", shell=True, capture_output=True, text=True)
                return True, "Docker is running", f"Compose: {res.stdout.strip()}"
            except subprocess.CalledProcessError:
                return True, "Docker running (No Compose)", "Plugin 'docker-compose' missing."
                
        except subprocess.CalledProcessError:
            return False, "Docker is installed but not running.", "Daemon not responding."
        except subprocess.TimeoutExpired:
            return False, "Docker check timed out.", "Daemon might be hung."

    @staticmethod
    def get_install_instructions() -> str:
        """Return OS-specific installation advice."""
        import platform
        system = platform.system().lower()
        
        if system == "windows":
            return ("1. Download Docker Desktop from [link=https://www.docker.com/products/docker-desktop]https://www.docker.com[/link]\n"
                    "2. Install and ensure WSL 2 backend is selected.\n"
                    "3. Start Docker Desktop application.")
        elif system == "linux":
            return ("Ubuntu/Debian:\n"
                    "  [bold]sudo apt-get update[/bold]\n"
                    "  [bold]sudo apt-get install docker.io docker-compose-plugin[/bold]\n"
                    "  [bold]sudo systemctl start docker[/bold]\n"
                    "  [bold]sudo usermod -aG docker $USER[/bold]")
        elif system == "darwin": # Mac
             return ("1. Download Docker Desktop for Mac.\n"
                     "2. drag to Applications folder.\n"
                     "3. Open Docker.app to start engine.")
        return "Refer to official documentation: https://docs.docker.com/get-docker/"

def check_health():
    """Run system health check."""
    try:
        from rich.table import Table
    except ImportError:
        console.print("[warning]Rich not installed. Skipping formatted table.[/warning]")
        return

    table = Table(title="System Health Check")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details")
    
    config = ConfigManager.load_env()
    
    # 1. Config
    if os.path.exists(".env"):
        table.add_row("Configuration", "[green]OK[/green]", f"{len(config)} parameters")
    else:
        table.add_row("Configuration", "[red]Missing[/red]", "Run setup")
        
    # 2. Database
    success, msg = DatabaseManager.test_connection(config)
    status = "[green]Connected[/green]" if success else "[red]Failed[/red]"
    table.add_row("Database", status, msg)
    
    
    # 3. Docker (if applicable)
    is_docker_mode = config.get('DEPLOYMENT_MODE') == 'docker'
    docker_ok, docker_msg, docker_details = DockerManager.check_docker()
    
    if is_docker_mode:
        style = "[green]Ready[/green]" if docker_ok else "[red]Critical[/red]"
        table.add_row("Docker Engine", style, f"{docker_msg} | {docker_details}")
        if not docker_ok:
            console.print("\n[bold yellow]⚠ Docker Requirement Missing[/bold yellow]")
            console.print(DockerManager.get_install_instructions())
            console.print("")
    else:
        # Just info for native mode
        style = "[green]Available[/green]" if docker_ok else "[dim]Not Found[/dim]"
        table.add_row("Docker Engine", style, f"(Optional) {docker_msg}")

    # 4. Redis (Precliniverse specific)
    redis_url = config.get('CELERY_BROKER_URL')
    if redis_url:
        # Additional check for Linux Redis service
        if not IS_WINDOWS and not is_docker_mode:
            try:
                import subprocess
                result = subprocess.run("systemctl is-active redis-server", shell=True, capture_output=True, text=True)
                if result.returncode == 0 and "active" in result.stdout:
                    redis_service = "[green]Running[/green]"
                else:
                    redis_service = "[yellow]Service not active[/yellow]"
            except:
                redis_service = "[dim]Unable to check service[/dim]"
        else:
             redis_service = ""
        
        success, msg = RedisManager.test_connection(redis_url)
        status = "[green]Connected[/green]" if success else "[red]Failed[/red]"
        details = f"{msg}"
        if redis_service: details += f" | Service: {redis_service}"
        
        table.add_row("Redis", status, details)
        
    console.print(table)
