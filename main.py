import sys 
import config
import json
import os
from dab_tester import DabTester
from dab_tester import Default_Validations
from dab_tester import to_test_id
import config
import dab.app_telemetry
import dab.device
import dab.health_check
import dab.input
import dab.operations
import dab.device_telemetry
import dab.voice
import dab.applications
import dab.system
import dab.content
import dab.output
import dab.version
import argparse
import builtins
import fnmatch
import types
from readchar import readchar
from logger import LOGGER
from util.config_loader import init_interactive_setup, make_app_id_list
from util.runtime_config_store import load_config, apply_overrides, save_config
from util.argument_validator import validate_arguments_and_warn

config_path = os.environ.get("DAB_CONFIG_JSON")

SUITE_NAMES = ["conformance", "output_image", "netflix", "functional"]
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def case_matches(test_id, requested_case):
    """Return whether a requested case matches a listed test ID."""
    return fnmatch.fnmatchcase(test_id, requested_case)


def is_manual_test(test_case):
    """
    Return whether a test case may prompt the operator for input.

    Follows the functions referenced by the test tuple through the calls
    they make inside this project and reports True when any of them reaches
    input() or readchar() (e.g. through yes_or_no or YesNoQuestion).
    """
    pending = [(obj.__code__, obj.__globals__) for obj in test_case if isinstance(obj, types.FunctionType)]
    seen = set()
    while pending:
        code, scope = pending.pop()
        if code in seen:
            continue
        seen.add(code)
        # Lambdas and nested functions share the enclosing globals
        pending.extend((const, scope) for const in code.co_consts if isinstance(const, types.CodeType))
        found = [scope.get(name, getattr(builtins, name, None)) for name in code.co_names]
        # Resolve attribute access such as helpers.yes_or_no or dab.applications.launch
        modules = [obj for obj in found if isinstance(obj, types.ModuleType)]
        while modules:
            module = modules.pop()
            for name in code.co_names:
                obj = getattr(module, name, None)
                if isinstance(obj, types.ModuleType) and obj not in found:
                    modules.append(obj)
                found.append(obj)
        for obj in found:
            if obj is builtins.input or obj is readchar:
                return True
            if (isinstance(obj, types.FunctionType)
                    and obj.__code__.co_filename.startswith(PROJECT_DIR)
                    and "site-packages" not in obj.__code__.co_filename):
                pending.append((obj.__code__, obj.__globals__))
    return False


