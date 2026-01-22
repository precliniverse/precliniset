import os
import sys
from .utils import console, print_banner
from .config import ConfigManager, ENV_FILE

def test_ecosystem_link():
    """Test ecosystem integration with Training Manager."""
    print_banner("Ecosystem Link Test")

    if not os.path.exists(ENV_FILE):
        console.print(f"[error]{ENV_FILE} not found. Run 'setup' first.[/error]")
        sys.exit(1)

    config = ConfigManager.load_env()

    # Rich Table
    try:
        from rich.table import Table
        table = Table(title="Ecosystem Integration Test Results")
    except ImportError:
        console.print("[warning]Rich not installed. Skipping formatted table.[/warning]")
        return

    table.add_column("Component", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details")

    # Check configuration
    tm_enabled = config.get('TM_ENABLED', 'False').lower() == 'true'
    tm_url = config.get('TM_API_URL')
    tm_key = config.get('TM_API_KEY')
    service_key = config.get('SERVICE_API_KEY')
    sso_key = config.get('SSO_SECRET_KEY')

    table.add_row("TM Integration Enabled", "Yes" if tm_enabled else "No", "")
    if not tm_enabled:
        table.add_row("Configuration Status", "[yellow]Warning[/yellow]", "Run 'link-ecosystem' to enable")
        console.print(table)
        return

    table.add_row("TM API URL", "[green]Configured[/green]" if tm_url else "[red]Missing[/red]", tm_url or "")
    table.add_row("TM API Key", "[green]Configured[/green]" if tm_key else "[red]Missing[/red]", "")
    table.add_row("Service API Key", "[green]Configured[/green]" if service_key else "[red]Missing[/red]", "")
    table.add_row("SSO Secret Key", "[green]Configured[/green]" if sso_key else "[red]Missing[/red]", "")

    success_count = 0
    total_tests = 0

    # Test connectivity
    if tm_url and tm_key:
        console.print("[info]Testing Training Manager API connectivity...[/info]")
        
        # We assume we are in the project root so we can import 'app'
        try:
            from app import create_app
            from app.services.tm_connector import TrainingManagerConnector

            app = create_app()
            with app.app_context():
                connector = TrainingManagerConnector()

                # Test 1: Skills endpoint
                total_tests += 1
                try:
                    skills = connector.get_skills()
                    if skills and isinstance(skills, list):
                        table.add_row("Skills API", "[green]Success[/green]", f"Retrieved {len(skills)} skills")
                        success_count += 1
                    else:
                        table.add_row("Skills API", "[red]Failed[/red]", "No skills returned or invalid response")
                except Exception as e:
                    table.add_row("Skills API", "[red]Error[/red]", str(e)[:47])


                # Test 2: Competency check 
                total_tests += 1
                try:
                    result = connector.check_competency(['test@example.com'], [1])
                    if result and isinstance(result, dict):
                        table.add_row("Competency API", "[green]Success[/green]", "API responded correctly")
                        success_count += 1
                    else:
                        table.add_row("Competency API", "[red]Failed[/red]", "Invalid response")
                except Exception as e:
                    table.add_row("Competency API", "[red]Error[/red]", str(e)[:47])

                # Test 3: Calendar API
                total_tests += 1
                try:
                    result = connector.get_user_calendar('test@example.com')
                    if result is not None:
                        table.add_row("Calendar API", "[green]Success[/green]", f"Retrieved events")
                        success_count += 1
                    else:
                        table.add_row("Calendar API", "[red]Failed[/red]", "Invalid response")
                except Exception as e:
                    table.add_row("Calendar API", "[red]Error[/red]", str(e)[:47])

        except ImportError as e:
            table.add_row("Connector Import", "[red]Failed[/red]", f"Cannot import TrainingManagerConnector: {e}")
            # Consider this a failure for all API tests
            total_tests += 3 
        except Exception as e:
            table.add_row("General API Test", "[red]Error[/red]", str(e)[:47])
             # Consider this a failure for all API tests
            total_tests += 3
    else:
        table.add_row("API Tests", "[yellow]Skipped[/yellow]", "Missing configuration")

    # Test SSO token generation
    total_tests += 1
    if sso_key:
        try:
            from itsdangerous import URLSafeTimedSerializer
            serializer = URLSafeTimedSerializer(sso_key)
            test_token = serializer.dumps({'email': 'test@example.com'}, salt='sso-salt')
            decoded = serializer.loads(test_token, max_age=30, salt='sso-salt')
            if decoded.get('email') == 'test@example.com':
                table.add_row("SSO Token Generation", "[green]Success[/green]", "Token validation works")
                success_count += 1
            else:
                table.add_row("SSO Token Generation", "[red]Failed[/red]", "Token decode mismatch")
        except Exception as e:
            table.add_row("SSO Token Generation", "[red]Error[/red]", str(e)[:47])
    else:
        table.add_row("SSO Token Generation", "[yellow]Skipped[/yellow]", "Missing SSO_SECRET_KEY")

    console.print(table)
    
    # Summary
    print("\n")
    console.rule("[bold magenta]Test Summary[/bold magenta]")
    
    if success_count == total_tests and total_tests > 0:
        console.print("[bold green]All ecosystem tests passed! Integration is working correctly.[/bold green]")
    elif success_count > 0:
        console.print(f"[bold yellow]Partial success: {success_count}/{total_tests} tests passed.[/bold yellow]")
    else:
        console.print("[bold red]All tests failed. Integration is not working.[/bold red]")
