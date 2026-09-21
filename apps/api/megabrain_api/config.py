import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql+psycopg://megabrain:megabrain@localhost:5432/megabrain"
        )
    )
    token: str = field(default_factory=lambda: os.getenv("APP_ACCESS_TOKEN", ""))
    test_login_enabled: bool = field(
        default_factory=lambda: os.getenv("APP_TEST_LOGIN_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"}
    )
    test_username: str = field(default_factory=lambda: os.getenv("APP_TEST_USERNAME", "admin"))
    test_password: str = field(default_factory=lambda: os.getenv("APP_TEST_PASSWORD", "admin"))
    origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv(
                "APP_ORIGINS",
                "http://localhost:3000,http://localhost:8080,https://localhost,capacitor://localhost",
            ).split(",")
        )
    )
    data: Path = field(
        default_factory=lambda: Path(os.getenv("APP_DATA_DIR", str(ROOT / ".data/app"))).resolve()
    )
    workspace: Path = field(
        default_factory=lambda: Path(
            os.getenv("APP_WORKSPACE", str(ROOT / ".data/app/workspace"))
        ).resolve()
    )
    max_upload: int = 20 * 1024 * 1024
    max_text: int = 2_000_000
    job_timeout: int = 600

    def prepare(self):
        if len(self.token) < 32:
            raise ValueError("APP_ACCESS_TOKEN must have at least 32 characters")
        if not self.database_url.startswith("postgresql") and os.getenv("APP_TESTING") != "1":
            raise ValueError("PostgreSQL is required outside tests")
        self.data.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.data / "uploads").mkdir(exist_ok=True)