if __name__ == "__main__":
    test_suites_str = ""
    for field_name in SUITE_NAMES:
        test_suites_str += field_name + ", "
    test_suites_str = test_suites_str[:-2]

    parser = argparse.ArgumentParser()
    parser.add_argument("-v","--verbose", 
                        help="increase output verbosity",
                        action="store_true")
    parser.set_defaults(verbose=False)
    parser.add_argument("-l","--list", 
                        help="list the test cases",
                        action="store_true")
    parser.set_defaults(list=False)
    parser.add_argument("-b","--broker", 
                        help="set the IP or host of the MQTT broker (host/IP only, no mqtt:// and no port). Ex: -b 192.168.0.100",
                        type=str,
                        default="localhost")

    parser.add_argument("-I","--ID", 
                        help="set the DAB Device ID. Ex: -I mydevice123",
                        type=str,
                        default="localhost")

    parser.add_argument("-c","--case", 
                        help="test only the specified case(s). Use comma to separate multiple or repeat -c. Supports shell-style wildcards (*, ?, []). Ex: -c InputLongKeyPressKeyDown,AppLaunchNegativeTest or -c 'SystemPower*' -c 'App*'",
                        action="append",
                        type=str)

    manual_group = parser.add_mutually_exclusive_group()
    manual_group.add_argument("--skip-manual",
                        help="skip the test cases that prompt the operator for input",
                        action="store_true")
    manual_group.add_argument("--manual-only",
                        help="run only the test cases that prompt the operator for input",
                        action="store_true")

    parser.add_argument("-o","--output", 
                        help="output location for the json file",
                        type=str)
    
    parser.add_argument("-s","--suite",
                        help="set what test suite to run. Available test suite includes:" + test_suites_str,
                        type=str)
    
    parser.add_argument("--dab-version",
                        help="Override detected DAB version. Use 2.0 or 2.1 to force specific test compatibility.",
                        type=str,
                        choices=["2.0", "2.1"],
                        default=None)

    parser.add_argument("--init", action="store_true",
                        help="Interactive setup: prompt for app paths (and optional store URL), then exit.")

    parser.add_argument("--config-app", action="append", default=None,
                        help="Update runtime apps mapping and exit. Repeat: --config-app key=value")
    
    parser.add_argument("--config-va", type=str, default=None,
                        help="Update runtime VA and exit. Example: --config-va GoogleAssistant")
    
    parser.add_argument("--config-show", action="store_true",
                    help="Print current runtime config and exit.")

    parser.set_defaults(output="")
    args = parser.parse_args()
    validate_arguments_and_warn(args)
    LOGGER.verbose = bool(args.verbose)
    device_id = args.ID


    if getattr(args, "config_show", False):
        path, cfg, created = load_config(config_path)

        LOGGER.result(f"[CONFIG] Path: {path}")
        if created:
            LOGGER.result("[CONFIG] Created default runtime config file.")
        LOGGER.result(f"[CONFIG] VA = {cfg.get('va')}")

        apps = cfg.get("apps", {})
        if isinstance(apps, dict) and apps:
            LOGGER.result(f"[CONFIG] Apps ({len(apps)}):")
            for k in sorted(apps.keys()):
                LOGGER.result(f"[CONFIG]   {k} = {apps[k]}")
        else:
            LOGGER.result("[CONFIG] Apps: <empty>")

        LOGGER.result("[CONFIG] Done. Exiting....")
        raise SystemExit(0)

    if args.config_app or args.config_va:
        try:
            from util.runtime_config_store import load_config, apply_overrides, save_config
            _path, _cfg, _created = load_config(config_path)
            _changed = apply_overrides(_cfg, apps_kv_list=args.config_app, va=args.config_va)

            if _changed:
                save_config(_path, _cfg)
                LOGGER.result(f"[CONFIG] Updated: {_path}")
            else:
                LOGGER.result(f"[CONFIG] No changes: {_path}")

            if args.config_va:
                LOGGER.result(f"[CONFIG] VA = {_cfg.get('va')}")

            if args.config_app:
                LOGGER.result(f"[CONFIG] Apps updated: {', '.join(args.config_app)}")

            LOGGER.result("[CONFIG] Done. Exiting....")
        except Exception as e:
            LOGGER.result(f"[CONFIG] Update failed: {type(e).__name__}: {e}")
            sys.exit(2)

        sys.exit(0)

    # ---- interactive bootstrap for sample apps ----
    elif getattr(args, "init", False):
        # Fixed to exactly three apps; make_app_id_list() now returns the allowed set.
        ids = make_app_id_list()
        print(f"[INIT] Managing fixed app set: {ids}")
        init_interactive_setup(app_ids=tuple(ids))  # safe: function uses the fixed allow-list
        print("[INIT] Done.")
        sys.exit(0)  # if you use 'from sys import exit as sys_exit', change to: sys_exit(0)

    # Read runtime config ONCE for this run and apply in memory
    config.init_runtime_config(config_path)
    LOGGER.result(f"[CONFIG] Active: va={config.va}, youtube={config.apps.get('youtube')}")

    import conformance
    import output_image
    import netflix
    import functional

    ALL_SUITES = {
        "conformance": conformance.CONFORMANCE_TEST_CASE,
        "output_image": output_image.OUTPUT_IMAGE_TEST_CASES,
        "netflix": netflix.NETFLIX_TEST_CASES,
        "functional": functional.FUNCTIONAL_TEST_CASE,
    }

    requested_cases = [
        c.strip()
        for case_arg in (args.case or [])
        for c in case_arg.split(",")
        if c.strip()
    ]

    # An empty selection such as -c ',' must not fall back to running every test.
    if args.case and not requested_cases:
        LOGGER.error("-c/--case was given without any test ID or pattern.")
        sys.exit(2)

    Tester = DabTester(args.broker, override_dab_version=args.dab_version)

    Tester.verbose = args.verbose
    # --skip-manual is meant for unattended runs, so preflight must not prompt either
    Tester.interactive_preflight = not args.skip_manual
    try:
        Tester.logger.verbose = Tester.verbose
    except Exception:
        pass
    LOGGER.info(f"Starting run with broker {args.broker}, device ID '{device_id}', suite='{args.suite or 'ALL'}', output='{args.output or '(default)'}', dab-version override='{args.dab_version or 'auto'}'.")

    suite_to_run = {}

    if (args.suite):
        # Let dict throw KeyError here
        suite_to_run.update({args.suite: ALL_SUITES[args.suite]})
        LOGGER.info(f"Selected suite: '{args.suite}' with {len(suite_to_run[args.suite])} tests.")
    else:
        suite_to_run = ALL_SUITES
        LOGGER.info(f"No suite specified. All suites selected: {', '.join(suite_to_run.keys())}.")

    if args.skip_manual or args.manual_only:
        suite_to_run = {
            suite: [test_case for test_case in test_cases if is_manual_test(test_case) == args.manual_only]
            for suite, test_cases in suite_to_run.items()
        }
        suite_to_run = {suite: test_cases for suite, test_cases in suite_to_run.items() if test_cases}
        LOGGER.info(
            f"{'Only manual' if args.manual_only else 'Skipping manual'} test cases: "
            f"{sum(len(test_cases) for test_cases in suite_to_run.values())} test(s) selected."
        )

    if (args.list == True):
        for suite in suite_to_run:
            LOGGER.info(f"Listing test cases for suite '{suite}'...")
            listed = 0
            for test_case in suite_to_run[suite]:
                try:
                    topic, _body_spec, _func, _expected, title, _is_neg, _ver = Tester.unpack_test_case(test_case)
                    if topic and title:
                        test_id = to_test_id(f"{topic}/{title}")
                        if not requested_cases or any(
                            case_matches(test_id, requested_case)
                            for requested_case in requested_cases
                        ):
                            LOGGER.result(test_id)
                            listed += 1
                    else:
                        LOGGER.warn(f"Skipping malformed test tuple (no topic/title): {test_case}")
                except Exception as e:
                    LOGGER.warn(f"Skipping malformed test tuple: {type(e).__name__}: {e}")
            LOGGER.ok(f"Listed {listed} case(s) in suite '{suite}'.")

    else:
        if not requested_cases:
            LOGGER.result("Testing all cases")
            for suite in suite_to_run:
                LOGGER.info(f"Preparing to run suite '{suite}' with {len(suite_to_run[suite])} tests.")
                Tester.assert_device_available(device_id)
                Tester.Execute_All_Tests(suite, device_id, suite_to_run[suite], args.output)
                if Tester.preflight_terminated:
                    LOGGER.warn("Run terminated during preflight. Remaining suites are not run.")
                    break
                LOGGER.ok(f"Completed suite '{suite}'.")
        else:
            # Handle single or multiple cases passed via -c
            LOGGER.info(f"Requested case IDs: {requested_cases}")
            matched_count = 0
            matched_suites = []
            suite_reports = []
            selected_results = []
            for suite in suite_to_run:
                LOGGER.info(f"Searching for requested cases in suite '{suite}'...")
                matched_tests = []
                for test_case in suite_to_run[suite]:
                    (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title, test_version, is_negative) = Tester.unpack_test_case(test_case)
                    if dab_request_topic is None:
                        continue
                    test_id = to_test_id(f"{dab_request_topic}/{test_title}")
                    if any(case_matches(test_id, requested_case) for requested_case in requested_cases):
                        matched_tests.append(test_case)
                if matched_tests:
                    LOGGER.result(f"Matched {len(matched_tests)} case(s) in suite '{suite}'.")
                    matched_count += len(matched_tests)
                    matched_suites.append(suite)
                    Tester.assert_device_available(device_id)
                    Tester.Execute_Single_Test(
                        suite,
                        device_id,
                        matched_tests,
                        args.output,
                        emit_summary=False,
                    )
                    selected_results.extend(Tester.last_valid_results)
                    if args.output:
                        # Keep what this suite wrote; the next suite overwrites the file
                        try:
                            with open(args.output, "r", encoding="utf-8") as f:
                                suite_reports.append(json.load(f))
                        except (OSError, ValueError) as e:
                            LOGGER.warn(f"Could not read back the results of suite '{suite}': {e}")
                    if Tester.preflight_terminated:
                        LOGGER.warn("Run terminated during preflight. Remaining suites are not run.")
                        break
            if matched_count == 0:
                LOGGER.error(f"None of the requested test case IDs matched: {requested_cases}")
            else:
                if len(suite_reports) > 1:
                    # Each suite wrote its own results to args.output, so only the
                    # last one is left there. Merge the per-suite files as written,
                    # since the results were already cleaned up by the JSON writer.
                    combined = dict(suite_reports[0])
                    combined["suite_name"] = "+".join(matched_suites)
                    combined["test_result_list"] = [
                        test for report in suite_reports for test in report.get("test_result_list", [])
                    ]
                    summaries = [report.get("result_summary", {}) for report in suite_reports]
                    combined["result_summary"] = {
                        key: sum(summary.get(key, 0) for summary in summaries)
                        for key in ("tests_executed", "tests_passed", "tests_failed", "tests_optional_failed", "tests_skipped")
                    }
                    # A suite stopped in preflight may have written no results at all,
                    # which its own summary counts as passed.
                    combined["result_summary"]["overall_passed"] = (
                        not Tester.preflight_terminated
                        and len(selected_results) == matched_count
                        and all(summary.get("overall_passed", False) for summary in summaries)
                    )
                    with open(args.output, "w", encoding="utf-8") as f:
                        json.dump(combined, f, indent=4)
                    LOGGER.ok(f"Saved the combined results JSON at {os.path.abspath(args.output)}.")
                outcomes = [
                    getattr(result, "test_result", None)
                    or getattr(result, "outcome", None)
                    or "UNKNOWN"
                    for result in selected_results
                ]
                LOGGER.result("Selected Test Results Summary")
                LOGGER.result(f"Executed        : {len(selected_results)}")
                LOGGER.result(f"  PASS          : {outcomes.count('PASS')}")
                LOGGER.result(f"  FAIL          : {outcomes.count('FAILED')}")
                LOGGER.result(f"  OPTIONAL_FAIL : {outcomes.count('OPTIONAL_FAILED')}")
                LOGGER.result(f"  SKIPPED       : {outcomes.count('SKIPPED')}")
                # A run stopped during preflight leaves matched tests without a result.
                not_run = matched_count - len(selected_results)
                if not_run > 0:
                    LOGGER.result(f"  NOT RUN       : {not_run}")
                LOGGER.result("Results by test:")
                for result in selected_results:
                    outcome = (
                        getattr(result, "test_result", None)
                        or getattr(result, "outcome", None)
                        or "UNKNOWN"
                    )
                    LOGGER.result(f"  {outcome:<16} {getattr(result, 'test_id', '<unknown>')}")
                LOGGER.result(
                    f"Overall Passed  : {'YES' if not_run <= 0 and not any(outcome in {'FAILED', 'SKIPPED'} for outcome in outcomes) else 'NO'}"
                )

    Tester.Close()
    LOGGER.ok("Run complete. Connection closed.")
