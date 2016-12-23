#!/usr/bin/env bash

TESTRARGS=$1

if [ $OS_TEST_PATH = './nova/tests/functional' ]; then
    blacklist_file=tests-functional-py3.txt
else
    blacklist_file=tests-py3.txt
fi

if [ -z "$TESTRARGS" ]; then
    ostestr --blacklist_file $blacklist_file
else
    ostestr -r "$TESTRARGS"
fi
