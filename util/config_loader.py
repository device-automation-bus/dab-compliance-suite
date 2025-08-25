# util/config_loader.py
"""
Simple helpers for resolving local app artifacts and App Store URLs for DAB tests.

- Normal runs (list/execute) are **non-interactive**. Missing artifacts should cause callers to fail.
- Use your CLI's `--init` mode to run `init_interactive_setup(...)` once and provide/override paths/URLs.

APIs:
- ensure_app_available(...): returns payload for `applications/install` with a **plain absolute path**.
- get_appstore_url_or_fail(...): returns App Store URL (non-interactive), raises if missing.
- get_or_prompt_appstore_url(...): back-compat shim; non-interactive by default, can prompt in --init.
- init_interactive_setup(...): interactive bootstrap used only with `--init` (supports overriding).
"""

from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

from logger import LOGGER  # shared suite logger

DEFAULT_CONFIG_DIR = "config/apps"
DEFAULT_STORE_JSON = f"{DEFAULT_CONFIG_DIR}/sample_app.json"

def _find_app_file(
    app_name_prefix: str,
    config_dir: str,
    exts: Tuple[str, ...] = (".apk", ".apks"),
) -> Tuple[Optional[Path], str]:
    """Return (path, ext_without_dot) for the first file starting with prefix and allowed ext, else (None, '')."""
    p = Path(config_dir)
    if not p.exists():
        return None, ""
    for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
        if entry.is_file() and entry.name.startswith(app_name_prefix):
            ext = entry.suffix.lower()
            if not exts or ext in exts:
                return entry.resolve(), ext.lstrip(".")
    return None, ""

def ensure_app_available(
    app_id: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
    allowed_exts: Tuple[str, ...] = (".apk", ".apks"),
    prompt_if_missing: bool = False,
) -> Dict[str, object]:
    """
    Ensure <app_id>.(apk|apks) exists in `config_dir` and return an install payload:
      {"appId": app_id, "url": "/abs/path/<app_id>.<ext>", "format": "<ext>", "timeout": timeout}
    - Non-interactive by default; set prompt_if_missing=True only in `--init`.
    """
    os.makedirs(config_dir, exist_ok=True)

    found_path, fmt = _find_app_file(app_id, config_dir, allowed_exts)
    if not found_path:
        if not prompt_if_missing:
            raise FileNotFoundError(
                f"Install artifact for app_id='{app_id}' not found in '{config_dir}'. "
                "Place it there or run with --init."
            )
        # Interactive: ask once and copy into place
        LOGGER.warn(f"[INIT] App '{app_id}' not found in '{config_dir}'")
        user_path = input("Full path to the app file (.apk or .apks): ").strip()
        src = Path(user_path)
        if not src.is_file():
            raise FileNotFoundError(f"Provided file does not exist: {src}")
        ext = src.suffix.lower()
        if allowed_exts and ext not in allowed_exts:
            raise ValueError(f"Unsupported format '{ext}'. Allowed: {', '.join(allowed_exts)}")
        dest = Path(config_dir) / f"{app_id}{ext}"
        shutil.copy2(src, dest)
        LOGGER.info(f"[INIT] Copied app to: {dest}")
        found_path, fmt = dest.resolve(), ext.lstrip(".")

    return {
        "appId": app_id,
        "url": str(found_path),  # plain absolute path (NOT file://)
        "format": fmt or found_path.suffix.lstrip(".").lower(),
        "timeout": int(timeout),
    }


def prompt_and_store_appstore_url(config_path: str = DEFAULT_STORE_JSON, default_url: str = "") -> None:
    """
    Prompt for an App Store URL and save to JSON (used only during `--init`).
    If `default_url` is provided, pressing ENTER keeps it; any non-empty input overrides it.
    """
    os.makedirs(Path(config_path).parent, exist_ok=True)
    if default_url:
        LOGGER.info(f"[INIT] Current App Store URL: {default_url}")
        entered = input("Enter NEW App Store URL to override, or press ENTER to keep current: ").strip()
        new_url = default_url if entered == "" else entered
    else:
        # Require a value if none exists yet
        while True:
            entered = input("Enter App Store URL for install-from-app-store tests: ").strip()
            if entered:
                new_url = entered
                break
            LOGGER.warn("[INIT] URL cannot be empty. Please provide a valid URL.")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"app_url": new_url}, f, indent=2)
    LOGGER.info(f"[INIT] Stored App Store URL at {config_path}")


