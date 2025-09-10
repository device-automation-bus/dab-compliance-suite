"""
Helpers for resolving local app artifacts and App Store URLs for DAB tests.

This version ENFORCES exactly three allowed apps and URLs:
  - "Sample_App"
  - "Sample_App1"
  - "Large_App"

Minimal-impact changes:
- Introduces a fixed allow‑list; all public helpers validate app IDs against it.
- Keeps existing APIs and behaviors otherwise.
- Still supports per‑app URL map at config/apps/app_urls.json (limited to the 3 IDs).
- Optionally lets you override *which* three via config/apps/app_ids.json, but we
  always cap to 3. (Edit that file only if you really need to swap an ID.)

Stable APIs preserved:
- ensure_app_available_anyext(app_id="Sample_App", config_dir=..., timeout=..., prompt_if_missing=False)
- ensure_apps_available_anyext(app_ids=[...], ...)
- make_app_id_list(count=3, base_name="Sample_App")  # base_name ignored; returns the 3 allowed
- init_sample_apps(count=3, base_name="Sample_App", ...)  # count/base ignored; manages the 3 allowed
- get_sample_apps_payloads(...), get_apps_payloads(...)
- init_interactive_setup(app_ids=("Sample_App",), ...)  # legacy wrapper now manages the 3 allowed
- ensure_app_available(...), ensure_apps_available(...)  # legacy aliases

URL helpers preserved (restricted to the 3 IDs):
- set_app_url(app_id, url)
- get_app_url_or_fail(app_id)
- get_urls_for_apps([ids...]) -> {id:url}
- load_app_urls_map()/save_app_urls_map()

Misc preserved:
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
# Defaults & NEW allow-list config
# -------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = "config/apps"
DEFAULT_STORE_JSON = f"{DEFAULT_CONFIG_DIR}/sample_app.json"  # legacy single URL
APP_URLS_JSON = f"{DEFAULT_CONFIG_DIR}/app_urls.json"         # per-app URL map
APP_IDS_JSON = f"{DEFAULT_CONFIG_DIR}/app_ids.json"           # optional override list (<=3)

# Fixed three app IDs (edit APP_IDS_JSON to override, still capped at 3)
ALLOWED_APP_IDS_DEFAULT: List[str] = [
    "Sample_App",
    "Sample_App1",
    "Large_App"
]

# -------------------------------------------------------------------------
# Small utilities
# -------------------------------------------------------------------------

def _safe_app_id(app_id: str) -> str:
    """Normalize appId to a safe filename stem (letters, digits, _ - . only)."""
    s = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in (app_id or "app"))
    return s or "app"


def _load_allowed_ids(path: str = APP_IDS_JSON, max_count: int = 3, silent: bool = True) -> List[str]:
    """Load up to 3 allowed app IDs from JSON array; fall back to defaults.

    JSON format (optional): ["Sample_App", "Sample_App1", "Large_App"]
    Regardless of file contents, we always cap to 3 entries.
    """
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                ids = []
                for x in data:
                    if not isinstance(x, str):
                        continue
                    sid = _safe_app_id(x)
                    if sid and sid not in ids:
                        ids.append(sid)
                if ids:
                    return ids[:max_count]
    except Exception as e:
        if not silent:
            LOGGER.warn(f"[INIT] Failed to load app_ids from '{path}': {e}")
    return ALLOWED_APP_IDS_DEFAULT[:max_count]


def _allowed_ids() -> List[str]:
    """Return the current 3 allowed app IDs (from JSON if present, else defaults)."""
    ids = [i for i in _load_allowed_ids() if i]
    if not ids:
        ids = ["Sample_App", "Sample_App1", "Large_App"]
    return ids[:3]
 
def make_app_id_list(count=3, base_name="Sample_App"):
    return [base_name if i == 0 else f"{base_name}{i}" for i in range(count)]

def _enforce_allowed(app_id: str) -> str:
    """Raise if app_id is not in the allowed list; return normalized safe id otherwise."""
    sid = _safe_app_id(app_id)
    allowed = _allowed_ids()
    if sid not in allowed:
        raise ValueError(
            f"Unsupported app_id='{app_id}'. Allowed: {allowed}. "
            f"(Edit {APP_IDS_JSON} only if you must swap IDs; still limited to 3.)"
        )
    return sid


def _find_first_app_file(app_id: str, config_dir: str) -> Optional[Path]:
    """
    Find an artifact in config_dir for the given app_id (case-insensitive):
      - exact filename without extension, OR
      - any extension starting with '<app_id>.'
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
    """Build a standard install payload for applications/install (any extension)."""
    ext = file_path.suffix[1:].lower() if file_path.suffix else "bin"
    return {
        "appId": app_id,
        "url": str(file_path),  # absolute filesystem path (no file://)
        "format": ext or "bin",
        "timeout": int(timeout),
    }

