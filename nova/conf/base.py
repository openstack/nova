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

monkey_patch = cfg.BoolOpt(
    'monkey_patch',
    default=False,
    help="""Determine if monkey patching should be applied.

Possible values:

* True: Functions specified in ``monkey_patch_modules`` will be patched.
* False: No monkey patching will occur.

Services which consume this:

* All

Interdependencies to other options:

* ``monkey_patch_modules``: This must have values set for this option to have
  any effect
""")

notify_decorator = 'nova.notifications.notify_decorator'

monkey_patch_modules = cfg.ListOpt(
    'monkey_patch_modules',
    default=[
        'nova.compute.api:%s' % (notify_decorator)
    ],
    help="""List of modules/decorators to monkey patch.

This option allows you to patch a decorator for all functions in specified
modules.

Possible values:

* nova.compute.api:nova.notifications.notify_decorator
* nova.api.ec2.cloud:nova.notifications.notify_decorator
* [...]

Interdependencies to other options:

* ``monkey_patch``: This must be set to ``True`` for this option to
  have any effect
""")


ALL_OPTS = [
    password_length,
    instance_usage_audit_period,
    use_rootwrap_daemon,
    rootwrap_config,
    tempdir,
    monkey_patch,
    monkey_patch_modules]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
