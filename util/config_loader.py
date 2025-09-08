"""
Helpers for resolving local app artifacts and App Store URLs for DAB tests.

Key features:
- Accept ANY file extension (no hardcoding).
- Interactive N-app init via init_sample_apps(count, base_name).
- Non-interactive payload builders for tests.
- Per-app URL map (appId -> url) at config/apps/app_urls.json.
- Backward compatible single global URL (config/apps/sample_app.json).

Public APIs (stable):
- ensure_app_available_anyext(app_id, config_dir=..., timeout=..., prompt_if_missing=False)
- ensure_apps_available_anyext(app_ids=[...], ...)
- make_app_id_list(count=3, base_name="sample_app")
- init_sample_apps(count=3, base_name="sample_app", config_dir=..., ask_store_url=True, store_config_path=...)
- get_sample_apps_payloads(count=3, base_name="sample_app", ...)
- get_apps_payloads(app_ids=[...], ...)
- init_interactive_setup(app_ids=("Sample_App",), ...)  # legacy wrapper
- ensure_app_available(...) & ensure_apps_available(...) # legacy aliases

URL helpers:
- set_app_url(app_id, url)
- get_app_url_or_fail(app_id)             # prefers per-app; falls back to global
- get_urls_for_apps([ids...]) -> {id:url}
- load_app_urls_map()/save_app_urls_map()

Misc:
- App Store URL helpers (get_appstore_url_or_fail, get_or_prompt_appstore_url, ...)
- PayloadConfigError + resolve_body_or_raise
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from logger import LOGGER  # shared suite logger

# -------------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = "config/apps"
DEFAULT_STORE_JSON = f"{DEFAULT_CONFIG_DIR}/sample_app.json"  # legacy single URL
APP_URLS_JSON = f"{DEFAULT_CONFIG_DIR}/app_urls.json"         # per-app URL map

# -------------------------------------------------------------------------
# Internal utilities
# -------------------------------------------------------------------------

def _safe_app_id(app_id: str) -> str:
    """Normalize appId to a safe filename stem (keep letters, digits, _ - .)."""
    s = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in (app_id or "app"))
    return s or "app"


def _find_first_app_file(app_id: str, config_dir: str) -> Optional[Path]:
    """
    Find an artifact in config_dir:
      - Exact filename without extension (case-insensitive), or
      - Any extension with '<app_id>.' prefix (case-insensitive).
    """
    p = Path(config_dir)
    if not p.exists():
        return None

    aid = app_id.lower()

    # Exact filename without extension (case-insensitive)
    for entry in p.iterdir():
        if entry.is_file() and entry.name.lower() == aid:
            return entry.resolve()

    # Any extension with "<app_id>." prefix (case-insensitive)
    prefix = aid + "."
    for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
        if entry.is_file() and entry.name.lower().startswith(prefix):
            return entry.resolve()

    return None


def _copy_into_config_dir_with_app_id(src_path: Path, config_dir: str, app_id: str) -> Path:
    """Copy src_path into config_dir as '<app_id>.<original_ext>' (or '<app_id>' if none)."""
    dest_dir = Path(config_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ext = src_path.suffix  # may be empty; keep original as-is
    dest = dest_dir / f"{app_id}{ext}"
    shutil.copy2(src_path, dest)
    return dest.resolve()


def _to_install_payload(app_id: str, file_path: Path, timeout: int = 60000) -> Dict[str, object]:
    """
    Build a standard install payload:
      {"appId": app_id, "url": "<abs path>", "format": "<ext-or-bin>", "timeout": timeout}
    """
    ext = file_path.suffix[1:].lower() if file_path.suffix else "bin"
    return {
        "appId": app_id,
        "url": str(file_path),     # absolute filesystem path (no file://)
        "format": ext or "bin",
        "timeout": int(timeout),
    }

# -------------------------------------------------------------------------
# Core: ensure app(s) available (ANY extension)
# -------------------------------------------------------------------------

def ensure_app_available_anyext(
    app_id: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
    prompt_if_missing: bool = False,
) -> Dict[str, object]:
    """
    Ensure an app artifact exists under config_dir with ANY extension.

    Behavior:
      - Looks for '<app_id>' (no ext) or '<app_id>.<ext>'.
      - If missing and prompt_if_missing=False → FileNotFoundError.
      - If missing and prompt_if_missing=True  → prompt once, copy into config, and continue.

    Returns: payload usable by `applications/install`.
    """
    app_id = _safe_app_id(app_id)
    Path(config_dir).mkdir(parents=True, exist_ok=True)

    found = _find_first_app_file(app_id, config_dir)
    if not found:
        if not prompt_if_missing:
            raise FileNotFoundError(
                f"Install artifact for app_id='{app_id}' not found in '{config_dir}'. "
                "Place it there (any extension) or run with --init."
            )
        LOGGER.warn(f"[INIT] App '{app_id}' not found in '{config_dir}'")
        user_path = input("Full path to the app file (any extension): ").strip()
        src = Path(user_path)
        if not src.is_file():
            raise FileNotFoundError(f"Provided file does not exist: {src}")
        found = _copy_into_config_dir_with_app_id(src, config_dir, app_id)
        LOGGER.info(f"[INIT] Copied app to: {found}")
    else:
        found = found.resolve()

    return _to_install_payload(app_id, found, timeout=timeout)


def ensure_apps_available_anyext(
    app_ids: List[str],
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
    prompt_if_missing: bool = False,
) -> List[Dict[str, object]]:
    """Ensure multiple apps are available. Returns payloads in given order."""
    return [
        ensure_app_available_anyext(
            app_id=_safe_app_id(app_id),
            config_dir=config_dir,
            timeout=timeout,
            prompt_if_missing=prompt_if_missing,
        )
        for app_id in app_ids
    ]

# -------------------------------------------------------------------------
# Uniform N-app helpers (scalable sample apps)
# -------------------------------------------------------------------------

def make_app_id_list(count: int = 3, base_name: str = "Sample_App") -> List[str]:
    """Build ['sample_app', 'sample_app1', 'sample_app2', ...] up to count."""
    base_name_cap = (base_name[:1].upper() + base_name[1:]) if base_name else "Sample_App"
    ids: List[str] = []
    for i in range(count):
        raw = base_name_cap if i == 0 else f"{base_name_cap}{i}"
        ids.append(_safe_app_id(raw))
    return ids


def init_sample_apps(
    count: int = 3,
    base_name: str = "sample_app",
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Interactive init for N sample apps:

      For each appId in make_app_id_list(...):
        - If artifact exists, ENTER keeps it; otherwise prompt for a file and copy it.
      Optionally prompt per-app URLs (preferred) and, if none provided, a single legacy URL.
    """
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    app_ids = make_app_id_list(count=count, base_name=base_name)

    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")
    for app_id in app_ids:
        try:
            current = _find_first_app_file(app_id, config_dir)
            if current:
                LOGGER.info(f"[INIT] Current artifact for '{app_id}': {current.resolve()}")
                entered = input(
                    f"Enter NEW file path to override '{app_id}' or press ENTER to keep current: "
                ).strip()
                if entered:
                    src = Path(entered)
                    if not src.is_file():
                        LOGGER.warn(f"[INIT] Provided file does not exist: {src}")
                    else:
                        dest = _copy_into_config_dir_with_app_id(src, config_dir, app_id)
                        LOGGER.info(f"[INIT] Replaced artifact: {dest}")
                else:
                    LOGGER.info(f"[INIT] Keeping existing artifact for '{app_id}'.")
            else:
                ensure_app_available_anyext(
                    app_id=app_id,
                    config_dir=config_dir,
                    prompt_if_missing=True,
                )
        except Exception as e:
            LOGGER.warn(f"[INIT][WARN] {app_id}: {e}")

    # Optional per-app URL prompts
    if ask_store_url:
        LOGGER.info("[INIT] Configure App Store URLs (per app). Leave blank to keep/skip.")
        urls_map = load_app_urls_map(silent=True)
        changed = False
        for app_id in app_ids:
            current = urls_map.get(app_id, "")
            prompt = f"Enter App Store URL for '{app_id}'"
            if current:
                prompt += f" (ENTER to keep: {current})"
            prompt += ": "
            entered = input(prompt).strip()
            if entered:
                set_app_url(app_id, entered)
                changed = True
                LOGGER.info(f"[INIT] URL set for '{app_id}'.")
        if not changed:
            LOGGER.info("[INIT] No per-app URL changes.")
        # Back-compat: if *none* set per-app, allow global legacy URL
        if not any(load_app_urls_map(silent=True).values()):
            try:
                current_url = load_appstore_url(store_config_path)
            except FileNotFoundError:
                current_url = ""
            try:
                prompt_and_store_appstore_url(store_config_path, default_url=current_url)
            except Exception as e:
                LOGGER.warn(f"[INIT][WARN] store-url(global): {e}")