# -------------------------------------------------------------------------
# Core ensure (ANY extension) — now validates allowed IDs
# -------------------------------------------------------------------------

def ensure_app_available_anyext(
    app_id: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
    prompt_if_missing: bool = False,
) -> Dict[str, object]:
    """
    Ensure an app artifact exists under config_dir with ANY extension.
    Only the 3 allowed app IDs are supported.

    Strategy:
      - Looks for '<app_id>' or '<app_id>.<ext>'.
      - If missing and prompt_if_missing=False -> FileNotFoundError.
      - If missing and prompt_if_missing=True  -> prompt once, copy into config, continue.

    Returns: payload usable by `applications/install`.
    """
    app_id = _enforce_allowed(app_id)
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
    """Ensure multiple apps (max 3) are available. Returns payloads in given order."""
    allowed = _allowed_ids()
    ids: List[str] = []
    for a in (app_ids or []):
        sid = _enforce_allowed(a)
        ids.append(sid)
    if len(ids) > 3:
        LOGGER.warn(f"[INIT] More than 3 app IDs requested; truncating to: {allowed}")
        ids = allowed
    return [
        ensure_app_available_anyext(
            app_id=a,
            config_dir=config_dir,
            timeout=timeout,
            prompt_if_missing=prompt_if_missing,
        )
        for a in ids
    ]

# -------------------------------------------------------------------------
# Uniform app helpers — now fixed to the allow-list
# -------------------------------------------------------------------------

def make_app_id_list(count: int = 3, base_name: str = "Sample_App") -> List[str]:
    """
    Return the 3 allowed app IDs. Parameters kept for backward compatibility.
    - `count` and `base_name` are ignored; we always return up to 3 allowed IDs.
    - Edit config/apps/app_ids.json to swap IDs if you must (still limited to 3).
    """
    ids = _allowed_ids()
    return ids[:3]


def init_sample_apps(
    count: int = 3,
    base_name: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """Interactive init strictly for the 3 allowed apps (artifacts + optional URLs)."""
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    app_ids = make_app_id_list()  # fixed 3

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

    # Optional per-app URL prompts (only for the 3 allowed IDs)
    if ask_store_url:
        LOGGER.info("[INIT] Configure App Store URLs (per app). Leave blank to keep/skip.")
        urls_map = load_app_urls_map(silent=True)
        for app_id in app_ids:
            current_url = urls_map.get(app_id, "")
            prompt = f"Enter App Store URL for '{app_id}'"
            if current_url:
                prompt += f" (ENTER to keep: {current_url})"
            prompt += ": "
            entered = input(prompt).strip()
            if entered:
                set_app_url(app_id, entered)
                LOGGER.info(f"[INIT] URL set for '{app_id}'.")

# -------------------------------------------------------------------------
# Batch payload builders (restricted to the 3 allowed IDs)
# -------------------------------------------------------------------------

def get_sample_apps_payloads(
    count: int = 3,
    base_name: str = "Sample_App",
    config_dir: str = DEFAULT_CONFIG_DIR,
    timeout: int = 60000,
) -> List[Dict[str, object]]:
    app_ids = make_app_id_list()
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
        app_ids=[_enforce_allowed(a) for a in app_ids],
        config_dir=config_dir,
        timeout=timeout,
        prompt_if_missing=False,
    )

