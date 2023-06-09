from DabTester import DabTester
from DabTester import Voice_Test
import dab.applications
import dab.system
import argparse

# Voice action steps
Voice_Test_Cases = [
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}',Voice_Test, "Are you on search page with Lady Gaga?"),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}',Voice_Test, "Is video playing?"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}',Voice_Test, "Is volume going up?"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 2000}',Voice_Test, "Is volume going down?"),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}',Voice_Test, "Did video paused?"),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}',Voice_Test, "Did video playback fastforward?"),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}',Voice_Test, "Did video playback rewind?"),
    ("applications/exit",'{"appId": "Cobalt"}',dab.applications.exit, 1000),
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

    parser.add_argument("-I","--ID", 
                        help="set the Device ID.Ex: -I mydevice123",
                        type=str,
                        default="localhost")

    parser.add_argument("-c","--case", 
                        help="test only the specified case.Ex: -c 3",
                        type=int)
    parser.set_defaults(case=99999)
    args = parser.parse_args()
    
    # Use the DabTester
    device_id = args.ID

    Tester = DabTester(args.broker)
    
    Tester.verbose = args.verbose
    
    if(args.list == True):
        for i in range(len(Voice_Test_Cases)):
            print("[%02d]"%i,Voice_Test_Cases[i][0]," ",Voice_Test_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Test_All("end_to_end_cobalt", device_id,Voice_Test_Cases)
        else:
            # Test a single case
            Tester.Test_Case(device_id,(Voice_Test_Cases[args.case]))
        
    Tester.Close()