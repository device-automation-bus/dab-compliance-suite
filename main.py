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
import end_to_end_cobalt
import voice_audio
import voice_text

ALL_SUITES = {
    "conformance": conformance.CONFORMANCE_TEST_CASE,
    "end_to_end_cobalt": end_to_end_cobalt.END_TO_END_TEST_CASE,
    "voice_audio": voice_audio.SEND_VOICE_AUDIO_TEST_CASES,
    "voice_text": voice_text.SEND_VOICE_TEXT_TEST_CASES
}

if __name__ == "__main__":
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
                        help="test only the specified case. Ex: -c InputLongKeyPressKeyDown",
                        type=str)

    parser.add_argument("-o","--output", 
                        help="output location for the json file",
                        type=str)
    
    parser.add_argument("-s","--suite",
                        help="set what test suite to run. Avaible test suite includes: conformance, voice_audio, voice_text, end_to_end_cobalt",
                        type=str)

    parser.set_defaults(output="")
    
    parser.set_defaults(case=99999)
    args = parser.parse_args()
    
    # Use the DabTester
    device_id = args.ID

    Tester = DabTester(args.broker)
    
    Tester.verbose = args.verbose

    suite_to_run = {}

    if (args.suite):
        # Let dict throw KeyError here
        suite_to_run.update({args.suite: ALL_SUITES[args.suite]})
    else:
        suite_to_run = ALL_SUITES


    if(args.list == True):
        for suite in suite_to_run:
            for test_case in suite_to_run[suite]:
                (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title) = test_case
                print(to_test_id(f"{dab_request_topic}/{test_title}"))
    else:
        if (len(args.case) == 0) or (not isinstance(args.case, (str))):
            # Test all the cases
            print("Testing all cases")
            for suite in suite_to_run:
                Tester.Execute_All_Tests(suite, device_id, suite_to_run[suite], args.output)
        else:
            # Test a single case
            for suite in suite_to_run:
                for test_case in suite_to_run[suite]:
                    (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title) = test_case
                    if (to_test_id(f"{dab_request_topic}/{test_title}") == args.case):
                        Tester.Execute_Test_Case(device_id,(test_case))
    Tester.Close()