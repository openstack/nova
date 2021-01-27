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

_DEFAULT_PASSWORD_SYMBOLS = ['23456789',  # Removed: 0,1
                             'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                             'abcdefghijkmnopqrstuvwxyz',  # Removed: l
                            ]

base_options = [
    cfg.IntOpt(
        'password_length',
        default=12,
        min=0,
        help='Length of generated instance admin passwords.'),
    cfg.IntOpt(
        'password_all_group_samples',
        default=1,
        min=0,
        help='''
How often should the symbols be sampled from all groups
to ensure the presence of all of them
* Zero: Purely random, so least predictable, but possibly not confirming to
  some password policies
* Any positive number: At least that many symbols will be from each of the
  classes. By default: lower-case, upper-case and numbers.

Interdependencies to other options:

* If ``password_length`` is smaller than ``password_all_group_samples`` times
  three (or more in case more groups are added to ``password_symbol_groups``),
  then the password will be cut off after ``password_length``, thereby possibly
  reducing the number of symbol classes in the generated password.
'''),
    cfg.MultiStrOpt(
        'password_symbol_groups',
        default=_DEFAULT_PASSWORD_SYMBOLS,
        help='''
List of symbols to use for passwords.
Default avoids visually confusing characters. (~6 bits per symbol)

The items in the list represents symbol groups, and from each of those groups
at least ``password_all_group_samples`` symbols are taken randomly.

Interdependencies to other options:
See ``password_additional_symbols`` for the interaction of the three values
``password_length``,  ``password_additional_symbols`` and
``password_symbol_groups``
'''),
    cfg.StrOpt(
        'instance_usage_audit_period',
        default='month',
        regex='^(hour|month|day|year)(@([0-9]+))?$',
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
    cfg.IntOpt(
        'default_green_pool_size',
        default=1000,
        min=100,
        help='''
The total number of coroutines that can be run via nova's default
greenthread pool concurrently, defaults to 1000, min value is 100.
'''),
    cfg.IntOpt(
        'bigvm_mb',
        default=1024 ** 2,      # 1 TB
        min=0,
        help="""
Instance memory usage identifying it as big VM

For a couple of operations, e.g. scheduling decisions and special settings when
spawning, we have to identify a big VM and handle them differently. Every VM
having more or equal to this setting's amount of RAM is a big VM.
"""),
    cfg.IntOpt(
        'largevm_mb',
        default=230 * 1024,      # 230 GB
        min=0,
        help="""
Instance memory usage identifying it as large VM

For a couple of operations, e.g. special settings when
spawning, we have to identify a large VM and handle them differently - even
differently than big VMs. Every VM having more or equal to this setting's
amount of RAM and less than bigvm_mb is a large VM.

See also: nova.utils.is_large_vm()
"""),
    cfg.StrOpt(
        'bigvm_deployment_rp_name_prefix',
        default='bigvm-deployment',
        help="""
This is the prefix used when creating resource-providers in placement for
handling spawning of VMs with special requirements like big VMs. The suffix of
the name will contain the nova-compute host. Prefix and suffix are joined by a
"-".
"""),
    cfg.IntOpt(
        'prepare_empty_host_for_spawning_interval',
        default=-1,
        help="""
Time in seconds between runs of the periodic task that frees up a host for
spawning VMs with special needs like big VMs.

This is disabled by default, because it only makes sense for some setups.
"""),
    cfg.IntOpt(
        'bigvm_cluster_max_usage_percent',
        default=80,
        help="""
Clusters/resource-provider with this much usage are not used for freeing up a
host for spawning (a big VM). Clusters found to reach that amount, that already
have a host freed, get their free host removed.
"""),
]

metrics_opts = [
    cfg.IntOpt('statsd_port',
               default=8125,
               help='Port of the statsd service.'),
    cfg.StrOpt('statsd_host',
               default='localhost',
               help='Host of the statsd service.'),
]


def register_opts(conf):
    conf.register_opts(base_options)
    conf.register_opts(metrics_opts)


def list_opts():
    return {'DEFAULT': base_options}
