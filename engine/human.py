"""A human at a terminal approves each write to shared memory (D-0.10-02).

`harness memory promote` and `harness memory accept` open the controlling
terminal, show what they will write and a random code, and write only when
the code is typed back. The code goes to the terminal, never to stdout or
stderr, so a caller that only reads the command's output cannot learn it.
A process with no controlling terminal (an agent's shell, CI) is refused.

Limit: a caller that runs the command under a terminal it controls itself
(`script`, `expect`) can read the code. The permit layer still asks before
such a command runs.
"""
from __future__ import annotations

import os
import secrets

from . import HarnessError

# no look-alike pairs (0/O, 1/I/L, 2/Z, 5/S, 8/B)
_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
_CODE_LEN = 4


def new_code() -> str:
    """A random code for one approval."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def confirm(action: str, summary: str, *, tty: str = "/dev/tty") -> None:
    """Return when a human types the code shown on the terminal.

    Args:
        action: The command, as its errors name it (`memory promote`).
        summary: What the command will write, shown before the code.
        tty: The terminal device. Tests pass a pseudo-terminal's path.

    Raises:
        HarnessError: no controlling terminal, or the typed code differs.
    """
    try:
        fd = os.open(tty, os.O_RDWR | os.O_NOCTTY)
    except OSError:
        raise HarnessError(
            f"{action}: a human must approve this at a terminal, and this "
            f"process has none. Fix: run the same command yourself in your "
            f"own terminal.") from None
    code = new_code()
    try:
        os.write(fd, (f"\n{summary.rstrip()}\n\n"
                      f"To approve, type {code} and press Enter. "
                      f"Anything else cancels: ").encode("utf-8"))
        answer = _read_line(fd).strip().upper()
    finally:
        os.close(fd)
    if answer != code:
        raise HarnessError(
            f"{action}: the code did not match, so nothing was written. "
            f"Fix: run the command again and type the code it shows.")


def _read_line(fd: int, limit: int = 256) -> str:
    """One line from the terminal, at most `limit` bytes; "" at end of file."""
    data = b""
    while len(data) < limit and not data.endswith(b"\n"):
        chunk = os.read(fd, 1)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8", "replace")
