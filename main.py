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
import dab.output
import dab.version
import argparse
import conformance
import output_image
import netflix
import functional
from logger import LOGGER 

ALL_SUITES = {
    "conformance": conformance.CONFORMANCE_TEST_CASE,
    "output_image": output_image.OUTPUT_IMAGE_TEST_CASES,
    "netflix": netflix.NETFLIX_TEST_CASES,
    "functional": functional.FUNCTIONAL_TEST_CASE,
}

if __name__ == "__main__":
    test_suites_str = ""
    for field_name in ALL_SUITES.keys():
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
                        help="set the IP of the MQTT broker. Ex: -b 192.168.0.100",
                        type=str,
                        default="localhost")

    parser.add_argument("-I","--ID", 
                        help="set the DAB Device ID. Ex: -I mydevice123",
                        type=str,
                        default="localhost")

    parser.add_argument("-c","--case", 
                        help="test only the specified case(s). Use comma to separate multiple. Ex: -c InputLongKeyPressKeyDown,AppLaunchNegativeTest",
                        type=str)

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

    parser.set_defaults(output="")
    
    parser.set_defaults(case=99999)
    args = parser.parse_args()
    LOGGER.verbose = bool(args.verbose)
    device_id = args.ID

    Tester = DabTester(args.broker, override_dab_version=args.dab_version)
    
    Tester.verbose = args.verbose
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

    if(args.list == True):
        for suite in suite_to_run:
            LOGGER.info(f"Listing test cases for suite '{suite}'...")
            for test_case in suite_to_run[suite]:
                (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title, test_version, is_negative) = Tester.unpack_test_case(test_case)
                if dab_request_topic is None:
                    continue
                LOGGER.result(to_test_id(f"{dab_request_topic}/{test_title}"))
    else:
        if ((not isinstance(args.case, (str)) or len(args.case) == 0)):
            LOGGER.result("Testing all cases")
            for suite in suite_to_run:
                LOGGER.info(f"Preparing to run suite '{suite}' with {len(suite_to_run[suite])} tests.")
                Tester.assert_device_available(device_id)
                Tester.Execute_All_Tests(suite, device_id, suite_to_run[suite], args.output)
                LOGGER.ok(f"Completed suite '{suite}'.")
        else:
            # Handle single or multiple cases passed via -c
            requested_cases = [c.strip() for c in args.case.split(",")]
            LOGGER.info(f"Requested case IDs: {requested_cases}")
            matched_tests = []
            for suite in suite_to_run:
                LOGGER.info(f"Searching for requested cases in suite '{suite}'...")
                for test_case in suite_to_run[suite]:
                    (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title, test_version, is_negative) = Tester.unpack_test_case(test_case)
                    if dab_request_topic is None:
                        continue
                    test_id = to_test_id(f"{dab_request_topic}/{test_title}")
                    if test_id in requested_cases:
                        matched_tests.append(test_case)
                if matched_tests:
                    LOGGER.result(f"Matched {len(matched_tests)} case(s) in suite '{suite}'.")
                    Tester.assert_device_available(device_id)
                    Tester.Execute_Single_Test(suite, device_id, matched_tests, args.output)
                    break
            else:
                LOGGER.error(f"None of the requested test case IDs matched: {requested_cases}")

    Tester.Close()
    LOGGER.ok("Run complete. Connection closed.")
