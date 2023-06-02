from DabTester import DabTester
from DabTester import Voice_Test
import dab.applications
import dab.system
import argparse

# Voice action steps
Voice_Test_Cases = [
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}',Voice_Test, "Are you on search page with Lady Gaga?"),
    ("voice/send-text",'{"requestText" : "Press enter", "voiceSystem": "Alexa"}',Voice_Test, "Is video playing?"),
    ("voice/send-text",'{"requestText" : "Play video", "voiceSystem": "Alexa"}',Voice_Test, "If video was not playing, is it playing now?"),
    ("voice/send-text",'{"requestText" : "Set volume 0", "voiceSystem": "Alexa"}',Voice_Test, "Did volume of the video changed?"),
    ("voice/send-text",'{"requestText" : "Set volume 5", "voiceSystem": "Alexa"}',Voice_Test, "Did volume of the video changed?"),
    ("voice/send-text",'{"requestText" : "Pause Video", "voiceSystem": "Alexa"}',Voice_Test, "Did video paused?"),
    ("voice/send-text",'{"requestText" : "Fast forward video", "voiceSystem": "Alexa"}',Voice_Test, "Did video playback fast forward?"),
    ("voice/send-text",'{"requestText" : "Rewind video", "voiceSystem": "Alexa"}',Voice_Test, "Did video playback rewind?"),
    ("voice/send-text",'{"requestText" : "Exit to main menu", "voiceSystem": "Alexa"}',Voice_Test, "Are you on main menu?"),
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
            Tester.Test_All(device_id,Voice_Test_Cases)
        else:
            # Test a single case
            Tester.Test_Case(device_id,(Voice_Test_Cases[args.case]))
        
    Tester.Close()