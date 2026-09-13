"""Browser-driven access to the parts of Karlancer that need a login.

Everything here touches the user's real account, so it is deliberately
separate from the unauthenticated `karyab.api` client and follows two rules:

  * The user logs in themselves, in a visible browser. karyab never sees,
    stores, or types a password.
  * The saved session is account access in a file. It is written with
    0600 permissions, kept out of git, and never logged.
"""

from .session import SESSION_PATH, SessionExpired, load_context, save_session

__all__ = ["SESSION_PATH", "SessionExpired", "load_context", "save_session"]
