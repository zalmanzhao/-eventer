import kubernetes
import datetime
import json
import requests
import logging
import sys
import queue
import signal
import threading
import argparse
from time import mktime, time
import hashlib
import urllib3
from elasticsearch import Elasticsearch, ConnectionTimeout

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WATCH_TIMEOUT = 60
POD_MSG_TEMPLATE = "### %s \n- Type:%s \n- Level:%s \n- Namespace:%s \n- Name:%s \n- Message:%s \n- Reason:%s \n- Timestamp:%s\n"
NODE_MSG_TEMPLATE = "### %s \n- Type:%s \n- Level:%s \n- Name:%s \n- Message:%s \n- Reason:%s \n- Timestamp:%s\n"

EVENT_DATA = {}


# 消息收敛
def event_convergence(content, times, interval, last_time):
    m1 = hashlib.md5()
    m1.update((content.replace(last_time, 'x')).encode("utf-8"))
    md5_data = m1.hexdigest()
    # 第一次出现需要告警
    if md5_data not in EVENT_DATA.keys():
        EVENT_DATA[md5_data] = {'times': 1, 'last_timestamp': int(time())}
        return True
    else:
        # 第二次出现需要告警
        if EVENT_DATA[md5_data]['times'] == 1:
            EVENT_DATA[md5_data] = {'times': 2, 'last_timestamp': int(time())}
            return True
        else:
            # 如果前面有第10次或者现在的时间隔上次发送的时间大于等于180秒则需要发送
            if EVENT_DATA[md5_data]['times'] >= times or int(time()) - EVENT_DATA[md5_data]['last_timestamp'] >= interval:
                EVENT_DATA[md5_data] = {'times': 1, 'last_timestamp': int(time())}
                return True
            else:
                EVENT_DATA[md5_data]['times'] = EVENT_DATA[md5_data]['times'] + 1
                logging.error("事件次数小于%s次，或者距离上次告警时间相差不到%s秒，故而忽略本次事件告警，消息内容：%s" % (times, interval, content))
                return False


def print_handler(event):
    if event['object'].kind == 'Event':
        logging.error('STDOUT ' + (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') + ' ' + event['object'].metadata.resource_version + ' ' + event['object'].metadata.name + ' ' + event['object'].message + ' ' + str(datetime.datetime.now()))
    else:
        logging.error('STDOUT ' +event['object'].metadata.resource_version + ' ' + event['object'].metadata.name + ' ' + str(datetime.datetime.now()))


class EventWatcherThread(threading.Thread):
    def __init__(self, queue):
        super().__init__(daemon=True)
        self.queue = queue
        self.resource_version = 0

    def run(self):
        try:
            return self._run()
        except Exception as e:
            e.thread = self
            self.queue.put(e)
            raise e

    def _run(self):
        while True:
            start_time = datetime.datetime.now()
            try:
                self._watch(since_time=start_time)
            except urllib3.exceptions.ReadTimeoutError:
                logging.error('EventWatcher timeout')
            else:
                logging.error('EventWatcher connection closed')

    def _watch(self, since_time):
        logging.error('Event Watching events since %s', since_time)

        w = kubernetes.watch.Watch()
        configuration = kubernetes.client.Configuration()
        configuration.verify_ssl = False
        v1 = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient(configuration))

        for event in w.stream(v1.list_event_for_all_namespaces, resource_version=self.resource_version, _request_timeout=WATCH_TIMEOUT):
            self.resource_version = event['object'].metadata.resource_version
            self.queue.put(event)


class NodeWatcherThread(threading.Thread):
    def __init__(self, queue):
        super().__init__(daemon=True)
        self.queue = queue
        self.resource_version = 0

    def run(self):
        try:
            return self._run()
        except Exception as e:
            e.thread = self
            self.queue.put(e)
            raise e

    def _run(self):
        while True:
            start_time = datetime.datetime.now()
            try:
                self._watch(since_time=start_time)
            except urllib3.exceptions.ReadTimeoutError:
                logging.error('NodeWatcher timeout')
            else:
                logging.error('NodeWatcher connection closed')

    def _watch(self, since_time):
        logging.error('Node Watching events since %s', since_time)

        w = kubernetes.watch.Watch()
        configuration = kubernetes.client.Configuration()
        configuration.verify_ssl = False
        v1 = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient(configuration))

        for event in w.stream(v1.list_node, resource_version=self.resource_version, _request_timeout=WATCH_TIMEOUT):
            self.resource_version = event['object'].metadata.resource_version
            self.queue.put(event)


