FROM centos:latest
MAINTAINER Zalman Zhao(email:840912357@qq.com)
ENV REFRESHED_AT 9/5/2018 14:50

WORKDIR /opt

ADD ./Centos-7.repo /etc/yum.repos.d/CentOS-Base.repo

RUN yum -y install wget gcc make zlib* libffi-devel openssl-devel &&\
    yum clean all

RUN wget https://ops-files.oss-cn-hangzhou.aliyuncs.com/pkg/Python-3.7.0.tar.xz &&\
    tar xvf Python-3.7.0.tar.xz && \
    cd Python-3.7.0 && ./configure && make && make install && \
    rm -rf /opt/Python*

ENV TZ=Asia/Shanghai

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && pip3 install kubernetes elasticsearch pytz -i https://mirrors.aliyun.com/pypi/simple/

ADD ./eventer.py /opt

ENTRYPOINT python3 eventer.py
