from kubernetes import client, config, watch
import datetime
import json
import requests
import logging
import sys
import os
import threading
from time import mktime, time
import hashlib

POD_MSG_TEMPLATE = "### %s \n- Type:%s \n- Level:%s \n- Namespace:%s \n- Name:%s \n- Message:%s \n- Reason:%s \n- Timestamp:%s\n"
NODE_MSG_TEMPLATE = "### %s \n- Type:%s \n- Level:%s \n- Name:%s \n- Message:%s \n- Reason:%s \n- Timestamp:%s\n"

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

EVENT_DATA = {}

def save_es(cluster_name, type, event, es_host):
    cst_tz = timezone('Asia/Shanghai')
    now = datetime.datetime.now().replace(tzinfo=cst_tz)
    utctime = now.astimezone(utc)
    try:
        es = Elasticsearch(hosts=es_host)
    except:
        logging.error("初始化es失败")
    else:
        if type == 'event':
            try:
                doc = {}
                doc['Message'] = event['object'].message
                doc['Reason'] = event['object'].reason
                doc['Name'] = event['object'].metadata.name
                doc['Namespace'] = event['object'].metadata.namespace
                doc['Type'] = 'event'
                doc['Level'] = event['object'].type
                doc['ClusterName'] = cluster_name
                doc['Timestamp'] = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime(
                            '%Y-%m-%d %H:%M:%S')
                doc['timestamp'] = utctime
                es.index(index=cluster_name.lower(), doc_type="text", body=doc)
            except:
                logging.error("event保存es失败")
        else:
            try:
                conditions = event['object'].status.conditions
                for condition in conditions:
                    if (condition.type == 'Ready' and condition.status != 'True') or (
                            condition.type != 'Ready' and condition.status != 'False'):
                        doc = {}
                        doc['Message'] = condition.message
                        doc['Reason'] = condition.reason
                        doc['Name'] = event['object'].metadata.name
                        doc['Type'] = 'node'
                        doc['Level'] = 'Error'
                        doc['ClusterName'] = cluster_name
                        doc['Timestamp'] = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime(
                            '%Y-%m-%d %H:%M:%S')
                        doc['timestamp'] = utctime
                        es.index(index=cluster_name.lower(), doc_type="text", body=doc)
            except:
                logging.error("node事件保存es失败")
                

def get_md5(data):
    m1 = hashlib.md5()
    m1.update(data.encode("utf-8"))
    token = m1.hexdigest()
    return token


#消息收敛
def event_convergence(content, times, interval, last_time):
    md5_data = get_md5(content.replace(last_time, 'x'))
    #第一次出现需要告警
    if md5_data not in EVENT_DATA.keys():
        EVENT_DATA[md5_data] = {'times': 1, 'last_timestamp': int(time())}
        return True
    else:
        #第二次出现需要告警
        if EVENT_DATA[md5_data]['times'] == 1:
            EVENT_DATA[md5_data] = {'times': 2, 'last_timestamp': int(time())}
            return True
        else:
            #如果前面有第10次或者现在的时间隔上次发送的时间大于等于180秒则需要发送
            if EVENT_DATA[md5_data]['times'] >= times or int(time()) - EVENT_DATA[md5_data]['last_timestamp'] >= interval:
                EVENT_DATA[md5_data] = {'times': 1, 'last_timestamp': int(time())}
                return True
            else:
                EVENT_DATA[md5_data]['times'] = EVENT_DATA[md5_data]['times'] + 1
                logging.info("事件次数小于%s次，或者距离上次告警时间相差不到%s秒，故而忽略本次事件告警，消息内容：%s" % (times, interval, content))
                return False


def send_ding(data, robot):
    post_data = json.dumps(data).encode(encoding='UTF8')
    response = requests.post(robot, headers={'Content-Type': 'application/json; charset=utf-8'}, data=post_data)
    if response.status_code != 200:
        return False
    return True


def pod_event(v1, level, cluster_name, robot, pod_at_all, times, interval, es_host):
    logging.info("Pod事件监控子进程启动")
    w = watch.Watch()
    for event in w.stream(v1.list_event_for_all_namespaces):
        if es_host != '':
            save_es(cluster_name, 'event', event, es_host)
        try:
            if event['object'].type == level and int(time()) - int(
                    mktime((event['object'].last_timestamp + datetime.timedelta(hours=8)).timetuple())) <= 30:
                last_time = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime(
                    '%Y-%m-%d %H:%M:%S')
                content = POD_MSG_TEMPLATE % (
                '【' + cluster_name + '】 Pod事件监控', 'Pod', level, event['object'].metadata.namespace, event['object'].metadata.name,
                event['object'].message, event['object'].reason, last_time)
                if event_convergence(content, times, interval, last_time):
                    data = {"msgtype": "markdown", "at": {"atMobiles": [], "isAtAll": pod_at_all}, "markdown": {"title": cluster_name, "text": content}}
                    if not send_ding(data, robot):
                        logging.error("Pod发送钉钉告警失败！")
        except:
            logging.error("解析event数据异常！")


def node_event(v1, level, cluster_name, robot, node_at_all, es_host):
    logging.info("Node异常监控子进程启动")
    w = watch.Watch()
    for event in w.stream(v1.list_node):
        if es_host != '':
            save_es(cluster_name, 'node', event, es_host)
        try:
            conditions = event['object'].status.conditions
            for condition in conditions:
                last_time = (condition.last_heartbeat_time + datetime.timedelta(hours=8)).strftime(
                    '%Y-%m-%d %H:%M:%S')
                if (condition.type == 'Ready' and condition.status != 'True') or (
                        condition.type != 'Ready' and condition.status != 'False'):
                    content = NODE_MSG_TEMPLATE % (
                    '【' + cluster_name + '】 Node异常监控', 'Node', level, event['object'].metadata.name, condition.message, condition.reason,
                    last_time)
                    #Node异常告警不做消息收敛，需要及时处理
                    data = {"msgtype": "markdown", "at": {"atMobiles": [], "isAtAll": node_at_all},
                            "markdown": {"title": cluster_name, "text": content}}
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

    if "TIMES" in os.environ:
        times = int(os.environ["TIMES"])
    else:
        times = 15

    if "INTERVAL" in os.environ:
        interval = int(os.environ["INTERVAL"])
    else:
        interval = 300

    if "POD_AT_ALL" in os.environ:
        if os.environ["POD_AT_ALL"].lower() == 'true':
            pod_at_all = True
        else:
            pod_at_all = False
    else:
        pod_at_all = False

    if "NODE_AT_ALL" in os.environ:
        if os.environ["NODE_AT_ALL"].lower() == 'true':
            node_at_all = True
        else:
            node_at_all = False
    else:
        node_at_all = True
        
    if "ES_HOST" in os.environ:
        es_host = os.environ["ES_HOST"]
    else:
        es_host = ''

    config.load_incluster_config()
    configuration = client.Configuration()
    # configuration.host = host
    configuration.verify_ssl = False
    v1 = client.CoreV1Api(client.ApiClient(configuration))

    pod = threading.Thread(target=pod_event, args=(v1, level, cluster_name, robot, pod_at_all, times, interval, es_host))
    pod.setDaemon(True)
    pod.start()

    node = threading.Thread(target=node_event, args=(v1, 'Error', cluster_name, robot, node_at_all, es_host))
    node.setDaemon(True)
    node.start()

    node.join()


if __name__ == '__main__':
    main()
