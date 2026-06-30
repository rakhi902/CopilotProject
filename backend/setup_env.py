"""Make sure backend/.env exists so you can store your secrets.

Run by the one-click launchers. It copies .env.example to .env on the first run
and fills in a generated JWT secret if it's still the placeholder.

It does NOT set DATABASE_URL: local development uses the SQLite fallback built
into app/core/config.py, and production sets DATABASE_URL in the environment.
Anything already in the file (a real JWT secret, your GROQ_API_KEY, every other
line) is left exactly as it is.
"""

import pathlib
import secrets

HERE = pathlib.Path(__file__).resolve().parent
ENV = HERE / ".env"
EXAMPLE = HERE / ".env.example"

_JWT_PLACEHOLDER = "your_secure_jwt_secret_here"


def main() -> int:
    if not ENV.exists():
        if not EXAMPLE.exists():
            print("backend/.env.example is missing; can't create .env.")
            return 1
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created backend/.env from .env.example.")

    lines = ENV.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("JWT_SECRET_KEY="):
            value = stripped.split("=", 1)[1].strip()
            if not value or value == _JWT_PLACEHOLDER:
                line = "JWT_SECRET_KEY=" + secrets.token_urlsafe(64)
                print("Generated a JWT secret.")
        out.append(line)
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
