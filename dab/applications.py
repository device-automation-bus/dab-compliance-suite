from time import sleep
from DabTester import YesNoQuestion

def launch(durationInMs=0,expectedLatencyMs=0):
    sleep(5)
    return YesNoQuestion("Cobalt started?")
    
def exit(durationInMs=0,expectedLatencyMs=0):
    sleep(5)
    return YesNoQuestion("Cobalt exited?")