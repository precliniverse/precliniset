import os
import shutil
import secrets
import string
from datetime import datetime
from pathlib import Path
from .utils import console, confirm_action, print_banner

ENV_FILE = ".env"

class ConfigManager:
    """Manage .env configuration file."""
    
    @staticmethod
    def load_env() -> dict:
        """Load .env file into dictionary."""
        config = {}
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        return config
    
    @staticmethod
    def save_env(config: dict, backup: bool = True):
        """Save configuration to .env file."""
        if backup and os.path.exists(ENV_FILE):
            backup_name = f"{ENV_FILE}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(ENV_FILE, backup_name)
            console.print(f"[info]Backup created: {backup_name}[/info]")
        
        with open(ENV_FILE, 'w') as f:
            for key, value in config.items():
                f.write(f"{key}={value}\n")
    
    @staticmethod
    def get_value(key: str) -> str:
        """Get single value from .env."""
        config = ConfigManager.load_env()
        return config.get(key)
    
    @staticmethod
    def set_value(key: str, value: str, backup: bool = True) -> str:
        """Set single value in .env."""
        config = ConfigManager.load_env()
        old_value = config.get(key)
        config[key] = value
        ConfigManager.save_env(config, backup=backup)
        return old_value

def generate_secret(length: int = 32) -> str:
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
