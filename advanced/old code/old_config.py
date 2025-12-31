import json
import os
import threading

class ConfigManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = {}
        self.lock = threading.Lock()
        self.load_config()
    def load_config(self):
        with self.lock:
            try:
                if os.path.exists(self.config_path):
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        self.config = json.load(f)
            except (IOError, json.JSONDecodeError):
                self.config = {}
    def save_config(self, config_data=None):
        with self.lock:
            try:
                if config_data is not None:
                    self.config = config_data
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=4)
            except IOError:
                pass
    def get(self, key, default=None):
        return self.config.get(key, default)
    def set(self, key, value):
        self.config[key] = value