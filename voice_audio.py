from dab_tester import DabTester
import dab.applications
import dab.system
import argparse
import dab.voice

# Voice action steps
dab.voice.send_audio_Cases = [
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/ladygaga.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Are you on search page with Lady Gaga?", "Voice launch Lady gaga"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/pressenter.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Is video playing?", "Voice play video"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/playvideo.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "If video was not playing, is it playing now?", "Voice resume video"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/setvolume0.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Did volume of the video changed?", "voice mute"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/setvolume5.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Did volume of the video changed?", "voice volume up"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/pausevideo.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Did video paused?", "voice pause"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/fastforwardvideo.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Did video playback fast forward?", "voice fastforward"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/rewindvideo.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Did video playback rewind?", "voice rewind"),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/exittomainmenu.wav", "voiceSystem": "Alexa"}', dab.voice.send_audio, "Are you on main menu?", "voice exit"),
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
        for i in range(len(dab.voice.send_audio_Cases)):
            print("[%02d]"%i, dab.voice.send_audio_Cases[i][0]," ", dab.voice.send_audio_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Execute_All_Tests("voice_audio", device_id, dab.voice.send_audio_Cases, args.output)
        else:
            # Test a single case
            Tester.Execute_Test_Case(device_id,(dab.voice.send_audio_Cases[args.case]))
        
    Tester.Close()