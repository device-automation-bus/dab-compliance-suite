"""
Helpers for resolving local app artifacts and App Store URLs for DAB tests.

Highlights:
- Accept ANY file extension for app artifacts (no hardcoding).
- Friendly interactive init for N apps; if a FILE PATH is pasted at the base-name prompt,
  it is auto-used for the FIRST app and the base stays 'Sample_App'.
- Non-interactive payload builders for tests.
- Per-app URL map (appId -> url) at config/apps/app_urls.json.
- Backward-compatible single legacy URL (config/apps/sample_app.json).

Stable APIs:
- ensure_app_available_anyext(app_id="Sample_App", config_dir=..., timeout=..., prompt_if_missing=False)
- ensure_apps_available_anyext(app_ids=[...], ...)
- make_app_id_list(count=3, base_name="Sample_App")
- init_sample_apps(count=3, base_name="Sample_App", config_dir=..., ask_store_url=True, store_config_path=...)
- get_sample_apps_payloads(count=3, base_name="Sample_App", ...)
- get_apps_payloads(app_ids=[...], ...)
- init_interactive_setup(app_ids=("Sample_App",), ...)        # legacy wrapper
- ensure_app_available(...) & ensure_apps_available(...)      # legacy aliases

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
from typing import Dict, List, Optional

from logger import LOGGER  # shared suite logger

# -------------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = "config/apps"
DEFAULT_STORE_JSON = f"{DEFAULT_CONFIG_DIR}/sample_app.json"  # legacy single URL
APP_URLS_JSON = f"{DEFAULT_CONFIG_DIR}/app_urls.json"         # per-app URL map

# -------------------------------------------------------------------------
# Small utilities
# -------------------------------------------------------------------------

def _safe_app_id(app_id: str) -> str:
    """Normalize appId to a safe filename stem (letters, digits, _ - . only)."""
    s = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in (app_id or "app"))
    return s or "app"


def _find_first_app_file(app_id: str, config_dir: str) -> Optional[Path]:
    """
    Find an artifact in config_dir:
      - exact filename without extension, OR
      - any extension starting with '<app_id>.' (case-insensitive).
    """
    root = Path(config_dir)
    if not root.exists():
        return None

    target = app_id.lower()

    # Exact match (no extension)
    for entry in root.iterdir():
        if entry.is_file() and entry.name.lower() == target:
            return entry.resolve()

    # With extension
    prefix = target + "."
    for entry in sorted(root.iterdir(), key=lambda e: e.name.lower()):
        if entry.is_file() and entry.name.lower().startswith(prefix):
            return entry.resolve()

    return None


def _copy_into_config_dir(src: Path, config_dir: str, app_id: str) -> Path:
    """Copy src into config_dir as '<app_id>.<original_ext>' (or '<app_id>' if none)."""
    dest_dir = Path(config_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix  # may be empty
    dest = dest_dir / f"{app_id}{suffix}"
    shutil.copy2(src, dest)
    return dest.resolve()


def _remove_app_files(app_id: str, config_dir: str) -> int:
    """Delete files matching '<app_id>' or '<app_id>.*' in config_dir. Returns count removed."""
    root = Path(config_dir)
    if not root.exists():
        return 0
    target = app_id.lower()
    removed = 0
    for entry in list(root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name.lower()
        if name == target or name.startswith(target + "."):
            try:
                entry.unlink()
                removed += 1
            except Exception as e:
                LOGGER.warn(f"[INIT] Failed to delete '{entry}': {e}")
    return removed


def _to_install_payload(app_id: str, file_path: Path, timeout: int = 60000) -> Dict[str, object]:
    """Build a standard install payload for applications/install."""
    ext = file_path.suffix[1:].lower() if file_path.suffix else "bin"
    return {
        "appId": app_id,
        "url": str(file_path),     # absolute filesystem path (no file://)
        "format": ext or "bin",
        "timeout": int(timeout),
    }

# -------------------------------------------------------------------------
# Core ensure (ANY extension)
# -------------------------------------------------------------------------

def ensure_app_available_anyext(
    app_id: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
    prompt_if_missing: bool = False,
) -> Dict[str, object]:
    """
    Ensure an app artifact exists under config_dir with ANY extension.

    Strategy:
      - Looks for '<app_id>' or '<app_id>.<ext>'.
      - If missing and prompt_if_missing=False -> FileNotFoundError.
      - If missing and prompt_if_missing=True  -> prompt once, copy into config, continue.

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
        user_path = input(
            f"Full path to the app file (any extension) to copy as "
            f"'{Path(config_dir) / (app_id)}.<ext>': "
        ).strip()
        src = Path(user_path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"Provided file does not exist: {src}")
        found = _copy_into_config_dir(src, config_dir, app_id)
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
            app_id=_safe_app_id(a),
            config_dir=config_dir,
            timeout=timeout,
            prompt_if_missing=prompt_if_missing,
        )
        for a in app_ids
    ]

