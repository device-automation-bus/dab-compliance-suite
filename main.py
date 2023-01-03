from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes 
import paho.mqtt.client as mqtt #import the client1

broker_address="localhost"
broker_port=1883

def on_message(client, userdata, message):
    
    import json
    print("Received: ")    
    json_object = json.loads(message.payload)
    json_formatted_str = json.dumps(json_object, indent=2)
    print(json_formatted_str)
    print("on topic: ",message.topic)
    
    client.disconnect()

def main():
    print("Creating new Client instance")
    client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5) 
    
    print("Connecting to MQTT broker")
    client.connect(broker_address, port=broker_port)
    
    topic="dab/applications/list"
    response_topic="_response/"+topic
    print("Subscribing to topic",response_topic)
    client.subscribe(response_topic)
    print("Publishing message to topic",topic)
    properties=Properties(PacketTypes.PUBLISH)
    properties.ResponseTopic=response_topic
    # Set the callback function
    client.on_message = on_message
    # Subscribe to a topic
    client.subscribe(response_topic)
    # Publish to a topic
    client.publish("dab/applications/list","{}",properties=properties)
    # Start the network loop to receive messages
    client.loop_forever()


if __name__ == "__main__":
    main()