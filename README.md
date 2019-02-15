# Kubernetes事件监控告警

### 常规事件的类型是Normal，异常类型的事件为Warning。也就是说，如果集群中出现了Warning类型的事件，那么可能就需要开发者接入进行甄别是否需要手动介入进行处理。

### 部署成功后30s，eventer即开始生效

### 参数说明
* CLUSTER_NAME 自定义集群名称
* DING_ROBOT 钉钉机器人
* LEVEL 日志级别  Normal或者Warning，默认为Warning

## 部署步骤
### 1 build为docker镜像
```
docker build -t xxxx.xxx.com/eventer:v1.0.0 .
docker push xxxx.xxx.com/eventer:v1.0.0
```
### 2 在钉钉群生成钉钉机器人

### 3 修改eventer.yaml里面的参数
DING_ROBOT 和 CLUSTER_NAME

### 4 应用eventer.yaml
```
kubectl -f eventer.yaml
```
