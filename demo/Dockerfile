# Sandbox image — used by DockerSandbox.create()
# This is NOT the application image.
#
# Build (from this directory):  docker build -t cloudagent-sandbox:latest .
# Tag is hardcoded in app/sandbox.py as "cloudagent-sandbox:latest"

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN mkdir -p /workspace/out /workspace/repo

CMD ["/bin/bash"]
