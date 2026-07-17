"""File path sandbox helpers for upload/download endpoints.

Security posture (v4.42.0 hardening pass)
-----------------------------------------

Every file-touching REST endpoint (upload / download / view /
edit / create) routes through the validators in this module.
Two independent layers of defence:

1. **Home-scope check.** ``resolve_home_path`` resolves the
   requested path through ``expanduser`` + ``resolve`` (which
   follows symlinks) and rejects anything that lands outside
   ``$HOME``. Blocks classic path traversal (``../../../etc/passwd``)
   and symlink-escape (``~/malicious-link -> /etc/shadow``).
2. **Sensitive-file blocklist.** Even inside the user's home,
   certain files must never be readable / writable via the
   HTTP surface:

   * The bridge's own token file (``token.txt``): reading it
     hands the caller the master bearer that would otherwise
     be revocable.
   * User-scoped credentials (``.ssh/*``, ``.aws/credentials``,
     ``.gnupg/**``, ``.docker/config.json``, ``.netrc``,
     ``.git-credentials``, browser password stores).
   * Shell history that commonly contains pasted secrets
     (``.bash_history``, ``.zsh_history``, ``.python_history``).
   * The user account database of the bridge itself
     (``users.json``).

   These are matched **both** by basename (backward compat with
   ``SENSITIVE_FILE_BASENAMES``) **and** by dotted-prefix
   (``.ssh/authorized_keys``, ``.aws/credentials/main``, and
   nested paths inside these directories). The prefix check is
   the v4.42.0 addition -- pre-v4.42.0 only basenames were
   blocked, which meant ``.ssh/authorized_keys`` was readable
   and writable via ``fs.view`` / ``fs.edit``.

3. **Endpoint-parity.** Pre-v4.42.0, ``validate_download_target``
   did the home-scope check but skipped the sensitive-basename
   check that ``validate_view_target`` performed. Any authed
   agent could ``GET /v1/download?path=token.txt`` and retrieve
   the master token. v4.42.0 makes ``validate_download_target``
   run the same sensitivity check as ``validate_view_target``
   so the sub-agent role model (multi-agent tokens introduced
   in v3.86.0) actually holds.

Threat model
------------

The blocklist is meant to survive the following adversaries:

* **Authed narrow-scope agent** (multi-agent bearer token with
  limited role) trying to escalate by exfiltrating the master
  token or credential material.
* **Authed operator** who accidentally aims a script at a
  credential file (``curl -X GET .../v1/download?path=.ssh/id_ed25519``
  in a debug session).
* **Compromised web extension / browser** presenting a stolen
  bearer, walking the filesystem for anything valuable.

It is NOT meant to defend against a caller with shell
access to the bridge host itself -- at that point they can
read the files directly. The blocklist is about the HTTP
surface being no more permissive than the shell would be for
an unprivileged account.
"""
from __future__ import annotations

from pathlib import Path


def resolve_home_path(target: str, *, root: Path, home: Path) -> tuple[Path | None, str | None, int]:
    if not target:
        return None, "missing path", 400
    if ".." in Path(target).parts:
        return None, "path traversal not allowed", 400
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = root / target_path
    try:
        target_path.resolve().relative_to(home.resolve())
    except ValueError:
        return None, "path outside home directory", 403
    return target_path, None, 200


# Canonical set of sensitive file basenames that must never be read, written,
# listed, viewed, created, or edited through any fs endpoint (REST or MCP).
# This is the single source of truth — import it instead of redefining locally.
#
# v4.42.0 additions: everything from the audit "credential material" list
# that has a plausible bare-basename form (many credential files are only
# meaningful inside a specific subdirectory, so they are covered by
# ``SENSITIVE_DIR_PREFIXES`` below rather than duplicated here).
SENSITIVE_FILE_BASENAMES = frozenset({
    # Bridge itself
    "token.txt", "users.json",
    # Env / dotenv files (any depth)
    ".env",
    # SSH private keys, both classic filenames and common variants
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub",
    # Common credential dotfiles at ~/
    ".netrc", ".ssh_config",
    # v4.42.0 additions
    ".git-credentials",       # git credential-store default location
    ".pypirc",                # PyPI publishing credentials
    ".npmrc",                 # npm auth tokens
    ".docker",                # docker config directory
    ".dockercfg",             # legacy docker config
    ".kube",                  # kubectl config
    ".gitconfig",             # sometimes contains signing keys / URL creds
    # Shell history frequently contains pasted secrets
    ".bash_history", ".zsh_history", ".sh_history", ".ash_history",
    ".fish_history", ".python_history", ".psql_history", ".mysql_history",
    ".rediscli_history", ".sqlite_history", ".node_repl_history",
})


# Dotted-prefix directories whose entire subtree is off-limits.
# Path is matched against the resolved-relative-to-home tuple:
# any component of the resolved path that matches (or a segment
# that starts with these prefixes) blocks the request.
#
# The check is deliberately conservative -- a directory whose
# NAME is one of these is treated as sensitive even if it isn't
# in the "official" location. So ``.ssh`` anywhere under $HOME
# is blocked, not just ``~/.ssh``. Rationale: an attacker
# staging a rogue ``~/projects/.ssh/authorized_keys`` would
# otherwise squeak through.
SENSITIVE_DIR_PREFIXES: frozenset[str] = frozenset({
    ".ssh",           # SSH keys, authorized_keys, known_hosts
    ".aws",           # AWS credentials + config
    ".gnupg",         # GPG keyring
    ".docker",        # docker config.json (auth tokens)
    ".kube",          # kubernetes contexts
    ".config/gh",     # GitHub CLI auth
    ".config/git",    # git credentials via helper
    ".mozilla",       # Firefox profile (logins.json)
    ".config/google-chrome",  # Chrome profile (Login Data)
    ".config/chromium",       # Chromium profile
})


