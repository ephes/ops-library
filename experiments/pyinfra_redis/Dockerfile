FROM python:3.14-slim-bookworm
RUN rm -f /etc/apt/apt.conf.d/docker-clean && apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv dbus dpkg-dev python3-apt && apt-get clean
RUN apt-get install --download-only -y redis-server redis-tools && mkdir /packages && cp /var/cache/apt/archives/*.deb /packages/ && cd /packages && dpkg-scanpackages . /dev/null > Packages && rm -f /etc/apt/sources.list.d/* && printf 'deb [trusted=yes] file:/packages ./\n' > /etc/apt/sources.list && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/trial && /opt/trial/bin/pip install --no-cache-dir ansible-core==2.20.0 pyinfra==3.6.1
ENV PATH="/opt/trial/bin:${PATH}" PYINFRA_REDIS_TRIAL=1 container=docker
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
