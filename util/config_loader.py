import os
import shutil
import json
from pathlib import Path
from typing import Dict, Tuple

def _find_app_file(app_name_prefix: str, config_dir: str, exts=(".apk", ".apks")) -> Tuple[Path, str]:
    """
    Look for files like 'Sample_App.apk' (or .apks) in config_dir.
    Returns (path, ext_without_dot) or (None, '') if not found.
    """
    p = Path(config_dir)
    if not p.exists():
        return None, ""
    for entry in p.iterdir():
        if entry.is_file() and entry.name.startswith(app_name_prefix):
            ext = entry.suffix.lower()
            if not exts or ext in exts:
                return entry.resolve(), ext.lstrip(".")
    return None, ""

def ensure_app_available(
    app_id: str = "Sample_App",
    config_dir: str = "config/apps",
    timeout: int = 60000,
    allowed_exts = (".apk", ".apks"),
) -> Dict[str, object]:
    """
    Ensures an app file exists in `config_dir` with name like 'Sample_App.<ext>'.
    If missing, prompts for a source file path and copies it into `config_dir`.

    Returns a payload dict (note: 'url' is a plain absolute file path, not a file:// URI):
      { "appId": "<app_id>", "url": "/abs/path/Sample_App.<ext>", "format": "<ext>", "timeout": <timeout> }
    """
    os.makedirs(config_dir, exist_ok=True)

    # 1) Try to find an existing file for this app_id
    found_path, fmt = _find_app_file(app_id, config_dir, allowed_exts)
    if not found_path:
        # 2) Prompt user for a source file and copy it into place
        print(f"[!] App '{app_id}' not found in '{config_dir}'")
        user_path = input("Please provide full path to the app file (e.g., .apk, .apks): ").strip()
        src = Path(user_path)
        if not src.is_file():
            raise FileNotFoundError(f"Provided file does not exist: {src}")
        ext = src.suffix.lower()
        if allowed_exts and ext not in allowed_exts:
            raise ValueError(f"Unsupported app format '{ext}'. Allowed: {', '.join(allowed_exts)}")

        dest = Path(config_dir) / f"{app_id}{ext}"
        shutil.copy2(src, dest)
        print(f"[INFO] App copied to: {dest}")
        found_path, fmt = dest.resolve(), ext.lstrip(".")

    # 3) Build a plain absolute path string (e.g., /Users/.../Sample_App.apk)
    file_path = str(found_path)  # CHANGED: previously used found_path.as_uri()

    # 4) Return the ready-to-use payload
    payload = {
        "appId": app_id,
        "url": file_path, 
        "format": fmt or found_path.suffix.lstrip(".").lower(),
        "timeout": int(timeout),
    }
    return payload

# --- (Optional) Keep your existing App Store URL helpers if you still need them) ---
def prompt_and_store_appstore_url(config_path="config/apps/sample_app.json"):
    appstore_url = input("Enter App Store URL for installFromAppstore test: ").strip()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"app_url": appstore_url}, f, indent=2)

def load_appstore_url(config_path="config/apps/sample_app.json") -> str:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"App config not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("app_url", "")

def get_or_prompt_appstore_url(config_path="config/apps/sample_app.json") -> str:
    try:
        url = load_appstore_url(config_path)
        if not url.strip():
            raise ValueError("Empty URL")
        return url
    except (FileNotFoundError, ValueError):
        prompt_and_store_appstore_url(config_path)
        return load_appstore_url(config_path)