class RobotHandler:
    def __init__(self, cluster_name, level, ding_url, event_at_all, node_at_all):
        self.cluster_name = cluster_name
        self.level = level
        self.ding_url = ding_url
        self.event_at_all = event_at_all
        self.node_at_all = node_at_all

    def __call__(self, event):
        if event['object'].kind == 'Event':
            if self.level == event['object'].type and int(time()) - int(mktime((event['object'].last_timestamp + datetime.timedelta(hours=8)).timetuple())) <= 30:
                last_time = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                content = POD_MSG_TEMPLATE % ('【' + self.cluster_name + '】 Event事件监控', 'Pod', self.level, event['object'].metadata.namespace, event['object'].metadata.name, event['object'].message, event['object'].reason, last_time)
                if event_convergence(content, 10, 180, last_time):
                    data = {"msgtype": "markdown", "at": {"atMobiles": [], "isAtAll": self.event_at_all}, "markdown": {"title": self.cluster_name, "text": content}}
                    post_data = json.dumps(data).encode(encoding='UTF8')
                    requests.post(self.ding_url, headers={'Content-Type': 'application/json; charset=utf-8'}, data=post_data)
            else:
                logging.error('丢弃 ' + (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') + ' ' + event['object'].type + event['object'].metadata.resource_version + ' ' + event['object'].metadata.name + ' ' + event['object'].message + ' ' + str(datetime.datetime.now()))
        else:
            conditions = event['object'].status.conditions
            for condition in conditions:
                last_time = (condition.last_heartbeat_time + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                if (condition.type == 'Ready' and condition.status != 'True') or (condition.type != 'Ready' and condition.status != 'False'):
                    content = NODE_MSG_TEMPLATE % ('【' + self.cluster_name + '】 Node异常监控', 'Node', 'Error', event['object'].metadata.name, condition.message, condition.reason, last_time)
                    # Node异常告警不做消息收敛，需要及时处理
                    data = {"msgtype": "markdown", "at": {"atMobiles": [], "isAtAll": self.node_at_all}, "markdown": {"title": self.cluster_name, "text": content}}
                    post_data = json.dumps(data).encode(encoding='UTF8')
                    requests.post(self.ding_url, headers={'Content-Type': 'application/json; charset=utf-8'}, data=post_data)


class EsHandler:
    def __init__(self, cluster_name, es_host):
        self.cluster_name = cluster_name
        try:
            self.es = Elasticsearch(hosts=es_host)
            self.es.index
        except:
            self.es = False
            logging.error("初始化es失败")

    def __call__(self, event):
        if not self.es:
            return False
        if event['object'].kind == 'Event':
            doc = {}
            doc['Message'] = event['object'].message
            doc['Reason'] = event['object'].reason
            doc['Name'] = event['object'].metadata.name
            doc['Namespace'] = event['object'].metadata.namespace
            doc['Type'] = 'Event'
            doc['Level'] = event['object'].type
            doc['ClusterName'] = self.cluster_name
            doc['Timestamp'] = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
            doc['timestamp'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000+0800")
            try:
                self.es.index(index=self.cluster_name.lower(), doc_type="text", body=doc)
            except ConnectionTimeout:
                logging.error("连接ES超时！")
            except:
                logging.error("Event事件保存ES失败！")
        else:
            conditions = event['object'].status.conditions
            for condition in conditions:
                if (condition.type == 'Ready' and condition.status != 'True') or (condition.type != 'Ready' and condition.status != 'False'):
                    doc = {}
                    doc['Message'] = condition.message
                    doc['Reason'] = condition.reason
                    doc['Name'] = event['object'].metadata.name
                    doc['Type'] = 'Node'
                    doc['Level'] = 'Error'
                    doc['ClusterName'] = self.cluster_name
                    doc['Timestamp'] = (event['object'].last_timestamp + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                    doc['timestamp'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000+0800")
                    try:
                        self.es.index(index=self.cluster_name.lower(), doc_type="text", body=doc)
                    except ConnectionTimeout:
                        logging.error("连接ES超时！")
                    except:
                        logging.error("Node事件保存ES失败！")


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--in-cluster', action='store_true', help='configure with in cluster kubeconfig')
    arg_parser.add_argument('--stdout', action='store_true', help='print events to stdout')
    arg_parser.add_argument('--log-level', default='WARNING')
    arg_parser.add_argument('--level', default='Warning')
    arg_parser.add_argument('--ding-robot', help='send events to ding ding robot')
    arg_parser.add_argument('--cluster-name', default='K8S集群')
    arg_parser.add_argument('--times', default=10)
    arg_parser.add_argument('--interval', default=180)
    arg_parser.add_argument('--event-at-all', default=False)
    arg_parser.add_argument('--node-at-all', default=True)
    arg_parser.add_argument('--es-host', default='')

    logging.error("集群监控机器人开始工作...")

    args = arg_parser.parse_args()
    logging.basicConfig(format='%(levelname)s: %(message)s', level=args.log_level)

    if args.in_cluster:
        kubernetes.config.load_incluster_config()
    else:
        kubernetes.config.load_kube_config()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    q = queue.Queue()

    event = EventWatcherThread(q)
    event.start()

    node = NodeWatcherThread(q)
    node.start()

    handlers = []

    if args.stdout:
        handlers.append(print_handler)
    if args.ding_robot:
        handlers.append(RobotHandler(args.cluster_name, args.level, args.ding_robot, args.event_at_all, args.node_at_all))
    if args.es_host:
        handlers.append(EsHandler(args.cluster_name, args.es_host))

    while True:
        event = q.get()

        if isinstance(event, Exception):
            event.thread.join()
            sys.exit(1)

        for handle in handlers:
            handle(event)

def shutdown(signum, frame):
    logging.error("Shutting down")
    sys.exit(0)

if __name__ == '__main__':
    main()
