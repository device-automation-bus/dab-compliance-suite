from DabTester import DabTester
from DabTester import Voice_Test
import dab.applications
import dab.system
import argparse
from schema import dab_response_validator
import dab.voice

# Voice action steps
Voice_Test_Cases = [
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}', dab.voice.send_text, "Are you on search page with Lady Gaga?", "Voice launch Lady gaga"),
    ("voice/send-text",'{"requestText" : "Press enter", "voiceSystem": "Alexa"}', dab.voice.send_text, "Is video playing?", "Voice play video", "Voice play video"),
    ("voice/send-text",'{"requestText" : "Play video", "voiceSystem": "Alexa"}', dab.voice.send_text, "If video was not playing, is it playing now?", "Voice resume video"),
    ("voice/send-text",'{"requestText" : "Set volume 0", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did volume of the video changed?", "voice mute"),
    ("voice/send-text",'{"requestText" : "Set volume 5", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did volume of the video changed?", "voice volume up"),
    ("voice/send-text",'{"requestText" : "Pause Video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video paused?", "voice pause"),
    ("voice/send-text",'{"requestText" : "Fast forward video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video playback fast forward?", "voice fastforward"),
    ("voice/send-text",'{"requestText" : "Rewind video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video playback rewind?", "voice rewind"),
    ("voice/send-text",'{"requestText" : "Exit to main menu", "voiceSystem": "Alexa"}', dab.voice.send_text, "Are you on main menu?", "voice exit"),
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
            print("[%02d]"%i, dab.voice.send_text_Cases[i][0]," ", dab.voice.send_text_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Execute_All_Tests("voice_text", device_id, dab.voice.send_text_Cases, args.output)
        else:
            # Test a single case
            Tester.Execute_Test_Case(device_id,(Voice_Test_Cases[args.case]))
        
    Tester.Close()