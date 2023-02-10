from DabTester import DabTester
from DabTester import Default_Test
import dab.applications
import dab.system
import argparse

# Implement the test cases
Test_Cases = [
    ("operations/list",'{}',Default_Test),
    ("applications/list",'{}',Default_Test),
    ("applications/launch",'{"appId": "Cobalt"}',dab.applications.launch),
    ("applications/launch-with-content",'{}',Default_Test),
    ("applications/get-state",'{"appId": "Cobalt"}',Default_Test),
    ("applications/exit",'{"appId": "Cobalt"}',dab.applications.exit),
    ("device/info",'{}',Default_Test),
    ("system/settings/list",'{}',Default_Test),
    ("system/settings/get",'{}',Default_Test),
    ("system/settings/set",'{}',Default_Test),
    ("input/key/list",'{}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_LEFT"}',Default_Test),
    ("input/long-key-press",'{}',Default_Test),
    ("output/image",'{"outputLocation": "https://webhook.site/791918a1-cf5f-4a3e-9166-9f83af776232"}', Default_Test),
    ("device-telemetry/start",'{}',Default_Test),
    ("device-telemetry/stop",'{}',Default_Test),
    ("app-telemetry/start",'{}',Default_Test),
    ("app-telemetry/stop",'{}',Default_Test),
    ("health-check/get",'{}',Default_Test),
    ("voice/list",'{}',Default_Test),
    ("voice/set",'{}',Default_Test),
    ("voice/send-audio",'{}',Default_Test),
    ("voice/send-text",'{}',Default_Test),
    ("version",'{}',Default_Test),
    ("system/restart",'{}',dab.system.restart),
]

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
                        help="set the IP of the broker.Ex: -b 192.168.0.100",
                        type=str,
                        default="localhost")
    parser.add_argument("-c","--case", 
                        help="test only the specified case.Ex: -c 3",
                        type=int)
    parser.set_defaults(case=99999)
    args = parser.parse_args()
    
    # Use the DabTester
    device_id = "OEUzIwMjExMTA4NjAyMDAwOA"

    Tester = DabTester(args.broker)
    
    Tester.verbose = args.verbose
    
    if(args.list == True):
        for i in range(len(Test_Cases)):
            print("[%02d]"%i,Test_Cases[i][0]," ",Test_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Test_All(device_id,Test_Cases)
        else:
            # Test a single case
            Tester.Test_Case(device_id,(Test_Cases[args.case]))
        
    Tester.Close()