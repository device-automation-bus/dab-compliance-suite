# DAB Compliance Testing Suite #

This project contains tools and tests to validate Device Automation Bus 2.1 Partner implementations end-to-end.

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

- The test tool reads test_version.txt.
- The same version is added inside the test result JSON file.
- This helps you know which version of the tool ran that test.

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

### Automatic App Setup Instructions ###

After extracting the DAB Compliance Test Suite, you DO NOT need to manually configure the APK or App Store URL.

Just follow this single step:

    Step 1: Run the following command

    ❯ python3 main.py -l

#### This will automatically guide you through setup: ####


  1. Sample App APK Setup

  - The tool will check if `Sample_App.apk` is available in:
      config/apps/

  - If it's missing:
    You will be prompted to enter the path to your APK file.
    The tool will automatically:
      - Copy the APK to the `config/apps/` folder
      - Rename it to `sample_app.apk` (preserving the original extension)

2. App Store URL Setup

  - The tool will also check if the App Store URL is saved in:
      config/apps/sample_app.json

  - If it's missing:
    You’ll be prompted to paste the App Store URL (e.g., from Google Play)
    This URL will be saved automatically in:
      config/apps/sample_app.json

  Example saved file:
      ```
      {
        "app_url": "https://play.google.com/store/apps/details?id=com.example.sample"
      }
      ```
## Available Test Suite ##

  ### 1. Spec conformance Test Suite ###

  Spec Conformance test checks if all DAB topic is available and the latency of each requests is within expectation. 
  This test doesn't check on functionality or endurance. This should be the first test suite to run if you are checking your baisc implementation against DAB.

  The following is command to run Spec conformance Test Suite:
  ```
  ❯ python3 main.py -v -b <mqtt-broker-ip> -I <dab-device-id> -s "conformance"
  ```


  ### 2. Send Text/Send Audio Voice Test Suite ###

  Voice functionality tests focuses on voice assisstance intergration with the platform. It go through a playback lifecycle from search to playback controls. Make sure if your device support all of these voice actions. 

  The following is command to run Send Text/Send Audio Voice Test Suite
  ```
  ❯ python3 main.py -v -b <mqtt-broker-ip> -I <dab-device-id> -s "voice_audio"

  ❯ python3 main.py -v -b <mqtt-broker-ip> -I <dab-device-id> -s "voice_text"
  ```

  ### 3. End to End Cobalt Test Suite ###

  This end to end intergration test focuses on a mix of key presses and voice controls.

  The following is command to run End to End Cobalt Test Suite

  ```
  ❯ python3 main.py -v -b <mqtt-broker-ip> -I <dab-device-id> -s "end_to_end_cobalt"
  ```

## Commands ##

These are the main commands of the tool:

```
❯ python3 test_suite.py --help
usage: main.py [-h] [-v] [-l] [-b BROKER] [-I ID] [-c CASE] [-o OUTPUT] [-s SUITE] [--dab-version {2.0,2.1}]

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
                        set what test suite to run. Available test suite includes:conformance, voice_audio, voice_text, output_image, netflix, functional
  --dab-version {2.0,2.1}
                        Override detected DAB version. Use 2.0 or 2.1 to force specific test compatibility.
</pre>

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
  Useful for rerunning a group of specific tests.

3. Full Suite Execution

  Command Example:
  ❯ python3 main.py -b <broker> -I <device_id> -s conformance

  What Happens:
  - Loads all test cases from the selected suite (like conformance, voice_audio, etc.)
  - Runs each test one by one.
  - Applies test version compatibility and prechecks.
  - Tracks and logs results for the entire batch.

  Use Case:
  Ideal for complete DAB verification (e.g., certification, release testing).

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
  OPTIONAL_FAILED   → Feature not supported or not required (e.g., DAB 2.1 on DAB 2.0 device)  
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

NEGATIVE TEST PASSED (Not a test result type — represents negative test results in the execution terminal log)

  - The test expected an error and got it.
  - Example: error 400 or 404 = correct behavior for a negative test.

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
  - NOTE: The remaining DAB operations are mandatory and should be implemented properly. They should not result in optional failed or failed tests — they must pass.