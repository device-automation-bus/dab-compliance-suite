from dab_tester import DabTester
from dab_tester import Voice_Test
import dab.applications
import dab.system
import argparse
import dab.input
import dab.voice
import config

# Voice action steps
Voice_Test_Cases = [
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}', dab.voice.send_text, "Are you on search page with Lady Gaga?", "End to end launch"),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}', dab.input.key_press, "Is video playing?", "End to end key press Enter"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}', dab.input.long_key_press, "Is volume going up?", "End to end volume up"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 2000}', dab.input.long_key_press, "Is volume going down?", "End to End volume down"),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}', dab.input.key_press, "Did video paused?", "End to End pause video"),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}', dab.input.long_key_press, "Did video playback fastforward?", "End to end fastforward"),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}', dab.input.long_key_press, "Did video playback rewind?", "End to end rewind"),
    ("applications/exit",f'{{"appId": "{config.apps["youtube"]}"}}',dab.applications.exit, 1000, "End to end exit"),
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
            print("[%02d]"%i, dab.input.long_key_press_Cases[i][0]," ", dab.input.long_key_press_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Test_All("end_to_end_cobalt", device_id, dab.input.long_key_press_Cases)
        else:
            # Test a single case
            Tester.Test_Case(device_id,(Voice_Test_Cases[args.case]))
        
    Tester.Close()