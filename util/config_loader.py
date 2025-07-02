import os
import shutil
import json

def prompt_and_store_appstore_url(config_path="config/apps/sample_app.json"):
    """
    Prompts user for app store URL and saves it to config/apps/sample_app.json
    """
    appstore_url = input("Enter App Store URL for installFromAppstore test: ").strip()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"app_url": appstore_url}, f, indent=2)

def load_appstore_url(config_path="config/apps/sample_app.json") -> str:
    """
    Loads appId (App Store URL) from config/apps/sample_app.json
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"App config not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("app_url", "")

def get_or_prompt_appstore_url(config_path="config/apps/sample_app.json") -> str:
    """
    Loads App Store URL if available, otherwise prompts user and saves it.
    """
    try:
        url = load_appstore_url(config_path)
        if not url.strip():
            raise ValueError("Empty URL")
        return url
    except (FileNotFoundError, ValueError):
        prompt_and_store_appstore_url(config_path)
        return load_appstore_url(config_path)

def ensure_app_available(app_name_prefix: str = "Sample_App", config_dir="config/apps"):
    """
    Ensures 'Sample_App.xxx' exists in config_dir.
    If not, prompts user to provide a file path and copies it as 'Sample_App.<original_extension>'.
    
    Returns:
        str: Absolute path to 'Sample_App.xxx' file.
    """
    # Check if file already exists
    for fname in os.listdir(config_dir):
        if fname.startswith(app_name_prefix):
            return os.path.abspath(os.path.join(config_dir, fname))

    # Prompt user for file path
    print(f"[!] App '{app_name_prefix}' not found in '{config_dir}'")
    user_path = input("Please provide full path to the app file (e.g., .apk, .apks): ").strip()

    if not os.path.isfile(user_path):
        raise FileNotFoundError(f"Provided file does not exist: {user_path}")

    # Extract extension and copy as 'Sample_App.xxx'
    _, ext = os.path.splitext(user_path)
    dest_path = os.path.join(config_dir, f"{app_name_prefix}{ext}")
    shutil.copy(user_path, dest_path)

    print(f"App copied to: {dest_path}")
    return os.path.abspath(dest_path)
