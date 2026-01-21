import os
from util.runtime_config_store import load_config

_path, config, _created = load_config(os.environ.get("DAB_CONFIG_JSON"))
apps = config["apps"]
va = config["va"]