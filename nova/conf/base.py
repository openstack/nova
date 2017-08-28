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

base_options = [
    cfg.IntOpt(
        'password_length',
        default=12,
        min=0,
        help='Length of generated instance admin passwords.'),
    cfg.StrOpt(
        'instance_usage_audit_period',
        default='month',
        regex='(hour|month|day|year)(@([0-9]+))?',
        help='''
Time period to generate instance usages for. It is possible to define optional
offset to given period by appending @ character followed by a number defining
offset.

Possible values:

*  period, example: ``hour``, ``day``, ``month` or ``year``
*  period with offset, example: ``month@15`` will result in monthly audits
   starting on 15th day of month.
'''),
    cfg.BoolOpt(
        'use_rootwrap_daemon',
        default=False,
        help='''
Start and use a daemon that can run the commands that need to be run with
root privileges. This option is usually enabled on nodes that run nova compute
processes.
'''),
    cfg.StrOpt(
        'rootwrap_config',
        default="/etc/nova/rootwrap.conf",
        help='''
Path to the rootwrap configuration file.

Goal of the root wrapper is to allow a service-specific unprivileged user to
run a number of actions as the root user in the safest manner possible.
The configuration file used here must match the one defined in the sudoers
entry.
'''),
    cfg.StrOpt(
        'tempdir',
        help='Explicitly specify the temporary working directory.'),
    cfg.BoolOpt(
        'monkey_patch',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason="""
Monkey patching nova is not tested, not supported, and is a barrier
for interoperability.
""",
        help="""
Determine if monkey patching should be applied.

Related options:

* ``monkey_patch_modules``: This must have values set for this option to
  have any effect
"""),
    cfg.ListOpt(
        'monkey_patch_modules',
        default=['nova.compute.api:nova.notifications.notify_decorator'],
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason="""
Monkey patching nova is not tested, not supported, and is a barrier
for interoperability.
""",
        help="""
List of modules/decorators to monkey patch.

This option allows you to patch a decorator for all functions in specified
modules.

Possible values:

* nova.compute.api:nova.notifications.notify_decorator
* [...]

Related options:

* ``monkey_patch``: This must be set to ``True`` for this option to
  have any effect
"""),
]


def register_opts(conf):
    conf.register_opts(base_options)


def list_opts():
    return {'DEFAULT': base_options}
