import utils
from DabClient import DabClient

if __name__ == "__main__":
    dab_test_client = DabClient()
    dab_test_client.connect("localhost",1883)
    response = dab_test_client.request("dab/device/info")
    print("Response: ",utils.json2str(response))
    response = dab_test_client.request("dab/operations/list")
    print("Response: ",utils.json2str(response))
    dab_test_client.disconnect()