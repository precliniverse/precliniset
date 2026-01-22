import argparse
import sys
from .utils import console, print_banner
from .config import ConfigManager
from .diagnostics import check_health
from .deploy import DockerDeployer, NativeDeployer
from .wizard import ConfigWizard
from .ecosystem import test_ecosystem_link

def main():
    parser = argparse.ArgumentParser(
        description="Precliniverse CLI",
        epilog="💡 TIP: Run 'python manage.py --interactive' for an interactive dashboard with visual menus."
    )
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    subparsers = parser.add_subparsers(dest="command")
    
    # Core Commands
    subparsers.add_parser("setup", help="Run Configuration Wizard")
    subparsers.add_parser("deploy", help="Full Install/Deploy")
    subparsers.add_parser("update", help="Update Code & Dependencies")
    subparsers.add_parser("start", help="Start Services")
    subparsers.add_parser("stop", help="Stop Services")
    subparsers.add_parser("logs", help="View Logs")
    subparsers.add_parser("link-ecosystem", help="Configure Training Manager integration")
    subparsers.add_parser("test-link", help="Test ecosystem integration")
    subparsers.add_parser("health", help="Run comprehensive health checks")
    
    bump_parser = subparsers.add_parser("bump", help="Increment version (SemVer)")
    bump_parser.add_argument("type", choices=["major", "minor", "patch", "rc"], help="Version segment to bump")

    release_parser = subparsers.add_parser("build-release", help="Create a publishable Docker package")
    release_parser.add_argument("--tag", type=str, help="Version tag (e.g. v1.0.0)")
    
    args = parser.parse_args()
    
    if args.command == "setup":
        wizard = ConfigWizard()
        wizard.run()

    elif args.command == "health":
        print_banner("System Health Check")
        check_health()
        
    elif args.command == "deploy":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.deploy(debug=args.debug)

    elif args.command == "update":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.update()
        
    elif args.command == "start":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.start()
        
    elif args.command == "stop":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.stop()

    elif args.command == "logs":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.logs()
        
    elif args.command == "test-link":
        test_ecosystem_link()

    elif args.command == "link-ecosystem":
        wizard = ConfigWizard()
        # We only want to run the security/ecosystem part
        print("Please use 'manage.py setup' to configure integrations in the wizard.")
        # Alternatively, we could expose a method in wizard, but setup is cleaner.
        
    elif args.command == "populate-demo":
        config = ConfigManager.load_env()
        mode = config.get('DEPLOYMENT_MODE', 'docker')
        deployer = DockerDeployer() if mode == 'docker' else NativeDeployer()
        deployer.run_flask("setup populate-simulation")

    elif args.command == "build-release":
        deployer = DockerDeployer()
        deployer.build_release(tag=args.tag)

    elif args.command == "bump":
        # Simple SemVer bumper logic
        import re
        import os
        
        version_file = "VERSION"
        if not os.path.exists(version_file):
            print(f"Error: {version_file} not found.")
            return

        with open(version_file, "r") as f:
            current = f.read().strip()
        
        # Regex to parse X.Y.Z-tag
        # Match: 1.2.3 or 1.2.3-rc1 or 1.2.3-beta
        match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", current)
        if not match:
            print(f"Error: Invalid version format '{current}' in {version_file}")
            return

        major, minor, patch, tag = int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)
        
        if args.type == "major":
            major += 1
            minor = 0
            patch = 0
            tag = None
        elif args.type == "minor":
            minor += 1
            patch = 0
            tag = None
        elif args.type == "patch":
            patch += 1
            tag = None
        elif args.type == "rc":
            if tag and tag.startswith("rc"):
                # Try to increment the number in rcX
                rc_match = re.search(r"rc(\d+)", tag)
                if rc_match:
                    rc_num = int(rc_match.group(1)) + 1
                    tag = f"rc{rc_num}"
                else:
                    tag = "rc2" # Fallback if tag was just 'rc'
            else:
                tag = "rc1"

        new_version = f"{major}.{minor}.{patch}"
        if tag:
            new_version += f"-{tag}"
            
        with open(version_file, "w") as f:
            f.write(new_version + "\n")
            
        print(f"✅ Version bumped: {current} -> [bold green]{new_version}[/bold green]")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
