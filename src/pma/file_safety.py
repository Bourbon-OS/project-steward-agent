from __future__ import annotations

from pathlib import Path


ALLOWED_TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
ALLOWED_TEXT_NAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "NOTICE",
}
SENSITIVE_DIR_NAMES = {".aws", ".azure", ".gnupg", ".kube", ".ssh"}
SENSITIVE_EXACT_NAMES = {
    ".npmrc",
    ".pypirc",
    "auth.json",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "token.json",
}
SENSITIVE_FILE_SUFFIXES = {".jks", ".key", ".p12", ".pem", ".pfx"}
SENSITIVE_NAME_FRAGMENTS = {
    "credential",
    "private_key",
    "secret",
    "token",
}


def is_sensitive_path(relative: Path) -> bool:
    lowered_parts = [part.lower() for part in relative.parts]
    if not lowered_parts:
        return False
    if any(part in SENSITIVE_DIR_NAMES for part in lowered_parts[:-1]):
        return True

    name = lowered_parts[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if name in SENSITIVE_EXACT_NAMES:
        return True
    if Path(name).suffix in SENSITIVE_FILE_SUFFIXES:
        return True
    return any(fragment in name for fragment in SENSITIVE_NAME_FRAGMENTS)


def is_allowed_text_file(path: Path) -> bool:
    return (
        path.name in ALLOWED_TEXT_NAMES
        or path.suffix.lower() in ALLOWED_TEXT_SUFFIXES
    )
