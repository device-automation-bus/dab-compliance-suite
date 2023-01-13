from time import sleep
from threading import Lock
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt
import json

class DabClient:
    def __init__(self):
        self.lock = Lock()
        self.lock.acquire()
        self.client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5) 

    def __on_message(self, client, userdata, message):   
        self.response = json.loads(message.payload)
        self.lock.release()

    def disconnect(self):
        self.client.disconnect()

    def connect(self,broker_address,broker_port):
        self.client.connect(broker_address, port=broker_port)
        self.client.loop_start()
    
    def request(self,topic,msg="{}"):
        # Send request and block until get the response or timeout
        response_topic="_response/"+topic
        self.client.subscribe(response_topic)
        properties=Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic=response_topic
        self.client.on_message = self.__on_message
        self.client.subscribe(response_topic)
        self.client.publish(topic,msg,properties=properties)
        self.lock.acquire()
        
    def print_response(self):
        print(json.dumps(self.response, indent=2))
