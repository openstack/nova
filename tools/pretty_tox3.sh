#!/usr/bin/env bash

TESTRARGS=$1

if [ -z "$TESTRARGS" ]; then
    ostestr --blacklist_file tests-py3.txt
else
    ostestr -r "$TESTRARGS"
fi
