# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

"""
Package-level global flags are defined here, the rest are defined
where they're used.
"""

import socket

from nova import vendor
from gflags import *

# This keeps pylint from barfing on the imports
FLAGS = FLAGS
DEFINE_string = DEFINE_string
DEFINE_integer = DEFINE_integer
DEFINE_bool = DEFINE_bool

# __GLOBAL FLAGS ONLY__
# Define any app-specific flags in their own files, docs at:
# http://code.google.com/p/python-gflags/source/browse/trunk/gflags.py#39

DEFINE_integer('s3_port', 3333, 's3 port')
DEFINE_integer('s3_internal_port', 3334, 's3 port')
DEFINE_string('s3_host', '127.0.0.1', 's3 host')
#DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')
DEFINE_string('compute_topic', 'compute', 'the topic compute nodes listen on')
DEFINE_string('storage_topic', 'storage', 'the topic storage nodes listen on')
DEFINE_bool('fake_libvirt', False,
                  'whether to use a fake libvirt or not')
DEFINE_bool('verbose', False, 'show debug output')
DEFINE_boolean('fake_rabbit', False, 'use a fake rabbit')
DEFINE_bool('fake_network', False, 'should we use fake network devices and addresses')
DEFINE_bool('fake_users', False, 'use fake users')
DEFINE_string('rabbit_host', 'localhost', 'rabbit host')
DEFINE_integer('rabbit_port', 5672, 'rabbit port')
DEFINE_string('rabbit_userid', 'guest', 'rabbit userid')
DEFINE_string('rabbit_password', 'guest', 'rabbit password')
DEFINE_string('rabbit_virtual_host', '/', 'rabbit virtual host')
DEFINE_string('control_exchange', 'nova', 'the main exchange to connect to')
DEFINE_string('ec2_url',
                'http://127.0.0.1:8773/services/Cloud',
                'Url to ec2 api server')

DEFINE_string('default_image',
                    'ami-11111',
                    'default image to use, testing only')
DEFINE_string('default_kernel',
                    'aki-11111',
                    'default kernel to use, testing only')
DEFINE_string('default_ramdisk',
                    'ari-11111',
                    'default ramdisk to use, testing only')
DEFINE_string('default_instance_type',
                    'm1.small',
                    'default instance type to use, testing only')

DEFINE_string('vpn_image_id', 'ami-CLOUDPIPE', 'AMI for cloudpipe vpn server')

# UNUSED
DEFINE_string('node_availability_zone',
                    'nova',
                    'availability zone of this node')
DEFINE_string('node_name',
                    socket.gethostname(),
                    'name of this node')

