from time import sleep
from threading import Lock
import json
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt

class Dab_Client:
    def __init__(self):
        self.lock = Lock()
        self.lock.acquire()
        self.client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5) 

    def on_message(self, client, userdata, message):   
        self.response = json.loads(message.payload)
        self.lock.release()

    def disconnect(self):
        self.client.disconnect()

    def connect(self,broker_address,broker_port):
        print("Connecting to MQTT broker at",broker_address,":",broker_port)
        self.client.connect(broker_address, port=broker_port)
        self.client.loop_start()
    
    def request(self,topic,msg="{}"):
        print("Requesting: ",topic)
        print("Payload: ",msg)
        response_topic="_response/"+topic
        self.client.subscribe(response_topic)
        properties=Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic=response_topic
        self.client.on_message = self.on_message
        self.client.subscribe(response_topic)
        self.client.publish(topic,msg,properties=properties)
        self.lock.acquire()
        return self.response

def print_json(msg):
    json_formatted_str = json.dumps(msg, indent=2)
    print("Response: ",json_formatted_str)

if __name__ == "__main__":
    dab_test_client = Dab_Client()
    dab_test_client.connect("localhost",1883)
    response = dab_test_client.request("dab/device/info")
    print_json(response)
    response = dab_test_client.request("dab/operations/list")
    print_json(response)
    dab_test_client.disconnect()