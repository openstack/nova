#!/bin/bash
TOOLS=`dirname $0`
VENV=$TOOLS/../.nova-venv
source $VENV/bin/activate && $@
