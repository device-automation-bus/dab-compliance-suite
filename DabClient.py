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
        self.code = self.response['status']

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
        if not (self.lock.acquire(timeout = 5)):
            self.code = 100
        
    def response(self):
        if((self.code != -1) and (self.code != 100)):
            return json.dumps(self.response, indent=2)
        else:
            return ""
    
    def last_error_code(self):
        return self.code
    
    def last_error_msg(self):
        if(self.code == -1):
            print("Unknown error",end='')
        elif(self.code == 100):
            print("Timeout",end='')
        elif(self.code == 400):
            print("Request invalid or malformed",end='')
        elif(self.code == 500):
            print("Internal error",end='')
        elif(self.code == 501):
            print("Not implemented",end='')