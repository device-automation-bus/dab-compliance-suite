from time import sleep
from threading import Lock
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt
import json

METRICS_TIMES = 10

class DabClient:
    def __init__(self):
        self.__lock = Lock()
        self.__lock.acquire()
        self.__client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5)
        self.metrics_count = 0
        self.__log = ""

    def __on_message(self, client, userdata, message):   
        self.__response_dic = json.loads(message.payload)
        self.__lock.release()
        try:
            self.__code = self.__response_dic['status']
        except:
            self.__code = -1

    def __on_message_metrics(self, client, userdata, message):
        self.__response_dic = json.loads(message.payload)
        self.__log += f"\n{json.dumps(self.__response_dic)}"
        if self.metrics_count < METRICS_TIMES:
            self.metrics_count += 1
            print(self.__response_dic)
        else:
            self.__code = 200
            self.metrics_count = 0
            self.__lock.release()

    def disconnect(self):
        self.__client.disconnect()

    def connect(self,broker_address,broker_port):
        self.__client.connect(broker_address, port=broker_port)
        self.__client.loop_start()
    
    def request(self,device_id,operation,msg="{}"):
        # Send request and block until get the response or timeout
        topic = "dab/" + device_id+"/" + operation
        response_topic="dab/_response/"+topic
        self.__client.subscribe(response_topic)
        properties=Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic=response_topic
        self.__client.on_message = self.__on_message
        self.__client.subscribe(response_topic)
        self.__client.publish(topic,msg,properties=properties)
        if not (self.__lock.acquire(timeout = 90)):
            self.__code = 100
        
    def response(self):
        if((self.__code != -1) and (self.__code != 100)):
            return json.dumps(self.__response_dic, indent=2)
        else:
            return ""

    def response_metrics(self):
        return self.__log

    def subscribe_metrics(self, device_id, operation):
        self.__code = 100
        response_topic = "dab/" + device_id+"/" + operation
        self.__client.subscribe(response_topic)
        self.__client.on_message = self.__on_message_metrics
        if not (self.__lock.acquire(timeout = 90)):
            self.__code = 100

    def unsubscribe_metrics(self, device_id, operation):
        response_topic = "dab/" + device_id+"/" + operation
        self.__client.unsubscribe(response_topic)
        if self.__lock.locked():
            self.__lock.release()
    
    def last_error_code(self):
        return self.__code
    
    def last_error_msg(self):
        if(self.__code == -1):
            print("Unknown error",end='')
        elif(self.__code == 100):
            print("Timeout",end='')
        elif(self.__code == 400):
            print("Request invalid or malformed",end='')
        elif(self.__code == 500):
            print("Internal error",end='')
        elif(self.__code == 501):
            print("Not implemented",end='')