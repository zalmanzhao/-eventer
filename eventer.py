from kubernetes import client, config, watch
import datetime
import json
import requests
import logging
import sys
import os
import threading
from time import mktime, time

MSG_TEMPLATE = "%s\nLevel: %s \nNamespace: %s \nName: %s \nMessage: %s \nReason: %s \nTimestamp: %s"

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def send_ding(data, robot):
    post_data = json.dumps(data).encode(encoding='UTF8')
    response = requests.post(robot, headers={'Content-Type': 'application/json; charset=utf-8'}, data=post_data)
    if response.status_code != 200:
        return False
    return True

def pod_envet(v1, level, cluster_name, robot):
    w = watch.Watch()
    for event in w.stream(v1.list_event_for_all_namespaces):
        try:
            if event['object'].type == level and int(time()) - int(mktime((event['object'].last_timestamp + datetime.timedelta(hours=8)).timetuple())) <= 30:
                last_timestamp = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                content = MSG_TEMPLATE % (cluster_name, level, event['object'].metadata.namespace, event['object'].metadata.name, event['object'].message, event['object'].reason, last_timestamp)
                data = {"msgtype": "text", "at": {"atMobiles": [], "isAtAll": False}, "text": {"content": content}}
                if not send_ding(data, robot):
                    logging.error("POD发送钉钉告警失败！")
        except:
            logging.error("解析event数据异常！")

def main():
    logging.info("集群监控机器人开始工作...")

    if "CLUSTER_NAME" in os.environ:
        cluster_name = os.environ["CLUSTER_NAME"]
    else:
        logging.info("Please Set CLUSTER NAME....")
        sys.exit(1)

    if "DING_ROBOT" in os.environ:
        robot = os.environ["DING_ROBOT"]
    else:
        logging.info("Please Set DING ROBOT....")
        sys.exit(1)

    if "LEVEL" in os.environ:
        level = os.environ["LEVEL"]
    else:
        level = 'Warning'

    if "API_HOST" in os.environ:
        host = os.environ["API_HOST"]
    else:
        host = "https://kubernetes.default.svc.cluster.local"

    #try:
    #    with open('/run/secrets/kubernetes.io/serviceaccount/token') as file_object:
    #        token = file_object.read()
    #except:
    #    logging.info("read serviceaccount fail....")
    #    sys.exit(1)
        
    config.load_incluster_config()
    configuration = client.Configuration()
    #configuration.api_key['authorization'] = token
    #configuration.api_key_prefix['authorization'] = 'Bearer'
    #configuration.host = host
    configuration.verify_ssl = False
    v1 = client.CoreV1Api(client.ApiClient(configuration))

    pod = threading.Thread(target=pod_envet, args=(v1, level, cluster_name, robot))
    pod.setDaemon(True)
    pod.start()
    pod.join()


if __name__ == '__main__':
    main()

