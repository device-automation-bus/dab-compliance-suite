import utils
from DabClient import DabClient

if __name__ == "__main__":
    dab_test_client = DabClient()
    dab_test_client.connect("localhost",1883)
    
    dab_test_client.request("dab/device/info")
    dab_test_client.print_response()
    print("Response: OK")
    
    dab_test_client.request("dab/operations/list")
    dab_test_client.print_response()
    print("Response: OK")
    
    dab_test_client.disconnect()