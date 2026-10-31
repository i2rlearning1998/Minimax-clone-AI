from dataclasses import dataclass, field
from pathlib import Path
import json
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent


@dataclass
class Settings:
    provider: str = 'mock'
    output_dir: Path = ROOT / 'outputs'
    db_path: Path = ROOT / 'outputs' / 'history.sqlite3'
    routing_path: Path = ROOT / 'config' / 'routing.json'
    voices_path: Path = ROOT / 'voices.json'
    timeout: float = 60.0
    retry_delay: float = 0.5
    cors_origins: tuple = ('http://localhost:3000', 'http://localhost:5173')
    keys: dict = field(default_factory=dict, repr=False)
    model_overrides: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls):
        # Secrets intentionally come only from this ignored file, never JSON/code.
        dotenv = dotenv_values(ROOT / '.env')
        def value(name, default):
            return os.environ.get(name, dotenv.get(name) or default)
        output = Path(value('OUTPUT_DIR', str(ROOT / 'outputs')))
        timeout = float(value('PROVIDER_TIMEOUT_SEC', '60'))
        if timeout <= 0:
            raise ValueError('PROVIDER_TIMEOUT_SEC must be positive')
        return cls(
            provider=value('TTS_PROVIDER', 'mock'), output_dir=output,
            db_path=Path(value('DATABASE_PATH', str(output / 'history.sqlite3'))),
            routing_path=Path(value('ROUTING_PATH', str(ROOT / 'config/routing.json'))),
            timeout=timeout,
            cors_origins=tuple(x.strip() for x in value('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173').split(',') if x.strip()),
            keys={'replicate': dotenv.get('REPLICATE_API_TOKEN') or '', 'fal': dotenv.get('FAL_KEY') or ''},
            model_overrides={p: value(p.upper() + '_MODEL', '') for p in ('replicate', 'fal')},
        )

    def route(self, language):
        data = json.loads(self.routing_path.read_text(encoding='utf-8'))
        language_config = data[language]
        provider = language_config.get('provider') or self.provider
        route = dict(language_config[provider])
        route['model'] = self.model_overrides.get(provider) or route.get('model', '')
        return provider, route
