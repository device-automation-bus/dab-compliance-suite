from DabTester import DabTester
from DabTester import Default_Test
import dab.applications
import dab.system
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v","--verbose", 
                        help="increase output verbosity",
                        action="store_true")
    parser.set_defaults(feature=False)
    parser.add_argument("-c","--case", 
                        help="test only the specified case.Ex: -c 3",
                        type=int)
    parser.set_defaults(feature=False)
    args = parser.parse_args()
    
    # Use the DabTester
    Tester = DabTester()
    # Implement the test cases
    Test_Cases = [
        ("dab/operations/list",'{}',Default_Test),
        ("dab/applications/list",'{}',Default_Test),
        ("dab/applications/launch",'{"appId": "Cobalt"}',dab.applications.launch),
        ("dab/applications/launch-with-content",'{}',Default_Test),
        ("dab/applications/get-state",'{"appId": "Cobalt"}',Default_Test),
        ("dab/applications/exit",'{"appId": "Cobalt"}',dab.applications.exit),
        ("dab/device/info",'{}',Default_Test),
        ("dab/system/settings/list",'{}',Default_Test),
        ("dab/system/settings/get",'{}',Default_Test),
        ("dab/system/settings/set",'{}',Default_Test),
        ("dab/input/key/list",'{}',Default_Test),
        ("dab/input/key-press",'{"keyCode": "KEY_DOWN"}',Default_Test),
        ("dab/input/long-key-press",'{}',Default_Test),
        ("dab/output/image",'{}',Default_Test),
        ("dab/device-telemetry/start",'{}',Default_Test),
        ("dab/device-telemetry/stop",'{}',Default_Test),
        ("dab/app-telemetry/start",'{}',Default_Test),
        ("dab/app-telemetry/stop",'{}',Default_Test),
        ("dab/health-check/get",'{}',Default_Test),
        ("dab/voice/list",'{}',Default_Test),
        ("dab/voice/set",'{}',Default_Test),
        ("dab/voice/send-audio",'{}',Default_Test),
        ("dab/voice/send-text",'{}',Default_Test),
        ("dab/version",'{}',Default_Test),
        ("dab/system/language/list",'{}',Default_Test),
        ("dab/system/language/get",'{}',Default_Test),
        ("dab/system/language/set",'{}',Default_Test),
        ("dab/system/restart",'{}',dab.system.restart),
    ]
    
    Tester.verbose = args.verbose
    
    if(args.case == None):
        # Test all the cases
        Tester.Test_All(Test_Cases)
    else:
        # Test a single case
        Tester.Test_Case(Test_Cases[args.case])
        
    Tester.Close()