from time import sleep
from DabTester import YesNoQuestion

def launch(test_result, durationInMs=0,expectedLatencyMs=0):
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt started?")

def launch_with_content(test_result, durationInMs=0,expectedLatencyMs=0):
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt started with playback?")
    
def exit(test_result, durationInMs=0,expectedLatencyMs=0):
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt exited?")