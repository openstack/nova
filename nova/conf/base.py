# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

from oslo_config import cfg


password_length = cfg.IntOpt(
    'password_length',
    default=12,
    help='Length of generated instance admin passwords')

instance_usage_audit_period = cfg.StrOpt(
    'instance_usage_audit_period',
    default='month',
    help='Time period to generate instance usages for.  '
         'Time period must be hour, day, month or year')

use_rootwrap_daemon = cfg.BoolOpt(
    'use_rootwrap_daemon',
    default=False,
    help="Start and use a daemon that can run the commands that "
    "need to be run with root privileges. This option is "
    "usually enabled on nodes that run nova compute "
    "processes")

rootwrap_config = cfg.StrOpt('rootwrap_config',
    default="/etc/nova/rootwrap.conf",
    help='Path to the rootwrap configuration file to use for '
    'running commands as root')

tempdir = cfg.StrOpt(
    'tempdir',
    help='Explicitly specify the temporary working directory')

ALL_OPTS = [
    password_length,
    instance_usage_audit_period,
    use_rootwrap_daemon,
    rootwrap_config,
    tempdir]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