# Backcompat alias for the name introduced in v3.2.0 (kept so existing imports
# and the documented surface keep working). Points at the same object.
_EDIT_BLOCKED_BASENAMES = SENSITIVE_FILE_BASENAMES


def _path_hits_sensitive_prefix(target_path: Path, home: Path) -> str | None:
    """Return the offending prefix when ``target_path`` lives
    inside one of the sensitive directory prefixes, or ``None``
    when the path is clear.

    Matched against the path relative to ``home``. Two match
    modes:

    * Exact segment match anywhere in the path (``a/b/.ssh/c``
      hits ``.ssh``).
    * Full-prefix match for multi-segment prefixes (``.config/gh``
      matches when consecutive segments are ``.config`` then
      ``gh``).

    Multi-segment prefixes handle the ``.config`` case where
    only *some* subdirectories are sensitive (``.config/git``
    yes, ``.config/htop`` no).

    Returns the human-readable prefix name so the caller can
    include it in the error message.
    """
    try:
        rel = target_path.resolve().relative_to(home.resolve())
    except ValueError:
        # Path escaped home; the caller already returned 403 for
        # that case, this is belt+suspenders.
        return None
    parts = rel.parts
    if not parts:
        return None
    for prefix in SENSITIVE_DIR_PREFIXES:
        segs = prefix.split("/")
        # Single-segment prefix: match anywhere in the path.
        if len(segs) == 1:
            if segs[0] in parts:
                return prefix
            continue
        # Multi-segment prefix: match consecutive segments.
        n = len(segs)
        for i in range(len(parts) - n + 1):
            if list(parts[i:i + n]) == segs:
                return prefix
    return None


def _sensitivity_error(target_path: Path, home: Path, *,
                       action: str) -> tuple[str, int] | None:
    """Composite check used by every validator: returns
    ``(message, http_status)`` when the target is off-limits.

    Combines the basename blocklist and the sensitive-directory
    prefix scan. The message names the specific file / prefix
    so an operator debugging a 403 can tell which rule fired.

    ``action`` is a verb the caller can inject into the error
    message ("reading", "editing", "creating") so the same
    helper stays generic across every fs verb.
    """
    if target_path.name in SENSITIVE_FILE_BASENAMES:
        return f"{action} {target_path.name} is not allowed", 403
    hit = _path_hits_sensitive_prefix(target_path, home)
    if hit is not None:
        return f"{action} files under {hit}/ is not allowed", 403
    return None


def validate_upload_target(target: str, *, root: Path, home: Path, bridge_py: Path) -> tuple[Path | None, str | None, int]:
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        if err == "path outside home directory":
            return None, "upload path must be inside user home", status
        return None, err, status
    if target_path.resolve() == bridge_py.resolve():
        return None, "cannot overwrite the bridge itself", 403
    # v4.42.0: upload now runs the same sensitivity check as
    # view/edit. Previously an authed caller could upload a
    # replacement ``token.txt`` or ``.ssh/authorized_keys``,
    # which would be a straight escalation path.
    sens = _sensitivity_error(target_path, home, action="uploading")
    if sens is not None:
        return None, sens[0], sens[1]
    return target_path, None, 200


def validate_download_target(target: str, *, root: Path, home: Path) -> tuple[Path | None, str | None, int]:
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        return None, err, status
    if not target_path.exists() or not target_path.is_file():
        return None, "file not found", 404
    # v4.42.0 critical fix: pre-v4.42.0 this function skipped
    # the sensitivity check that its sibling ``validate_view_target``
    # performed. Any authed caller could
    # ``GET /v1/download?path=token.txt`` and pull the master
    # bearer token -- turning the multi-agent narrow-scope
    # tokens introduced in v3.86.0 into a full-privilege
    # escalation path. Same check as view now.
    sens = _sensitivity_error(target_path, home, action="downloading")
    if sens is not None:
        return None, sens[0], sens[1]
    return target_path, None, 200


def validate_edit_target(target: str, *, root: Path, home: Path, bridge_py: Path) -> tuple[Path | None, str | None, int]:
    """Validate target for fs.edit: must exist, be inside home, not be blocked."""
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        return None, err, status
    sens = _sensitivity_error(target_path, home, action="editing")
    if sens is not None:
        return None, sens[0], sens[1]
    if target_path.resolve() == bridge_py.resolve():
        return None, "cannot edit the bridge itself", 403
    if not target_path.exists() or not target_path.is_file():
        return None, "file not found", 404
    return target_path, None, 200


def validate_view_target(target: str, *, root: Path, home: Path) -> tuple[Path | None, str | None, int]:
    """Validate target for fs.view: must exist as a file, be inside home, not be sensitive."""
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        return None, err, status
    sens = _sensitivity_error(target_path, home, action="viewing")
    if sens is not None:
        return None, sens[0], sens[1]
    if not target_path.exists() or not target_path.is_file():
        return None, "file not found", 404
    return target_path, None, 200


def validate_create_target(target: str, *, root: Path, home: Path, bridge_py: Path) -> tuple[Path | None, str | None, int]:
    """Validate target for fs.create: must not exist, be inside home, not be sensitive/bridge."""
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        if err == "path outside home directory":
            return None, "create path must be inside user home", status
        return None, err, status
    sens = _sensitivity_error(target_path, home, action="creating")
    if sens is not None:
        return None, sens[0], sens[1]
    if target_path.resolve() == bridge_py.resolve():
        return None, "cannot overwrite the bridge itself", 403
    if target_path.exists():
        return None, f"file already exists: {target_path.name} (use PATCH /v1/fs/edit to modify)", 409
    return target_path, None, 200
