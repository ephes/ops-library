FROM python:3.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/trial && /opt/trial/bin/pip install --no-cache-dir ansible-core==2.20.0 pyinfra==3.6.1
ENV PATH="/opt/trial/bin:${PATH}" PYINFRA_TRIAL_CONTAINER=1
WORKDIR /trial
