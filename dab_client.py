from time import sleep
from threading import Lock
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import paho.mqtt.client as mqtt
import json
import uuid
from logger import LOGGER  

METRICS_TIMES = 5

class DabClient:
    def __init__(self):
        self.__lock = Lock()
        self.__lock.acquire()
        self.__client = mqtt.Client("mqtt5_client",protocol=mqtt.MQTTv5)
        self.__metrics_count = 0
        self.__response_chunks = []
        self.__response_dic = {}
        self.__code = -1  # unknown by default

    def __on_message(self, client, userdata, message):
        try:
            self.__response_dic = json.loads(message.payload)
        except Exception as e:
            LOGGER.warn(f"Non-JSON response on {message.topic}: {e}")
            self.__response_dic = {}
        self.__response_chunks.append(self.__response_dic)
        try:
            self.__code = self.__response_dic['status']
        except:
            self.__code = -1
        LOGGER.info(f"Response on {message.topic}: status={self.__code}")
        if self.__lock.locked():
            self.__lock.release()

    def get_response_chunk(self):
        return self.__response_chunks.pop(0) if self.__response_chunks else None

    def __on_message_metrics(self, client, userdata, message):
        if not message.payload:
            return
        try:
            metrics_response = json.loads(message.payload)
            if self.__metrics_count < METRICS_TIMES:
                self.__metrics_count += 1
                LOGGER.info(f"[METRICS] {metrics_response}")  
            else:
                self.__metrics_state = True
                self.__lock.release()
        except Exception as e:
            LOGGER.warn(f"Non-JSON metrics payload on {message.topic}: {e}")

    def disconnect(self):
        LOGGER.info("Disconnecting MQTT client…")  
        self.__client.disconnect()

    def connect(self,broker_address,broker_port):
        LOGGER.info(f"Connecting to MQTT broker {broker_address}:{broker_port}…")  
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
        LOGGER.info(f"Subscribed to response topic: {response_topic}")  
        self.__client.publish(topic,msg,properties=properties)
        LOGGER.info(f"Published request to {topic}") 
        self.__response_chunks.clear()
        if not (self.__lock.acquire(timeout = 90)):
            self.__code = 100
            LOGGER.error(f"Timeout waiting for response on {response_topic}")  

    def response(self):
        if((self.__code != -1) and (self.__code != 100)):
            return json.dumps(self.__response_dic, indent=2)
        else:
            return ""

    def subscribe_metrics(self, device_id, operation):
        self.__metrics_state = False
        self.__metrics_count = 0
        response_topic = "dab/" + device_id+"/" + operation
        self.__client.subscribe(response_topic)
        self.__client.on_message = self.__on_message_metrics
        if not (self.__lock.acquire(timeout = 30)):
            self.__metrics_state = False
            LOGGER.warn("[METRICS] Timed out waiting for metrics messages.")  

    def unsubscribe_metrics(self, device_id, operation):
        response_topic = "dab/" + device_id+"/" + operation
        self.__client.unsubscribe(response_topic)

    def last_metrics_state(self):
        return self.__metrics_state

    def last_error_code(self):
        return self.__code

    def last_error_msg(self):
        # replaced prints with logger
        if(self.__code == -1):
            LOGGER.warn("Unknown error")
        elif(self.__code == 100):
            LOGGER.error("Timeout")
        elif(self.__code == 400):
            LOGGER.warn("Request invalid or malformed")
        elif(self.__code == 500):
            LOGGER.error("Internal error")
        elif(self.__code == 501):
            LOGGER.warn("Not implemented")

    # ---- Minimal discovery compatible with callers passing attempts + wait_seconds ----
    def discover_devices(self, attempts: int = 1, wait_seconds: float = 1.0):
        """
        Broadcasts to 'dab/discovery' and collects responses on a unique response topic.
        Compatible with callers that pass attempts + wait_seconds.
        Returns: [{"deviceId": "<id>", "ip": "<ip or None>"}]
        """
        resp_topic = f"dab/_response/discovery/{uuid.uuid4().hex}"
        found = {}

        def _on_disc(_c, _u, msg):
            try:
                d = json.loads(msg.payload.decode("utf-8"))
                dev = d.get("deviceId") or d.get("device_id")
                ip  = d.get("ip") or d.get("ipAddress")
                if dev and dev not in found:
                    found[dev] = {"deviceId": dev, "ip": ip}
                elif dev and ip and not found[dev].get("ip"):
                    found[dev]["ip"] = ip
            except:
                LOGGER.warn(f"Bad discovery payload on {msg.topic}")  

        self.__client.message_callback_add(resp_topic, _on_disc)
        self.__client.subscribe(resp_topic)

        props = Properties(PacketTypes.PUBLISH)
        props.ResponseTopic = resp_topic
        payload = "{}"

        n = 1 if attempts is None else max(1, int(attempts))
        for _ in range(n):
            self.__client.publish("dab/discovery", payload, properties=props)
            sleep(max(0.2, float(wait_seconds)))

        try:
            self.__client.message_callback_remove(resp_topic)
        except:
            pass
        self.__client.unsubscribe(resp_topic)
        return list(found.values())
