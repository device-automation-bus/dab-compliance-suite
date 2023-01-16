from time import sleep
from DabTester import YesNoQuestion

def restart():
    print(" wait ...",end='')
    sleep(30)
    return YesNoQuestion("Cobalt re-started?")