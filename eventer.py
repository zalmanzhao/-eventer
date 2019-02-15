from kubernetes import client, config, watch
import datetime
import json
import requests
import logging
import sys
import os
import threading
from time import mktime, time

POD_MSG_TEMPLATE = "%s\nType:%s \nLevel:%s \nNamespace:%s \nName:%s \nMessage:%s \nReason: %s \nTimestamp:%s"
NODE_MSG_TEMPLATE = "%s\nType:%s \nLevel:%s \nName:%s \nMessage:%s \nReason: %s \nTimestamp:%s"

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def send_ding(data, robot):
    post_data = json.dumps(data).encode(encoding='UTF8')
    response = requests.post(robot, headers={'Content-Type': 'application/json; charset=utf-8'}, data=post_data)
    if response.status_code != 200:
        return False
    return True

def pod_envet(v1, level, cluster_name, robot):
    logging.info("Pod事件监控子进程启动")
    w = watch.Watch()
    for event in w.stream(v1.list_event_for_all_namespaces):
        try:
            if event['object'].type == level and int(time()) - int(mktime((event['object'].last_timestamp + datetime.timedelta(hours=8)).timetuple())) <= 30:
                last_timestamp = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                content = POD_MSG_TEMPLATE % (cluster_name, 'Pod', level, event['object'].metadata.namespace, event['object'].metadata.name, event['object'].message, event['object'].reason, last_timestamp)
                data = {"msgtype": "text", "at": {"atMobiles": [], "isAtAll": False}, "text": {"content": content}}
                if not send_ding(data, robot):
                    logging.error("Pod发送钉钉告警失败！")
        except:
            logging.error("解析event数据异常！")


def node_envet(v1, level, cluster_name, robot):
    logging.info("Node异常监控子进程启动")
    w = watch.Watch()
    for event in w.stream(v1.list_node):
        try:
            conditions = event['object'].status.conditions
            for condition in conditions:
                last_timestamp = (condition.last_heartbeat_time + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                if (condition.type == 'Ready' and condition.status != 'True') or (condition.type != 'Ready' and condition.status != 'False'):
                    content = NODE_MSG_TEMPLATE % (cluster_name, 'Node', level, event['object'].metadata.name, condition.message, condition.reason, last_timestamp)
                    data = {"msgtype": "text", "at": {"atMobiles": [], "isAtAll": False}, "text": {"content": content}}
                    if not send_ding(data, robot):
                        logging.error("Node发送钉钉告警失败！")
        except:
            logging.error("解析Node数据异常！")

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

    node = threading.Thread(target=node_envet, args=(v1, 'Error', cluster_name, robot))
    node.setDaemon(True)
    node.start()
    
    node.join()


if __name__ == '__main__':
    main()