def load_appstore_url(config_path: str = DEFAULT_STORE_JSON) -> str:
    """Load App Store URL string from JSON, raising if the file is missing."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"App Store config not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("app_url", "")


def get_appstore_url_or_fail(config_path: str = DEFAULT_STORE_JSON) -> str:
    """Non-interactive: return App Store URL or raise if missing/empty (used in list/run)."""
    url = load_appstore_url(config_path)
    if not url or not url.strip():
        raise ValueError(
            "App Store URL not configured. Run your CLI with --init to set it "
            f"(expected key 'app_url' in {config_path})."
        )
    return url


def get_or_prompt_appstore_url(
    config_path: str = DEFAULT_STORE_JSON,
    prompt_if_missing: bool = False
) -> str:
    """
    Backwards-compatible shim:
      - Default non-interactive (prompt_if_missing=False): return URL or raise if missing/empty.
      - If prompt_if_missing=True (use only in --init), prompt and store, then return URL.
    """
    try:
        return get_appstore_url_or_fail(config_path)
    except (FileNotFoundError, ValueError):
        if prompt_if_missing:
            LOGGER.warn("[INIT] App Store URL not configured; prompting now.")
            prompt_and_store_appstore_url(config_path)
            return get_appstore_url_or_fail(config_path)
        raise


def init_interactive_setup(
    app_ids: Tuple[str, ...] = ("Sample_App",),
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Interactive bootstrap used by `--init`: collect (and optionally override) app files
    and the App Store URL.
    - If an APK is already present for an appId, user may press ENTER to keep it or
      provide a new path to override it.
    - If an App Store URL already exists, user may press ENTER to keep it or enter a new one.
    """
    os.makedirs(config_dir, exist_ok=True)
    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")

    # Apps: allow override
    for app_id in app_ids:
        try:
            current_path, _fmt = _find_app_file(app_id, config_dir)
            if current_path:
                LOGGER.info(f"[INIT] Current artifact for '{app_id}': {current_path}")
                entered = input(
                    f"Enter NEW file path to override '{app_id}' or press ENTER to keep current: "
                ).strip()
                if entered:
                    src = Path(entered)
                    if not src.is_file():
                        LOGGER.warn(f"[INIT] Provided file does not exist: {src}")
                    else:
                        ext = src.suffix.lower()
                        if ext not in (".apk", ".apks"):
                            LOGGER.warn("[INIT] Unsupported format. Allowed: .apk, .apks")
                        else:
                            dest = Path(config_dir) / f"{app_id}{ext}"
                            shutil.copy2(src, dest)
                            LOGGER.info(f"[INIT] Replaced artifact: {dest}")
                else:
                    LOGGER.info(f"[INIT] Keeping existing artifact for '{app_id}'.")
            else:
                # Missing → prompt once and copy
                ensure_app_available(app_id=app_id, config_dir=config_dir, prompt_if_missing=True)
        except Exception as e:
            LOGGER.warn(f"[INIT][WARN] {app_id}: {e}")

    # Store URL: allow override
    if ask_store_url:
        current_url = ""
        try:
            current_url = load_appstore_url(store_config_path)
        except FileNotFoundError:
            current_url = ""
        try:
            prompt_and_store_appstore_url(store_config_path, default_url=current_url)
        except Exception as e:
            LOGGER.warn(f"[INIT][WARN] store-url: {e}")


class PayloadConfigError(Exception):
    """Raised when a test payload cannot be built due to missing config/artifacts."""
    def __init__(self, reason: str, hint: str = ""):
        super().__init__(reason)
        self.hint = hint


def _hint_from_reason(reason: str) -> str:
    low = str(reason).lower()
    if "install artifact" in low or "not found in 'config/apps'" in low or "config/apps" in low:
        return "Place the APK in config/apps or run with --init to configure paths."
    if "app store" in low or "app_url" in low or "sample_app.json" in low:
        return "Run with --init to set the App Store URL (config/apps/sample_app.json)."
    return ""


def resolve_body_or_raise(body_spec) -> str:
    """
    Build a body string from a spec:
      - callable -> call it
      - dict/list -> JSON-encode
      - None -> "{}"
      - str/other -> str()
    Raises PayloadConfigError with a helpful hint if body_spec throws.
    """
    try:
        body = body_spec() if callable(body_spec) else body_spec
        if isinstance(body, (dict, list)):
            return json.dumps(body)
        if body is None:
            return "{}"
        return str(body)
    except Exception as e:
        raise PayloadConfigError(str(e), _hint_from_reason(e))
