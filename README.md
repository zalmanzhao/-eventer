# Kubernetes事件监控告警

### 常规事件的类型是Normal，异常类型的事件为Warning。也就是说，如果集群中出现了Warning类型的事件，那么可能就需要开发者接入进行甄别是否需要手动介入进行处理。

### 部署成功后30s，eventer即开始生效



## 部署步骤
### 1 build为docker镜像
```
docker build -t xxxx.xxx.com/eventer:v1.0.5 .
docker push xxxx.xxx.com/eventer:v1.0.5
```
### 2 在钉钉群生成钉钉机器人

### 3 修改eventer.yaml里面的参数
#### 参数说明
* --in-cluster 指定跑在集群内部
* --stdout 是否打印日志
* --cluster-name 自定义集群名称
* --ding-robot 钉钉机器人
#### 可选参数
* --level 日志级别  Normal或者Warning，默认为Warning
* --times 收敛告警次数 默认15次
* --interval 收敛告警间隔  默认300秒
* --event-at-all Pod事件告警是否@所有人  True 或者 False  默认为 False
* --node-at-all Node异常告警是否@所有人  True 或者 False 默认为 True
* --es-host 事件存入ES  为空时为不存

### 4 应用eventer.yaml
```
kubectl -f eventer.yaml
```