# -------------------------------------------------------------------------
# Uniform N-app helpers
# -------------------------------------------------------------------------

def make_app_id_list(count: int = 3, base_name: str = "Sample_App") -> List[str]:
    """
    Build ['Sample_App', 'Sample_App1', 'Sample_App2', ...] with cleaned ids.
    Hardening: if base_name looks like a *path* or has a *file suffix*, fall back to 'Sample_App'.
    """
    looks_like_path = False
    if base_name:
        if ("/" in base_name) or ("\\" in base_name) or Path(base_name).suffix:
            looks_like_path = True
    raw_base = "Sample_App" if looks_like_path else (base_name or "Sample_App")
    base = (raw_base[:1].upper() + raw_base[1:])
    return [_safe_app_id(base if i == 0 else f"{base}{i}") for i in range(count)]


def init_sample_apps(
    count: int = 3,
    base_name: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Interactive init for N sample apps.

    For each appId in make_app_id_list(...):
      - If artifact exists: allow Keep/Replace/Delete.
      - If missing: prompt once for a file and copy it.
    """
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    app_ids = make_app_id_list(count=count, base_name=base_name)

    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")

    for app_id in app_ids:
        try:
            current = _find_first_app_file(app_id, config_dir)
            if current:
                LOGGER.info(f"[INIT] Current artifact for '{app_id}': {current.resolve()}")
                choice = input(
                    f"Keep (K) / Replace (R) / Delete (D) this app under '{config_dir}' "
                    f"as '{app_id}.*'? [K]: "
                ).strip().lower() or "k"
                if choice.startswith("r"):
                    new_path = input(
                        f"Full path to the NEW file to store as "
                        f"'{Path(config_dir) / (app_id + '.<ext>')}' (any extension): "
                    ).strip()
                    src = Path(new_path).expanduser()
                    if src.is_file():
                        dest = _copy_into_config_dir(src, config_dir, app_id)
                        LOGGER.info(f"[INIT] Replaced artifact: {dest}")
                    else:
                        LOGGER.warn("[INIT] Provided path not a file; kept existing.")
                elif choice.startswith("d"):
                    removed = _remove_app_files(app_id, config_dir)
                    LOGGER.info(f"[INIT] Deleted {removed} file(s) for '{app_id}'.")
                else:
                    LOGGER.info(f"[INIT] Kept '{app_id}'.")
            else:
                LOGGER.info(
                    f"[INIT] '{app_id}' has no artifact. You will be prompted to select a file, "
                    f"which will be stored as '{Path(config_dir) / (app_id + '.<ext>')}'."
                )
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
            current_url = urls_map.get(app_id, "")
            prompt = f"Enter App Store URL for '{app_id}'"
            if current_url:
                prompt += f" (ENTER to keep: {current_url})"
            prompt += ": "
            entered = input(prompt).strip()
            if entered:
                set_app_url(app_id, entered)
                changed = True
                LOGGER.info(f"[INIT] URL set for '{app_id}'.")
        if not changed:
            LOGGER.info("[INIT] No per-app URL changes.")
        # Fallback: if none set per-app, offer legacy single URL
        if not any(load_app_urls_map(silent=True).values()):
            try:
                current = load_appstore_url(store_config_path)
            except FileNotFoundError:
                current = ""

# -------------------------------------------------------------------------
# Batch payload builders
# -------------------------------------------------------------------------

def get_sample_apps_payloads(
    count: int = 3,
    base_name: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
) -> List[Dict[str, object]]:
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
    return ensure_apps_available_anyext(
        app_ids=[_safe_app_id(a) for a in app_ids],
        config_dir=config_dir,
        timeout=timeout,
        prompt_if_missing=False,
    )


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
    mapping = load_app_urls_map(path, silent=True)
    mapping[_safe_app_id(app_id)] = (url or "").strip()
    save_app_urls_map(mapping, path)


def get_app_url_or_fail(app_id: str, path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> str:
    """Get per-app URL; if missing, fall back to global; else raise with guidance."""
    mapping = load_app_urls_map(path, silent=True)
    url = (mapping.get(_safe_app_id(app_id), "") or "").strip()
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
# Interactive bootstrap wrapper for --init
# -------------------------------------------------------------------------

def init_interactive_setup(
    app_ids: tuple[str, ...] | None = None,
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Interactive bootstrap for --init.

    FIXED: If the user mistakenly pastes a FILE PATH at the "Base name" prompt,
    we do NOT turn that into an app id. Instead:
      - Use 'Sample_App', 'Sample_App1', ... as ids.
      - Auto-use that file for the first app (no second prompt).
    """
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")

    # If explicit ids provided (legacy path), just manage those.
    if app_ids:
        ids = [_safe_app_id(a) for a in app_ids]
        first_file_hint = None
    else:
        # How many apps
        raw_n = input("How many sample apps to configure? [3]: ").strip()
        try:
            n = int(raw_n) if raw_n else 3
        except ValueError:
            n = 3

        # Base name (may be misused as a path!)
        base_in = input("Base name for apps [Sample_App]: ").strip()
        first_file_hint: Optional[Path] = None

        # Detect if user pasted a file path here; handle gracefully.
        looks_like_path = False
        if base_in:
            if ("/" in base_in) or ("\\" in base_in) or Path(base_in).suffix:
                looks_like_path = True

        if looks_like_path:
            maybe_file = Path(base_in).expanduser().resolve()
            if maybe_file.exists() and maybe_file.is_file():
                first_file_hint = maybe_file
                LOGGER.info("[INIT] Detected file path in base-name prompt; will use it for the FIRST app.")
            else:
                LOGGER.warn(f"[INIT] Provided base-name looks like a path, but not a file: {maybe_file}")
            base = "Sample_App"  # always fall back to a safe base
        else:
            base = base_in or "Sample_App"

        ids = make_app_id_list(count=n, base_name=base)

    # Manage each app: Keep / Replace / Delete, or add if missing.
    for idx, app_id in enumerate(ids):
        try:
            existing = _find_first_app_file(app_id, config_dir)
            if existing:
                LOGGER.info(f"[INIT] Current artifact for '{app_id}': {existing}")
                choice = input(
                    f"Keep (K) / Replace (R) / Delete (D) this app under '{config_dir}' "
                    f"as '{app_id}.*'? [K]: "
                ).strip().lower() or "k"
                if choice.startswith("r"):
                    new_path = input(
                        f"Full path to the NEW file to store as "
                        f"'{Path(config_dir) / (app_id + '.<ext>')}' (any extension): "
                    ).strip()
                    src = Path(new_path).expanduser()
                    if src.is_file():
                        dest = _copy_into_config_dir(src, config_dir, app_id)
                        LOGGER.info(f"[INIT] Replaced: {dest}")
                    else:
                        LOGGER.warn("[INIT] Provided path not a file; kept existing.")
                elif choice.startswith("d"):
                    removed = _remove_app_files(app_id, config_dir)
                    LOGGER.info(f"[INIT] Deleted {removed} file(s) for '{app_id}'.")
                else:
                    LOGGER.info(f"[INIT] Kept '{app_id}'.")
            else:
                # If a file path was provided at base-name prompt, use it for the FIRST app and skip prompting.
                if idx == 0:
                    first_hint = locals().get("first_file_hint", None)
                    if first_hint and isinstance(first_hint, Path) and first_hint.exists() and first_hint.is_file():
                        dest = _copy_into_config_dir(first_hint, config_dir, app_id)
                        LOGGER.info(f"[INIT] Added artifact for '{app_id}': {dest}")
                        continue
                # Normal add flow (single prompt) — make the destination explicit to the user
                LOGGER.info(
                    f"[INIT] '{app_id}' has no artifact. You will be prompted to select a file, "
                    f"which will be stored as '{Path(config_dir) / (app_id + '.<ext>')}'."
                )
                ensure_app_available_anyext(
                    app_id=app_id,
                    config_dir=config_dir,
                    prompt_if_missing=True,
                )
        except Exception as e:
            LOGGER.warn(f"[INIT][WARN] {app_id}: {e}")

    # Optional per-app URLs, then legacy single URL if none set
    if ask_store_url:
        try:
            urls_map = load_app_urls_map(silent=True)
        except Exception:
            urls_map = {}
        changed = False
        for app_id in ids:
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
