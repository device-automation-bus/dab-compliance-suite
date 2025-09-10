# util/output_image_handler.py
from __future__ import annotations
from typing import Any, Dict, Optional, Union
import os, json, base64, re, datetime as dt, sys

# ----------------- helpers -----------------

def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")

def _safe(s: Optional[str]) -> str:
    return "".join(c if (c.isalnum() or c in "-_.:@") else "_" for c in (s or "device"))

def _normalize_b64(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return s

def _from_data_uri(v: str) -> str:
    # Accept "data:image/png;base64,AAAA..." → return "AAAA..."
    if isinstance(v, str) and v.startswith("data:image/"):
        i = v.find(",")
        if i != -1:
            return v[i + 1 :]
    return v

def _extract_png_bytes(resp: Union[Dict[str, Any], str]) -> bytes:
    """Extract base64 image bytes from response['outputImage'] or raise."""
    if isinstance(resp, str):
        resp = json.loads(resp)
    if not isinstance(resp, dict):
        raise ValueError("response must be a dict or JSON string")

    raw = resp.get("outputImage")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("response['outputImage'] missing or empty")

    b64 = _normalize_b64(_from_data_uri(raw))
    try:
        return base64.b64decode(b64, validate=False)
    except Exception as e:
        raise ValueError(f"base64 decode failed: {e}")

def _dir_of(path_like: Optional[str]) -> Optional[str]:
    if not path_like:
        return None
    # If it's a JSON file path, use its directory; if it's a dir, use it
    if path_like.lower().endswith(".json"):
        return os.path.dirname(path_like) or "."
    return path_like

def _detect_results_root(fallback_root: Optional[str]) -> str:
    """
    Decide where the results.json lives WITHOUT changing other files:
    1) DAB_RESULTS_JSON env -> dirname
    2) CLI args: -o/--output/--output-file/--output_path/--output-path
    3) Provided fallback_root (dir or file path)
    4) Default './test_result'
    """
    # 1) Env var (if main/tester set it)
    env_json = os.environ.get("DAB_RESULTS_JSON")
    if env_json:
        return os.path.dirname(env_json) or "."

    # 2) CLI flags (works even if nothing else was changed)
    argv = sys.argv or []
    keys = ("-o", "--output", "--output-file", "--output_path", "--output-path")
    for i, arg in enumerate(argv):
        if arg in keys and i + 1 < len(argv):
            candidate = os.path.abspath(os.path.expanduser(argv[i + 1]))
            return os.path.dirname(candidate) if candidate.lower().endswith(".json") else candidate

    # 3) Fallback provided by caller (may be dir or json path)
    d = _dir_of(fallback_root) if isinstance(fallback_root, str) else None
    if d:
        return d

    # 4) Final fallback
    return "./test_result"

def _save_png_bytes(png: bytes, results_root: str, device_id: Optional[str], prefix: Optional[str]) -> str:
    images_dir = os.path.join(results_root or ".", "images")
    os.makedirs(images_dir, exist_ok=True)
    out_path = os.path.join(
        images_dir,
        f"{_safe(device_id)}-{_safe(prefix or 'output_image')}-{_ts()}.png",
    )
    with open(out_path, "wb") as f:
        f.write(png)
    return os.path.abspath(out_path)

# ----------------- public APIs -----------------

def save_output_image(
    *,
    response: Union[Dict[str, Any], str],
    device_id: Optional[str],
    results_root: Optional[str] = "./test_result",
    filename_prefix: Optional[str] = "output_image",
) -> str:
    """
    Save PNG to <results_root>/images/<device>-<prefix>-<ts>.png.
    Returns the absolute file path.

    Called by dab/output.py with kwargs:
        save_output_image(response=..., device_id=..., results_root=..., filename_prefix=...)
    This function *auto-detects* the real results JSON directory if possible
    (env/argv) so images land next to the user's -o path without changing other code.
    """
    png = _extract_png_bytes(response)
    root = _detect_results_root(results_root)
    return _save_png_bytes(png, root, device_id, filename_prefix)

def handle_output_image_response(
    resp: Union[Dict[str, Any], str],
    results_json_path: str,
    device_id: Optional[str],
) -> str:
    """
    Back-compat wrapper used by results writer (heavy-topic processing).
    Uses the *exact* results JSON path provided by the writer.
    """
    try:
        png = _extract_png_bytes(resp)
        root = _dir_of(results_json_path) or "."
        path = _save_png_bytes(png, root, device_id, "output_image")
        return f"[INFO] Image saved: {path}"
    except Exception as e:
        return f"[WARN] Image save failed: {e}"
