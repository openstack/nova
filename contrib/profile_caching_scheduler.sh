#!/bin/bash
# Copyright (c) 2014 Rackspace Hosting
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# This runs a unit test that uses pycallgraph
# to profile the select_destinations call
# in the CachingScheduler
#
# For this script to work please run:
# python setup.py develop
# pip install -r requirements.txt
# pip install -r test-requirements.txt
# pip install pycallgraph
# export EVENTLET_NO_GREENDNS='yes'
#
BASEDIR=$(dirname $0)
TEST=$BASEDIR/../nova/tests/scheduler/test_caching_scheduler.py
echo
echo "Running this unit test file as a python script:"
echo $TEST

python $TEST

RESULTDIR=$(pwd)
echo
echo "For profiler result see: "
echo $RESULTDIR/scheduler.png
echo