# -------------------------------------------------------------------------
# Global App Store helpers (unchanged)
# -------------------------------------------------------------------------

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

def get_or_prompt_appstore_url(config_path: str = DEFAULT_STORE_JSON) -> str:
    try:
        return get_appstore_url_or_fail(config_path)
    except Exception:
        url = input("Enter App Store URL (e.g. https://...): ").strip()
        if not url:
            raise ValueError("App Store URL is required.")
        return url

def get_or_prompt_appstore_url(
    config_path: str = DEFAULT_STORE_JSON,
    prompt_if_missing: bool = False,
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
# Per-app URL map (restricted to the 3 allowed IDs)
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
    """Set per-app URL in the map (overwrites existing value). Limited to allowed IDs."""
    sid = _enforce_allowed(app_id)
    mapping = load_app_urls_map(path, silent=True)
    mapping[sid] = (url or "").strip()
    # Keep only allowed keys and limit to 3 entries
    allowed = set(_allowed_ids())
    mapping = {k: v for k, v in mapping.items() if k in allowed}
    save_app_urls_map(mapping, path)


def get_app_url_or_fail(app_id: str, path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> str:
    """Get per-app URL; if missing, fall back to global; else raise with guidance."""
    sid = _enforce_allowed(app_id)
    mapping = load_app_urls_map(path, silent=True)
    url = (mapping.get(sid, "") or "").strip()
    if url:
        return url
    # Fallback to legacy single URL
    url = load_appstore_url(fallback_global)
    if url and url.strip():
        return url
    raise ValueError(
        f"No URL configured for app_id='{sid}'. "
        f"Run --init to set per-app URLs or configure global URL at {fallback_global}."
    )


def get_urls_for_apps(app_ids: List[str], path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> Dict[str, str]:
    """Return a dict of appId->url for requested app IDs (raises if any missing)."""
    urls: Dict[str, str] = {}
    for a in app_ids:
        sid = _enforce_allowed(a)
        urls[sid] = get_app_url_or_fail(sid, path=path, fallback_global=fallback_global)
    return urls

# -------------------------------------------------------------------------
# Payload builder & error (unchanged)
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
# Backward-compatibility aliases (unchanged API, new restrictions apply)
# -------------------------------------------------------------------------

def ensure_app_available(*args, **kwargs):
    """Legacy alias → any-extension version (still restricted to 3 allowed apps)."""
    return ensure_app_available_anyext(*args, **kwargs)


def ensure_apps_available(app_ids, **kwargs):
    """Legacy alias for batch ensure; preserves old import sites (max 3 apps)."""
    return ensure_apps_available_anyext(app_ids=app_ids, **kwargs)

# -------------------------------------------------------------------------
# Interactive bootstrap wrapper for --init (now fixed to 3 allowed apps)
# -------------------------------------------------------------------------

def init_interactive_setup(
    app_ids: tuple[str, ...] | None = None,
    config_dir: str = DEFAULT_CONFIG_DIR,
    ask_store_url: bool = True,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> None:
    """
    Interactive bootstrap for --init, restricted to exactly 3 allowed apps.

    Notes:
    - Ignores any provided `app_ids` beyond validation; always manages the 3 allowed
      from `_allowed_ids()` to keep behavior consistent across runs.
    - The earlier base-name / count prompts are removed by design.
    """
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    LOGGER.info(f"[INIT] Preparing in: {Path(config_dir).resolve()}")

    # Always use the allowed three
    ids = make_app_id_list()

    # Manage each app: Keep / Replace / Delete, or add if missing.
    for app_id in ids:
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

    # Optional per-app URLs (only 3, same names)
    if ask_store_url:
        try:
            urls_map = load_app_urls_map(silent=True)
        except Exception:
            urls_map = {}
        for app_id in ids:
            current = urls_map.get(app_id, "")
            prompt = f"Enter App Store URL for '{app_id}'"
            if current:
                prompt += f" (ENTER to keep: {current})"
            prompt += ": "
            entered = input(prompt).strip()
            if entered:
                set_app_url(app_id, entered)
                LOGGER.info(f"[INIT] URL set for '{app_id}'.")
