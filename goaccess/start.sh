#!/bin/sh
goaccess /srv/logs/proxy-host-*_access.log \
  --config-file=/srv/goaccess.conf \
  --real-time-html \
  --output=/srv/report/index.html \
  --ws-url=ws://localhost:7890 \
  --origin=http://localhost:8890 \
  --port=7890
#  --persist \
#  --restore \
 