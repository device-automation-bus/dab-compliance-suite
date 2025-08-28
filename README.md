# DAB Compliance Testing Suite #

This project contains tools and tests for end-to-end validation of Device Automation Bus (DAB) 2.0 and 2.1 Partner implementations.

## Follow these steps to prepare and run the test suite: ##

## Download the Test Suite ##

The latest DAB Compliance Test Suite can be downloaded from the GitHub Actions workflow.

Download [Link](https://github.com/device-automation-bus/dab-compliance-suite/actions)


## Test Versioning ##

#### What is it? ####

Each time you push code to the 'main' branch, a version number is created automatically.

#### How is the version made? ####

- The version is based on the date + run number.
- Example: 25071801 = Year 2025, July 18, Run 01
- This version is saved in a file called: test_version.txt

#### What does it do? ####

- The test tool reads test_version.txt and embeds that version number in the test result JSON file. This helps you easily identify which tool version was used for a particular test.

#### Why is it useful? ####

- You can track and compare test results easily.
- Helps when debugging or reporting test outcomes.

#### Where is the version saved? ####

- File: test_version.txt (in the root folder)
- Also inside the test result JSON under "test_version"

#### Where is the full test tool zip? ####

- After each push to main, the whole project (with version info) is zipped.
- You can download it from GitHub → Actions → Artifacts.

## Prerequisite ##
Python minimal version 3.8

Please edit config.py to have the device app line up with your system settings.

```
pip3 install -r requirements.txt
```

### Automatic App Setup Instructions  ###

After extracting the DAB Compliance Test Suite, you DO NOT need to manually configure the APK or App Store URL.

1. Run your CLI with --init
   Example:
   python3 main.py --init

2. Application Setup:
   - The tool will check if Sample_App (application file) exists in config/apps/
   - If missing, it will prompt:
       "Full path to the application file (.apk or .apks):"
   - Enter the absolute path to your application file.
   - The tool will copy it into config/apps/ and rename to Sample_App.<ext>

3. App Store URL Setup:
   - The tool will check if config/apps/sample_app.json exists.
   - If missing, it will prompt:
       "Enter App Store URL for install-from-app-store tests:"
   - Paste the Play Store (or App Store) URL.
   - The tool saves it into config/apps/sample_app.json

4. Done!
   - only need to run --init again if you want to replace applications or URLs.


## Available Test Suite ##

  ### 1. Spec conformance Test Suite ###

  Spec Conformance test checks if all DAB topics are available and the latency of each request is within expectations. 
  This test doesn't check for functionality or endurance. It should be the first test suite to run if you are checking your basic implementation against DAB.

  The following is command to run Spec conformance Test Suite:
  ```
  ❯ python3 main.py -v -b <mqtt-broker-ip> -I <dab-device-id> -s "conformance"
  ```


## Commands ##

These are the main commands of the tool:

```
python3 main.py --help
usage: main.py [-h] [-v] [-l] [-b BROKER] [-I ID] [-c CASE] [-o OUTPUT] [-s SUITE] [--dab-version {2.0,2.1}] [--init]

options:
  -h, --help            show this help message and exit
  -v, --verbose         increase output verbosity
  -l, --list            list the test cases
  -b BROKER, --broker BROKER
                        set the IP of the MQTT broker. Ex: -b 192.168.0.100
  -I ID, --ID ID        set the DAB Device ID. Ex: -I mydevice123
  -c CASE, --case CASE  test only the specified case(s). Use comma to separate multiple. Ex: -c InputLongKeyPressKeyDown,AppLaunchNegativeTest
  -o OUTPUT, --output OUTPUT
                        output location for the json file
  -s SUITE, --suite SUITE
                        set what test suite to run. Available test suite includes:conformance, output_image, netflix, functional
  --dab-version {2.0,2.1}
                        Override detected DAB version. Use 2.0 or 2.1 to force specific test compatibility.
  --init                Interactive setup: prompt for app paths (and optional store URL), then exit.

```

## Command Examples ##

Test Execution Logic & Result Handling

The DAB Compliance Test Tool supports running tests in different ways:

1. Single Test Case Execution

    Command Example:
    ❯ python3 main.py -b <broker> -I <device_id> -c SystemSettingsSetSetHighContrastText

    What Happens:
    - Only that one test is unpacked and executed.
    - DAB version check and feature precheck are applied.
    - Result is printed and stored.

    Use Case:
    Great for checking or debugging a single feature.

2. Multiple Test Cases Execution

  Command Example:
  ❯ python3 main.py -b <broker> -I <device_id> -c TestA,TestB,TestC

  What Happens:
  - Each test is run one after another.
  - Each result is independently validated and stored.
  - The tool continues running even if one test fails.

  Use Case:
  Useful for re-running a group of specific tests.

3. Full Suite Execution

  - Run command:
    python3 main.py -b <broker> -I <device_id> -s conformance

  - What happens:
    - Loads all test cases from the chosen suite
    - Runs each test one by one
    - Checks DAB version and preconditions
    - Saves logs and results for the whole suite

  - When to use:
    - For full DAB verification
    - Certification or release testing


4. Output Results Handling (`-o` flag)

  Command Example:
  ❯ python3 main.py -b <broker> -I <device_id> -c SystemSettingsSetSetHighContrastText -o results/single_test.json

  How It Works:
  - If `-o <file>` is provided, the tool writes results to that file in JSON format.

  5. If `-o` is NOT provided:

  The tool will automatically save results to a default location.

  - Default Path:
    ./test_result/<suite_name>.json

Test Result Types:

  PASS              → Test succeeded with expected output  
  FAILED            → Test ran but result was incorrect  
  OPTIONAL_FAILED   → Feature not supported or not required (e.g., DAB 2.1 tests on DAB version 2.0) 
  SKIPPED           → Internal issue — test incomplete. Retry is required (e.g., pre-check failed).

Summary:

  - Choose `-c` for single or custom tests, `-s` for full suite
  - Use `-o` to save results to a JSON file
  - Tool handles DAB version filtering and unsupported features

  Test Result & Error Handling 

  Each test will end with one of the following results:

PASS

  - The test worked and the result was correct.
  - For negative tests, expected failure = PASS.

FAILED

  - The test ran, but gave the wrong result.

OPTIONAL_FAILED

  - The device doesn't support the feature.
  - Or test requires a newer DAB version.
  - Example: error code 501 → Not Implemented.

SKIPPED

  - The test didn't complete due to internal error.
  - Example: error code 500 or device not responding.

NEGATIVE TEST PASSED (Not a result type stored in JSON — only shown in the execution terminal log)

  Meaning:
  - The test intentionally expected an error response.
  - The DAB Bridge returned the correct error code (e.g., 400 Bad Request, 404 Not Found).
  - This confirms that the DAB Bridge is handling invalid or unsupported requests properly.

  Why it is required:
  - Negative tests ensure robustness and compliance by verifying that the DAB Bridge
    does not silently accept invalid inputs.
  - They check for proper error handling and system safety (e.g., rejecting bad data,
    unsupported operations, or invalid states).

Where can I see this?

  → Check the test result JSON. Each test includes:
    - Result type (PASS, FAILED, etc.)
    - Logs with error codes or messages
    - Response from device

Important: operation/list Topics

  When testing the "operation/list" feature:


Required Topics

  All DAB topics MUST be listed in "operation/list"  
  If a required topic is missing → **FAIL the test**

Telemetry Topics Are Optional

 Only the following topics are OPTIONAL:
   - device-telemetry/start
   - device-telemetry/stop
   - device-telemetry/metrics
   - app-telemetry/start
   - app-telemetry/stop
   - app-telemetry/metrics

These do NOT need to be present in operation/list.

How to Handle in Tests

  - If a required topic is missing from "operation/list" → FAIL
  - If telemetry topics are missing from "operation/list" → OK (no FAIL)
  - If telemetry tests are run but not supported → OPTIONAL_FAILED 
  
  - NOTE:
    All core DAB operations are mandatory and are expected to be implemented consistently.  
    These operations should not result in "optional failed" or "failed" outcomes they are required to pass in order to demonstrate full compliance with the DAB specification.
    
    - ABOUT 501 ERROR:
        According to the DAB specification, a 501 status code indicates that the DAB Bridge  
        recognizes the requested operation but does not support it.  

        This code is reserved for optional features.  
        When returned, the corresponding test is marked as "OPTIONAL FAILED" rather than "FAILED",  
        as support for such features is not mandatory for baseline compliance.

    - UI VS DAB OPERATIONS:
        If a feature or setting is available through the device’s user interface,  
        the DAB Bridge is also expected to provide the corresponding operation in `operations/list` and `system/settings/list`.  

        This ensures consistency between user-facing functionality and automated control.  
        The only acceptable case for omission is when the feature itself is not implemented  
        on the platform at all. Otherwise, missing support in DAB is treated as a compliance gap  
        and should be addressed.
