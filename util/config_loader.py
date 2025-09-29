"""
This module helps DAB tests find app files and store links (deep links/URLs).
It supports only three app IDs: Sample_App, Sample_App1, Large_App (override in config/apps/app_ids.json, max 3).
App files live in config/apps/ (any extension); use ensure_app_available_anyext(appId, ...) to get a file payload.
Per-app store links live in config/apps/app_urls.json as {appId: url}; a global link lives in config/apps/sample_app.json as {"app_url": url}.
The global link can also come from env (DAB_APPSTORE_URL, APPSTORE_URL, STORE_URL) and is saved to sample_app.json for next runs.
Link precedence is: per-app URL → global URL; if missing, you can enable prompting (prompt_if_missing=True) to ask once and save.
For store installs use build_install_from_app_store_body(appId, ...) → {"appId","url","timeout"} (never puts the URL into "appId").
For local installs the payload looks like {"appId","url","format","timeout"} from ensure_app_available_anyext.
make_app_id_list() returns the current three allowed IDs; all helpers enforce the allow-list.
Errors surface as PayloadConfigError with a short hint; logs use the shared suite LOGGER.
Legacy aliases (ensure_app_available / ensure_apps_available) are kept for compatibility.
No hard-coded store URLs are used; everything is configured via per-app map, global file, or environment.
Example: build_install_from_app_store_body("Sample_App") → {"appId":"Sample_App","url":"<configured>","timeout":60000}.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from logger import LOGGER  # shared suite logger

# -------------------------------------------------------------------------
# Defaults & allow-list config
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


def _write_appstore_url(url: str, config_path: str) -> None:
    """Persist a single key {'app_url': url} to DEFAULT_STORE_JSON."""
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"app_url": (url or "").strip()}, f, indent=2)


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

# -------------------------------------------------------------------------
# Local artifact helpers
# -------------------------------------------------------------------------

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
# Global App Store helpers 
# -------------------------------------------------------------------------

def load_appstore_url(
    config_path: str = DEFAULT_STORE_JSON,
    env_keys: Tuple[str, ...] = ("DAB_APPSTORE_URL", "APPSTORE_URL", "STORE_URL"),
) -> str:
    """
    Return the global App Store URL.

    Resolution (no hard-coded defaults):
      1) If config file exists and contains 'app_url' -> return it (non-empty).
      2) Else, check environment variables in order: env_keys.
         - If found, persist to config and return.
      3) Else, raise FileNotFoundError with guidance.

    Accepts any URL/deeplink scheme (market://, https://, appstore://, etc.).
    """
    # 1) Config file
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            val = (cfg.get("app_url", "") or "").strip()
            if val:
                return val
            else:
                LOGGER.warn(f"[INIT] '{config_path}' present but 'app_url' is empty.")
        except Exception as e:
            LOGGER.warn(f"[INIT] Failed to read '{config_path}': {e}")

    # 2) Environment variables
    for key in env_keys:
        val = (os.getenv(key) or "").strip()
        if val:
            try:
                _write_appstore_url(val, config_path)  # persist for future runs
                LOGGER.info(f"[INIT] Set App Store URL from ${key} and saved to '{config_path}'.")
            except Exception as e:
                LOGGER.warn(f"[INIT] Could not persist App Store URL from ${key}: {e}")
            return val

    # 3) Nothing configured
    raise FileNotFoundError(
        f"App Store URL not configured. Set one of {env_keys} or run with --init to create "
        f"'{config_path}' containing {{\"app_url\": \"<store deep link or URL>\"}}."
    )


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
    prompt_if_missing: bool = False,
) -> str:
    """
    - Returns the configured global App Store URL (file/env).
    - If missing/empty and prompt_if_missing=True: prompt once, persist, and return.
    - If missing/empty and prompt_if_missing=False: raise ValueError.
    """
    try:
        url = (load_appstore_url(config_path) or "").strip()
        if url:
            return url
    except Exception:
        pass

    if prompt_if_missing:
        LOGGER.warn("[INIT] Global App Store URL not configured; prompting now.")
        entered = input("Enter GLOBAL App Store URL to use as fallback for all apps: ").strip()
        if not entered:
            raise ValueError("App Store URL is required.")
        _write_appstore_url(entered, config_path)
        LOGGER.info(f"[INIT] Saved App Store URL to '{config_path}'.")
        return entered

    raise ValueError(
        "App Store URL not configured. Run with --init to set it or export DAB_APPSTORE_URL / APPSTORE_URL."
    )

# -------------------------------------------------------------------------
# Per-app URL map + helpers (restricted to the 3 allowed IDs)
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
    Path(path).parent.mkdir(parents=True, exist_ok=True
    )
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
    # Fallback to global single URL
    url = load_appstore_url(fallback_global)
    if url and url.strip():
        return url
    raise ValueError(
        f"No URL configured for app_id='{sid}'. "
        f"Set per-app in {path} or configure global URL at {fallback_global}."
    )


def get_urls_for_apps(app_ids: List[str], path: str = APP_URLS_JSON, fallback_global: str = DEFAULT_STORE_JSON) -> Dict[str, str]:
    """Return a dict of appId->url for requested app IDs (raises if any missing)."""
    urls: Dict[str, str] = {}
    for a in app_ids:
        sid = _enforce_allowed(a)
        urls[sid] = get_app_url_or_fail(sid, path=path, fallback_global=fallback_global)
    return urls


def get_or_prompt_app_url(
    app_id: str,
    per_app: bool = True,
    prompt_if_missing: bool = False,
    path: str = APP_URLS_JSON,
    store_config_path: str = DEFAULT_STORE_JSON,
) -> str:
    """
    Return the App Store URL for a given allowed app_id.

    Order:
      1) Per-app URL from app_urls.json (if per_app=True).
         - If missing and prompt_if_missing, prompt once, persist via set_app_url, and return.
      2) Global URL from sample_app.json or env via load_appstore_url().
         - If missing and prompt_if_missing, prompt once, persist via _write_appstore_url, and return.
      3) Else raise ValueError with guidance.

    Mirrors the 'ask for apps path' behavior: we prompt only when requested.
    """
    sid = _enforce_allowed(app_id)

    # 1) Per-app
    if per_app:
        mapping = load_app_urls_map(path, silent=True) or {}
        url = (mapping.get(sid, "") or "").strip()
        if url:
            return url
        if prompt_if_missing:
            entered = input(f"Enter App Store URL for '{sid}' (e.g. market://details?id=..., https://...): ").strip()
            if entered:
                set_app_url(sid, entered, path=path)
                return entered
            # fall through to global

    # 2) Global
    try:
        url = (load_appstore_url(store_config_path) or "").strip()
        if url:
            return url
    except Exception:
        # ignore; we may prompt below
        pass

    if prompt_if_missing:
        LOGGER.warn("[INIT] Global App Store URL not configured; prompting now.")
        entered = input("Enter GLOBAL App Store URL to use as fallback for all apps: ").strip()
        if entered:
            _write_appstore_url(entered, store_config_path)
            return entered

    # 3) Nothing configured
    raise ValueError(
        f"No App Store URL configured for '{sid}'. "
        f"Set per-app in {path} or set a global 'app_url' in {store_config_path} "
        f"(or export DAB_APPSTORE_URL / APPSTORE_URL)."
    )

# -------------------------------------------------------------------------
# Install-from-store payload builder
# -------------------------------------------------------------------------

def build_install_from_app_store_body(
    app_id: str = "Sample_App",
    timeout: int = 60000,
    per_app: bool = True,
    prompt_if_missing: bool = False,
) -> Dict[str, object]:
    """
    Build payload for applications/install-from-app-store:
      {"appId": "<ID>", "url": "<store URL/deeplink>", "timeout": 60000}

    - Prompts for missing URLs if prompt_if_missing=True (same UX as asking for app path).
    - Honors the 3 allowed IDs: Sample_App, Sample_App1, Large_App.
    """
    sid = _enforce_allowed(app_id)
    url = get_or_prompt_app_url(
        sid,
        per_app=per_app,
        prompt_if_missing=prompt_if_missing,
        path=APP_URLS_JSON,
        store_config_path=DEFAULT_STORE_JSON,
    )
    return {"appId": sid, "url": url, "timeout": int(timeout)}

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
# Backward-compatibility aliases
# -------------------------------------------------------------------------

def ensure_app_available(*args, **kwargs):
    """Legacy alias → any-extension version (still restricted to 3 allowed apps)."""
    return ensure_app_available_anyext(*args, **kwargs)


def ensure_apps_available(app_ids, **kwargs):
    """Legacy alias for batch ensure; preserves old import sites (max 3 apps)."""
    return ensure_apps_available_anyext(app_ids=app_ids, **kwargs)

# -------------------------------------------------------------------------
# Interactive bootstrap wrapper for --init (fixed to 3 allowed apps)
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

# -------------------------------------------------------------------------
# Negative-case payload
# -------------------------------------------------------------------------

def build_incorrect_format_body(app_id: str | None = None):
    """
    Build a flat 'applications/install' NEGATIVE payload (no fileLocation, no file://)
    using appId='unsupported_format_app' and a .txt artifact.

    Produces:
    {
      "appId": "unsupported_format_app",
      "url": "<absolute>/config/apps/unsupported_format_app.txt",
      "format": "txt",
      "timeout": 60000
    }
    """
    # Always use the dedicated negative-test app id
    resolved_app_id = "unsupported_format_app"

    # Resolve <repo>/config/apps robustly (independent of CWD)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    apps_dir = os.path.join(repo_root, "config", "apps")
    os.makedirs(apps_dir, exist_ok=True)

    txt_path = os.path.join(apps_dir, "unsupported_format_app.txt")

    # Ensure the dummy artifact exists (create if missing)
    if not os.path.exists(txt_path):
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("dummy text file for negative install format test\n")
        except Exception:
            # Best-effort fallback under current working directory
            fallback = os.path.abspath(os.path.join("config", "apps", "unsupported_format_app.txt"))
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            with open(fallback, "w", encoding="utf-8") as f:
                f.write("dummy text file for negative install format test\n")
            txt_path = fallback

    # Flat payload (as required): NO fileLocation, NO file://
    return {
        "appId": resolved_app_id,
        "url": txt_path,
        "format": "txt",
        "timeout": 60000,
    }