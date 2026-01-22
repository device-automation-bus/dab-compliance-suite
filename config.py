# config.py
# Default application identifiers and voice assistant used by tests and runners.
# Values can be overridden at runtime by calling init_runtime_config(path).

from util.runtime_config_store import load_config

apps = dict(
    youtube="YouTube",
    netflix="Netflix",
    amazon="PrimeVideo",
    sample_app="Sample_App",
    sample_app1="Sample_App1",
    large_app="Large_App",
    sample_app_url="Sample_App_Url",
    removable_app="Netflix",
)

va = "GoogleAssistant"

_RUNTIME_LOADED = False


def init_runtime_config(path=None):
    """
    Loads runtime overrides (apps/va) from the runtime config store.

    Call this once from main.py after argument parsing.
    If runtime config is missing or partial, defaults above remain in effect.
    """
    global apps, va, _RUNTIME_LOADED
    if _RUNTIME_LOADED:
        return

    _path, cfg, _created = load_config(path)

    if isinstance(cfg, dict):
        if isinstance(cfg.get("apps"), dict):
            apps = cfg["apps"]
        if cfg.get("va"):
            va = cfg["va"]

    _RUNTIME_LOADED = True
