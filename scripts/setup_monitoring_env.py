"""Generate local credentials; never commit them."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = root / ".env"
token_file = root / "monitoring" / "secrets" / "metrics_token"
if env.exists() or token_file.exists():
    raise SystemExit("Credentials already exist; refusing to overwrite.")
token_file.parent.mkdir(parents=True, exist_ok=True)
token = secrets.token_urlsafe(32)
password = secrets.token_urlsafe(24)
token_file.write_text(token + "\n", encoding="utf-8")
env.write_text(
    "MONITORING_METRICS_TOKEN=" + token +
    "\nGRAFANA_ADMIN_USER=admin\nGRAFANA_ADMIN_PASSWORD=" + password + "\n",
    encoding="utf-8",
)
print("Created local .env and monitoring/secrets/metrics_token.")
