"""Check the Langfuse setup without sending any conversation data.

    uv run python scripts/check_langfuse.py

Prints whether tracing is enabled, where it points and whether the keys are accepted. Never prints
a key. (A real run needs the API or `python -m medagent.agents.chat`; see docs/SETUP.md.)
"""

from medagent.core.config import get_settings


def main() -> None:
    settings = get_settings()
    have_keys = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    print(f"keys set:           {have_keys}")
    print(f"enabled:            {settings.langfuse_enabled}")
    print(f"host:               {settings.langfuse_base_url}")
    print(f"content captured:   {settings.langfuse_capture_content}  (False = text is redacted)")
    print(f"share of turns:     {settings.langfuse_sample_rate:.0%}")
    if not have_keys or settings.langfuse_secret_key is None:
        print("\nTracing is off: set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env.")
        return

    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )
    try:
        ok = client.auth_check()
    finally:
        client.shutdown()
    print(f"keys accepted:      {ok}")
    if not ok:
        print(
            "\nThe keys were rejected: check the region host (EU vs US) and that the key pair "
            "belongs to one project."
        )


if __name__ == "__main__":
    main()
