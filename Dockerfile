FROM debian:11-slim

RUN apt-get update && \
    apt-get install -y ffmpeg lsb-release gnupg curl tini && \
    rm -rf /var/lib/apt/lists/*

RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update && \
    apt-get install -y google-cloud-sdk

COPY entrypoint.sh /opt/entrypoint.sh

ENTRYPOINT ["tini", "--", "/opt/entrypoint.sh"]