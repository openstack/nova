#!/usr/bin/env bash

set -o pipefail

TESTRARGS=$1
python setup.py testr --slowest --testr-args="--subunit $TESTRARGS" | $(dirname $0)/subunit-trace.py -f
