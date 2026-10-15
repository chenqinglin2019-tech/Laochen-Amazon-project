#!/usr/bin/env python3
"""Accept new cloud credentials through stdin only; never echo their values."""
from auth_runtime import configure_console, main

if __name__ == "__main__":
    configure_console()
    raise SystemExit(main(["configure"]))
