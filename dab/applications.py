from time import sleep
from DabTester import YesNoQuestion

def launch():
    sleep(2)
    return YesNoQuestion("Cobalt started?")
    
def exit():
    sleep(1)
    return YesNoQuestion("Cobalt exited?")