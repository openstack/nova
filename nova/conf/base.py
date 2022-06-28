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
        default=512 * 1024 + 10,      # a little over 512 GB
        min=0,
        help="""
Instance memory usage identifying it as large VM

For a couple of operations, e.g. special settings when
spawning, we have to identify a large VM and handle them differently - even
differently than big VMs. Every VM having more or equal to this setting's
amount of RAM and less than bigvm_mb is a large VM.

See also: nova.utils.is_large_vm()
"""),
    cfg.IntOpt(
        'full_reservation_memory_mb',
        default=230 * 1024,      # 230 GiB
        help="""
Instance memory usage identifying a VM as needing memory reservations

VMs starting from this amount of memory will get their memory reserved. This
setting acts in addition to the flavor's CUSTOM_MEMORY_RESERVABLE_MB resource
definition. The flavor's setting takes precedence if set.

A negative value disables this feature.

See also: nova.utils.get_reserved_memory()
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
    cfg.StrOpt(
        "flavorid_alias_prefix",
        default="x_deprecated_",
        help="""
To enable gradual deprecation of old flavor names, the new flavors can specifiy
an extra_spec key 'catalog:alias', which adds the flavor to the flavor listing
a second time, only with a different flavorid, and the flavor name replaced by
the value of 'catalog:alias'.
The flavorid is changed by prepending this config value to the actual flavorid.
When the flavor with this flavorid is inspected or used to deploy a server, the
actual aliased flavor will be shown/used respectively.
The 'x_' prefix in the default sorts aliased flavors towards the end of the
flavor list (when sorting by flavorid, which is the API default). This
decreases visibility for aliased flavors.
"""),
    cfg.IntOpt(
        'bigvm_cluster_max_reservation_percent',
        default=50,
        help="""

Clusters/resource-providers with this percentage of memory reserved (of their
reservable memory, which can be less than total memory) are not used for
freeing up a host for spawning big VMs. Clusters found to reach that amount,
that already have a host freed, get their free host removed.

Compare the values of conf.vmware.memory_reservation_cluster_hosts_max_fail and
conf.vmware.memory_reservation_max_ratio_fallback to see how much of total
memory is actually reservable.
"""),
]


def register_opts(conf):
    conf.register_opts(base_options)


def list_opts():
    return {'DEFAULT': base_options}
