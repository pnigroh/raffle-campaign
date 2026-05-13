FROM alpine:3.19

RUN apk add --no-cache \
        rclone \
        inotify-tools \
        bash \
        coreutils \
        tini

COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

ENV RCLONE_CONFIG=/config/rclone.conf
ENV WATCH_DIR=/data/media
ENV REMOTE=b2:raffle-media
ENV SYNC_INTERVAL=600

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
