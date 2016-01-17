#!/bin/bash

virtualenv_activate="${1}"
source_path="${2}"
CURL="${3}"
GREP="${4}"
unset PYTHONPATH

source "${virtualenv_activate}"

girder-install web || exit 1

# Make sure that our grunt targets got built
webroot=$(girder-install web-root)
if [ ! -f "${webroot}/static/built/plugins/jobs/plugin.min.js" ] ; then
    echo "Error: grunt targets were not built correctly"
    exit 1
fi

# Start Girder server
export GIRDER_PORT=50202
python -m girder &> /dev/null &

# Ensure the server started
girder_pid=$!
sleep 1
if ! ps -p $girder_pid &> /dev/null; then
    echo "Error: Girder could not be started"
    exit 1
fi

# Loop until Girder is giving answers
timeout=0
until [ $timeout -eq 15 ]; do
    json=$("${CURL}" --connect-timeout 5 --max-time 5 --silent http://localhost:${GIRDER_PORT}/api/v1/system/version)
    if [ -n "$json" ]; then
        break
    fi
    timeout=$((timeout+1))
    sleep 1
done

# Do the real tests
"${CURL}" --max-time 5 --silent http://localhost:${GIRDER_PORT} | "${GREP}" "g-global-info-apiroot" > /dev/null
if [ $? -ne 0 ] ; then
    echo "Error: Failed to load main page"
    exit 1
fi

"${CURL}" --max-time 5 --silent http://localhost:${GIRDER_PORT}/api/v1 | "${GREP}" "swagger" > /dev/null
if [ $? -ne 0 ] ; then
    echo "Error: Failed to load Swagger docs"
    exit 1
fi

kill -9 %+
exit 0
