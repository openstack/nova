#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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


import os
import subprocess


def execute_get_output(*command):
    """Execute and return stdout"""
    devnull = open(os.devnull, 'w')
    command = map(str, command)
    proc = subprocess.Popen(command, close_fds=True,
                            stdout=subprocess.PIPE, stderr=devnull)
    devnull.close()
    return proc.stdout.read().strip()


def execute(*command):
    """Execute without returning stdout"""
    devnull = open(os.devnull, 'w')
    command = map(str, command)
    proc = subprocess.Popen(command, close_fds=True,
                            stdout=subprocess.PIPE, stderr=devnull)
    devnull.close()