# -------------------------------------------------------------------------
# Batch payloads
# -------------------------------------------------------------------------

def get_sample_apps_payloads(
    count: int = 3,
    base_name: str = "sample_app",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
) -> List[Dict[str, object]]:
    """Non-interactive payloads for N uniform sample apps."""
    app_ids = make_app_id_list(count=count, base_name=base_name)
    return ensure_apps_available_anyext(
        app_ids=app_ids,
        config_dir=config_dir,
        timeout=timeout,
        prompt_if_missing=False,
    )


def get_apps_payloads(
    app_ids: List[str],
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
) -> List[Dict[str, object]]:
    """Non-interactive payloads for explicit app_ids (raises if any missing)."""
    return ensure_apps_available_anyext(
        app_ids=[_safe_app_id(a) for a in app_ids],
        config_dir=config_dir,
        timeout=timeout,
        prompt_if_missing=False,
    )

# -------------------------------------------------------------------------
# App Store URL helpers (compatibility)
# -------------------------------------------------------------------------

def prompt_and_store_appstore_url(config_path: str = DEFAULT_STORE_JSON, default_url: str = "") -> None:
    """Prompt for a single global App Store URL and save to JSON (used during --init as fallback)."""
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    if default_url:
        LOGGER.info(f"[INIT] Current App Store URL: {default_url}")
        entered = input("Enter NEW App Store URL to override, or press ENTER to keep current: ").strip()
        new_url = default_url if entered == "" else entered
    else:
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
    """Load the global App Store URL string from JSON (raises if file missing)."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"App Store config not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("app_url", "")


def get_appstore_url_or_fail(config_path: str = DEFAULT_STORE_JSON) -> str:
    """Return global App Store URL or raise if missing/empty."""
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
      - Default non-interactive: return URL or raise.
      - If prompt_if_missing=True: prompt and store, then return URL.
    """
    try:
        return get_appstore_url_or_fail(config_path)
    except (FileNotFoundError, ValueError):
        if prompt_if_missing:
            LOGGER.warn("[INIT] App Store URL not configured; prompting now.")
            prompt_and_store_appstore_url(config_path)
            return get_appstore_url_or_fail(config_path)
        raise

