"""Log in to Garmin Connect using cached tokens, falling back to .env credentials.

Run `python -m garmin_sync.auth` to test the login on its own.
"""

import os
import sys

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

import config


class LoginError(RuntimeError):
    pass


def _prompt_mfa() -> str:
    return input("Garmin sent you a verification code (MFA). Enter it here: ").strip()


def get_client() -> Garmin:
    """Return a logged-in Garmin client.

    Cached tokens in config.TOKEN_DIR are tried first; they refresh themselves.
    Only when they are missing or rejected are the .env credentials used
    (and MFA asked for, if your account has it enabled).
    """
    email = os.getenv("GARMIN_EMAIL") or None
    password = os.getenv("GARMIN_PASSWORD") or None
    if email == "you@example.com":
        email = password = None  # untouched .env.example values

    client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
    try:
        client.login(config.TOKEN_DIR)
    except GarminConnectAuthenticationError as e:
        if not email or not password:
            raise LoginError(
                "No valid cached login and no credentials found.\n"
                "Copy .env.example to .env and fill in GARMIN_EMAIL and GARMIN_PASSWORD."
            ) from e
        raise LoginError(
            f"Garmin rejected the login:\n{e}\n\n"
            "If your password is correct, Garmin may have changed its login system.\n"
            "Try `pip install --upgrade garminconnect`, or use the FIT importer "
            "(see README) until the library is fixed."
        ) from e
    except GarminConnectTooManyRequestsError as e:
        raise LoginError(
            "Garmin is rate-limiting logins (HTTP 429). Wait 15-60 minutes and try again."
        ) from e
    except GarminConnectConnectionError as e:
        raise LoginError(f"Could not reach Garmin Connect: {e}") from e

    save_tokens(client)
    return client


def save_tokens(client: Garmin) -> None:
    """Persist (possibly refreshed) tokens so the next run needs no login."""
    try:
        client.client.dump(config.TOKEN_DIR)
    except Exception as e:  # never fatal: worst case you log in again next time
        print(f"Warning: could not save login tokens: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        c = get_client()
    except LoginError as err:
        sys.exit(str(err))
    print(f"Logged in as {c.get_full_name()}. Tokens cached in {config.TOKEN_DIR}")
