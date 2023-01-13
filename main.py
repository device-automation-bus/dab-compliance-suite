from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt #import the client1
import json
import threading

class Dab_Client:
    # def __init__(self,broker_address,broker_port):
    
    def on_message(self, client, userdata, message):
        print("Received: ")    
        json_object = json.loads(message.payload)
        json_formatted_str = json.dumps(json_object, indent=2)
        print(json_formatted_str)
        print("on topic: ",message.topic)
        self.client.disconnect()

    def connect(self,broker_address,broker_port):
        print("Creating new Client instance")
        self.client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5) 
        
        print("Connecting to MQTT broker")
        self.client.connect(broker_address, port=broker_port)
        
        topic="dab/device/info5"
        response_topic="_response/"+topic
        print("Subscribing to topic",response_topic)
        self.client.subscribe(response_topic)
        print("Publishing message to topic",topic)
        properties=Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic=response_topic
        self.client.on_message = self.on_message
        self.client.subscribe(response_topic)
        self.client.publish(topic,"{}",properties=properties)

    def loop(self):
        self.client.loop_forever()


if __name__ == "__main__":
    dab_test_client = Dab_Client()
    dab_test_client.connect("localhost",1883)
    dab_test_client.loop()
    