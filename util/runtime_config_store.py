import json
import os
from logger import LOGGER

DEFAULT_PATH = os.path.join("config", "runtime_config.json")


def _defaults():
    return {
        "apps": {
            "youtube": "YouTube",
            "netflix": "Netflix",
            "amazon": "PrimeVideo",
            "sample_app": "Sample_App",
            "sample_app1": "Sample_App1",
            "large_app": "Large_App",
            "sample_app_url": "Sample_App_Url",
            "removable_app": "Netflix",
        },
        "va": "GoogleAssistant",
    }


def save_config(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def apply_overrides(cfg, apps_kv_list=None, va=None):
    """
    apps_kv_list: ["youtube=YouTubeTV", "netflix=Netflix"] (repeatable)
    va: "Alexa"
    Returns True if cfg changed.
    """
    changed = False

    if va is not None and str(va).strip():
        va = str(va).strip()
        if cfg.get("va") != va:
            cfg["va"] = va
            changed = True

    if apps_kv_list:
        apps = cfg.get("apps")
        if not isinstance(apps, dict):
            apps = {}
            cfg["apps"] = apps
            changed = True

        for kv in apps_kv_list:
            if not kv or "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k or not v:
                continue
            if apps.get(k) != v:
                apps[k] = v
                changed = True

    return changed


def load_config(path=None):
    path = path or DEFAULT_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        cfg = _defaults()
        save_config(path, cfg)
        LOGGER.ok(f"[CONFIG] Created default runtime config: {path}")
        return path, cfg, True

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        LOGGER.warn(f"[CONFIG] Failed to read {path}: {e}. Recreating defaults.")
        cfg = _defaults()

    if not isinstance(cfg, dict):
        cfg = _defaults()
    if not isinstance(cfg.get("apps"), dict):
        cfg["apps"] = _defaults()["apps"]
    if not cfg.get("va"):
        cfg["va"] = _defaults()["va"]

    # Keep file always valid
    save_config(path, cfg)
    return path, cfg, False


def prompt_edit_config(path=None):
    path, cfg, _ = load_config(path)
    apps = cfg["apps"]

    LOGGER.result(f"[CONFIG] Editor: {path}")
    LOGGER.result(f"[CONFIG] Current va={cfg.get('va')}")
    LOGGER.result(f"[CONFIG] App keys: {', '.join(sorted(apps.keys()))}")

    va_in = input(f"va [{cfg.get('va')}]: ").strip()
    if va_in:
        cfg["va"] = va_in
        LOGGER.result(f"[CONFIG] Updated va={cfg['va']}")

    LOGGER.result("[CONFIG] Update apps: press Enter to keep.")
    for k in sorted(apps.keys()):
        v_in = input(f"apps.{k} [{apps[k]}]: ").strip()
        if v_in:
            apps[k] = v_in
            LOGGER.result(f"[CONFIG] Updated apps.{k}={v_in}")

    cfg["apps"] = apps
    save_config(path, cfg)

    LOGGER.ok(f"[CONFIG] Saved. va={cfg.get('va')}, apps={len(cfg.get('apps', {}))}")
    return path