# -------------------------------------------------------------------------
# Per-app URL map (appId -> url)
# -------------------------------------------------------------------------

def load_app_urls_map(path: str = APP_URLS_JSON, silent: bool = False) -> Dict[str, str]:
    """Return {appId: url} map; {} if missing or invalid."""
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        if not silent:
            LOGGER.warn(f"[URLS] Failed to load map '{path}': {e}")
        return {}


def save_app_urls_map(mapping: Dict[str, str], path: str = APP_URLS_JSON) -> None:
    """Persist {appId: url} map to disk."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)


def set_app_url(app_id: str, url: str, path: str = APP_URLS_JSON) -> None:
    """Set per-app URL in the map (overwrites existing value)."""
    m = load_app_urls_map(path, silent=True)
    m[_safe_app_id(app_id)] = (url or "").strip()
    save_app_urls_map(m, path)


def get_app_url_or_fail(app_id: str, path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> str:
    """Get per-app URL; if missing, fall back to global; else raise with guidance."""
    m = load_app_urls_map(path, silent=True)
    url = (m.get(_safe_app_id(app_id), "") or "").strip()
    if url:
        return url
    # Fallback to legacy single URL
    url = load_appstore_url(fallback_global)
    if url and url.strip():
        return url
    raise ValueError(
        f"No URL configured for app_id='{app_id}'. "
        f"Run --init to set per-app URLs or configure global URL at {fallback_global}."
    )


def get_urls_for_apps(app_ids: List[str], path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> Dict[str, str]:
    """Return a dict of appId->url for requested app IDs (raises if any missing)."""
    return {
        _safe_app_id(a): get_app_url_or_fail(a, path=path, fallback_global=fallback_global)
        for a in app_ids
    }

# -------------------------------------------------------------------------
# Payload builder & error
# -------------------------------------------------------------------------

class PayloadConfigError(Exception):
    """Raised when a test payload cannot be built due to missing config/artifacts."""
    def __init__(self, reason: str, hint: str = ""):
        super().__init__(reason)
        self.hint = hint


def _hint_from_reason(reason: str) -> str:
    low = str(reason).lower()
    if "install artifact" in low or "config/apps" in low:
        return "Place the app file in config/apps or run with --init to configure paths."
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

# -------------------------------------------------------------------------
# Backward-compatibility aliases
# -------------------------------------------------------------------------

def ensure_app_available(*args, **kwargs):
    """Legacy alias → any-extension version."""
    return ensure_app_available_anyext(*args, **kwargs)

def ensure_apps_available(app_ids, **kwargs):
    """Legacy alias for batch ensure; preserves old import sites."""
    return ensure_apps_available_anyext(app_ids=app_ids, **kwargs)

# -------------------------------------------------------------------------
# Legacy interactive wrapper
# -------------------------------------------------------------------------

def init_interactive_setup(
    app_ids: Tuple[str, ...] = ("Sample_App",),
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Legacy interactive bootstrap for explicit app_ids:
      - For each appId, allow override/keep or prompt to add (ANY extension).
      - Optionally prompt to store per-app URLs; if none set, prompt for global URL.
    """
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")

    for app_id in app_ids:
        try:
            app_id = _safe_app_id(app_id)
            current = _find_first_app_file(app_id, config_dir)
            if current:
                LOGGER.info(f"[INIT] Current artifact for '{app_id}': {current.resolve()}")
                entered = input(
                    f"Enter NEW file path to override '{app_id}' or press ENTER to keep current: "
                ).strip()
                if entered:
                    src = Path(entered)
                    if not src.is_file():
                        LOGGER.warn(f"[INIT] Provided file does not exist: {src}")
                    else:
                        dest = _copy_into_config_dir_with_app_id(src, config_dir, app_id)
                        LOGGER.info(f"[INIT] Replaced artifact: {dest}")
                else:
                    LOGGER.info(f"[INIT] Keeping existing artifact for '{app_id}'.")
            else:
                ensure_app_available_anyext(
                    app_id=app_id,
                    config_dir=config_dir,
                    prompt_if_missing=True,
                )
        except Exception as e:
            LOGGER.warn(f"[INIT][WARN] {app_id}: {e}")

    if ask_store_url:
        urls_map = load_app_urls_map(silent=True)
        changed = False
        for app_id in app_ids:
            current = urls_map.get(app_id, "")
            prompt = f"Enter App Store URL for '{app_id}'"
            if current:
                prompt += f" (ENTER to keep: {current})"
            prompt += ": "
            entered = input(prompt).strip()
            if entered:
                set_app_url(app_id, entered)
                changed = True
                LOGGER.info(f"[INIT] URL set for '{app_id}'.")
        if not changed:
            try:
                current_url = load_appstore_url(store_config_path)
            except FileNotFoundError:
                current_url = ""
            try:
                prompt_and_store_appstore_url(store_config_path, default_url=current_url)
            except Exception as e:
                LOGGER.warn(f"[INIT][WARN] store-url(global): {e}")
