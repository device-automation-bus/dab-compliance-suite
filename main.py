from time import sleep
import json
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt

class Dab_Client:
    def on_message(self, client, userdata, message):
        print("Received: ")    
        json_object = json.loads(message.payload)
        json_formatted_str = json.dumps(json_object, indent=2)
        print(json_formatted_str)
        print("on topic: ",message.topic)
        self.disconnect()

    def disconnect(self):
        self.client.disconnect()

    def connect(self,broker_address,broker_port):
        print("Creating new Client instance")
        self.client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5) 
        print("Connecting to MQTT broker")
        self.client.connect(broker_address, port=broker_port)
        self.client.loop_start()
    
    def send_cmd(self,topic,msg):
        response_topic="_response/"+topic
        print("Subscribing to topic",response_topic)
        self.client.subscribe(response_topic)
        print("Publishing message to topic",topic)
        properties=Properties(PacketTypes.PUBLISH)
        properties.ResponseTopic=response_topic
        self.client.on_message = self.on_message
        self.client.subscribe(response_topic)
        self.client.publish(topic,msg,properties=properties)

if __name__ == "__main__":
    dab_test_client = Dab_Client()
    dab_test_client.connect("localhost",1883)
    dab_test_client.send_cmd("dab/device/info","{}")
    sleep(1)
    dab_test_client.disconnect()