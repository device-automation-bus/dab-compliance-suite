# dab/output.py
from schema import dab_response_validator
from time import sleep
from dab_tester import YesNoQuestion, Default_Validations
from util.output_image_handler import save_output_image
from logger import LOGGER  # ← add this import
import jsons, os

def image(test_result, durationInMs=0, expectedLatencyMs=0):
    # 1) Schema validation
    try:
        dab_response_validator.validate_output_image_response_schema(test_result.response)
    except Exception as error:
        LOGGER.warn(f"Schema error: {error}")
        return False

    # 2) Parse response
    try:
        response = jsons.loads(test_result.response) if isinstance(test_result.response, str) else test_result.response
    except Exception as e:
        LOGGER.warn(f"Schema error: Could not parse JSON: {e}")
        return False

    if not isinstance(response, dict) or response.get('status') != 200:
        return False

    # 3) Use the exact folder where results JSON is/will be written
    env_json = os.environ.get("DAB_RESULTS_JSON")
    results_root = os.path.dirname(env_json) if env_json else "./test_result"

    # 4) Save image BEFORE Yes/No prompt — to <results_root>/images/...
    try:
        png_path = save_output_image(
            response=response,
            device_id=getattr(test_result, "device_id", "device"),
            results_root=results_root,
            filename_prefix=getattr(test_result, "operation", "output_image"),
        )
        setattr(test_result, "_artifact_saved", True)  # optional: avoid re-save later

        # console-only info (do not add to test_result.logs)
        LOGGER.info(f"Screenshot saved: {png_path}")

    except Exception as e:
        LOGGER.warn(f"Image save error: {e}")
        return False

    # 5) Prompt and run default timing validation
    prompt = f"Verify '{png_path}' exists and shows the screenshot"
    ok = YesNoQuestion(test_result, prompt) and Default_Validations(test_result, durationInMs, expectedLatencyMs)

    # 6) Always attempt to delete the saved file (even if validations failed) — console-only logs
    try:
        if os.path.exists(png_path):
            os.remove(png_path)
            LOGGER.result(f"Deleted screenshot after validation: {png_path}")
    except Exception as e:
        LOGGER.warn(f"Failed to delete screenshot: {e}")

    return ok
