#!/bin/bash
# This is used by run_tests.sh and tox.ini
python tools/hacking.py --doctest

# Until all these issues get fixed, ignore.
PEP8='python tools/hacking.py --ignore=E12,E711,E721,E712,N303,N403,N404'

EXCLUDE='--exclude=.venv,.git,.tox,dist,doc,*openstack/common*,*lib/python*'
EXCLUDE+=',*egg,build,./plugins/xenserver/networking/etc/xensource/scripts'
EXCLUDE+=',./plugins/xenserver/xenapi/etc/xapi.d/plugins'
${PEP8} ${EXCLUDE} .

${PEP8} --filename=nova* bin

SCRIPT_ROOT=$(echo $(dirname $(readlink -f "$0")) | sed s/\\/tools//)

SCRIPTS_PATH=${SCRIPT_ROOT}/plugins/xenserver/networking/etc/xensource/scripts
PYTHONPATH=${SCRIPTS_PATH} ${PEP8} ./plugins/xenserver/networking

# NOTE(sirp): Also check Dom0 plugins w/o .py extension
PLUGINS_PATH=${SCRIPT_ROOT}/plugins/xenserver/xenapi/etc/xapi.d/plugins
PYTHONPATH=${PLUGINS_PATH} ${PEP8} ./plugins/xenserver/xenapi \
    `find plugins/xenserver/xenapi/etc/xapi.d/plugins/ -type f -perm +111`

! pyflakes nova/ | grep "imported but unused"
