#!/usr/bin/env python
# Copyright (c) 2012, Cloudscaling
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
'''
find_unused_options.py

Compare the nova.conf file with the nova.conf.sample file to find any unused
options or default values in nova.conf
'''

from __future__ import print_function

import argparse
import os
import sys

sys.path.append(os.getcwd())
from oslo.config import iniparser


class PropertyCollecter(iniparser.BaseParser):
    def __init__(self):
        super(PropertyCollecter, self).__init__()
        self.key_value_pairs = {}

    def assignment(self, key, value):
        self.key_value_pairs[key] = value

    def new_section(self, section):
        pass

    @classmethod
    def collect_properties(cls, lineiter, sample_format=False):
        def clean_sample(f):
            for line in f:
                if line.startswith("#") and not line.startswith("# "):
                    line = line[1:]
                yield line
        pc = cls()
        if sample_format:
            lineiter = clean_sample(lineiter)
        pc.parse(lineiter)
        return pc.key_value_pairs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='''Compare the nova.conf
    file with the nova.conf.sample file to find any unused options or
    default values in nova.conf''')

    parser.add_argument('-c', action='store',
                        default='/etc/nova/nova.conf',
                        help='path to nova.conf\
                        (defaults to /etc/nova/nova.conf)')
    parser.add_argument('-s', default='./etc/nova/nova.conf.sample',
                        help='path to nova.conf.sample\
                        (defaults to ./etc/nova/nova.conf.sample')
    options = parser.parse_args()

    conf_file_options = PropertyCollecter.collect_properties(open(options.c))
    sample_conf_file_options = PropertyCollecter.collect_properties(
        open(options.s), sample_format=True)

    for k, v in sorted(conf_file_options.items()):
        if k not in sample_conf_file_options:
            print("Unused:", k)
    for k, v in sorted(conf_file_options.items()):
        if k in sample_conf_file_options and v == sample_conf_file_options[k]:
            print("Default valued:", k)
