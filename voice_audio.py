from dab_tester import DabTester
import dab.applications
import dab.system
import argparse
import dab.voice

# Voice action steps
SEND_VOICE_AUDIO_TEST_CASES = [
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