from dataclasses import dataclass, field
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

def load_env(path=ROOT / '.env'):
    """Small environment loader; existing process environment takes priority."""
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()

@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'sqlite:///' + (ROOT / 'data/impact.db').as_posix()))
    api_key: str = field(default_factory=lambda: os.getenv('NVIDIA_API_KEY', ''), repr=False)
    model: str = field(default_factory=lambda: os.getenv('NVIDIA_MODEL', 'nvidia/nemotron-3-super-120b-a12b'))
    api_token: str = field(default_factory=lambda: os.getenv('IMPACT_API_TOKEN', ''), repr=False)
    rpm: int = field(default_factory=lambda: int(os.getenv('NVIDIA_RPM', '6')))
    tpm: int = field(default_factory=lambda: int(os.getenv('NVIDIA_TPM', '24000')))
    daily_calls: int = field(default_factory=lambda: int(os.getenv('NVIDIA_DAILY_CALLS', '100')))
    max_output: int = field(default_factory=lambda: int(os.getenv('NVIDIA_MAX_OUTPUT_TOKENS', '2500')))
    max_input_chars: int = field(default_factory=lambda: int(os.getenv('NVIDIA_MAX_INPUT_CHARS', '24000')))
    roots: tuple = field(default_factory=lambda: tuple(Path(p).resolve() for p in os.getenv('REPOSITORY_ROOTS', '').split(';') if p) or (ROOT / 'examples',))
    lease_seconds: int = 240
    def __post_init__(self):
        if min(self.rpm, self.tpm, self.daily_calls, self.max_output, self.max_input_chars) <= 0:
            raise ValueError('Provider budgets must be positive')
        if self.max_output > 8000 or self.max_input_chars > 60000:
            raise ValueError('Configured context exceeds this application budget')

settings = Settings()
