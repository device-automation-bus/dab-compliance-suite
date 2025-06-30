import os
import shutil

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
