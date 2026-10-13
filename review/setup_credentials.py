"""Create local-only reviewer credentials, stored outside Git."""
import argparse
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]


def create(path=None):
    location = Path(path) if path else ROOT / "data" / "review_credentials.env"
    if location.exists():
        raise FileExistsError("Credentials already exist; refusing overwrite")
    location.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(22)
    secret = secrets.token_urlsafe(48)
    location.write_text(
        "REVIEW_PASSWORD_HASH=" + generate_password_hash(password) +
        "\nREVIEW_SESSION_SECRET=" + secret + "\n",
        encoding="utf-8",
    )
    location.chmod(0o600)
    return location, password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path)
    args = parser.parse_args()
    path, password = create(args.path)
    print("Private credentials file:", path)
    print("ONE-TIME LOCAL REVIEW PASSWORD:", password)
    print("Keep this password private. The credentials file is ignored by Git.")


if __name__ == "__main__":
    main()
