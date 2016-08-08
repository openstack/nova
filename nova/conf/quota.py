# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

quota_opts = [
    cfg.IntOpt('quota_instances',
               min=-1,
               default=10,
               help="""
The number of instances allowed per project.

Possible Values

 * 10 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_cores',
               min=-1,
               default=20,
               help="""
The number of instance cores or VCPUs allowed per project.

Possible values:

 * 20 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_ram',
               min=-1,
               default=50 * 1024,
               help="""
The number of megabytes of instance RAM allowed per project.

Possible values:

 * 51200 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_floating_ips',
               min=-1,
               default=10,
               help="""
The number of floating IPs allowed per project. Floating IPs are not allocated
to instances by default. Users need to select them from the pool configured by
the OpenStack administrator to attach to their instances.

Possible values:

 * 10 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_fixed_ips',
               min=-1,
               default=-1,
               help="""
The number of fixed IPs allowed per project (this should be at least the number
of instances allowed). Unlike floating IPs, fixed IPs are allocated dynamically
by the network component when instances boot up.

Possible values:

 * -1 (default) : treated as unlimited.
 * Any positive integer.
"""),
    cfg.IntOpt('quota_metadata_items',
               min=-1,
               default=128,
               help="""
The number of metadata items allowed per instance. User can associate metadata
while instance creation in the form of key-value pairs.

Possible values:

 * 128 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_injected_files',
               min=-1,
               default=5,
               help="""
The number of injected files allowed. It allow users to customize the
personality of an instance by injecting data into it upon boot. Only text
file injection is permitted. Binary or zip files won't work. During file
injection, any existing files that match specified files are renamed to include
.bak extension appended with a timestamp.

Possible values:

 * 5 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_injected_file_content_bytes',
               min=-1,
               default=10 * 1024,
               help="""
The number of bytes allowed per injected file.

Possible values:

 * 10240 (default) or any positive integer representing number of bytes.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_injected_file_path_length',
               min=-1,
               default=255,
               help="""
The maximum allowed injected file path length.

Possible values:

 * 255 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_security_groups',
               min=-1,
               default=10,
               help="""
The number of security groups per project.

Possible values:

 * 10 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_security_group_rules',
               min=-1,
               default=20,
               help="""
The number of security rules per security group. The associated rules in each
security group control the traffic to instances in the group.

Possible values:

 * 20 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_key_pairs',
               min=-1,
               default=100,
               help="""
The maximum number of key pairs allowed per user. Users can create at least one
key pair for each project and use the key pair for multiple instances that
belong to that project.

Possible values:

 * 100 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_server_groups',
               min=-1,
               default=10,
               help="""
Add quota values to constrain the number of server groups per project. Server
group used to control the affinity and anti-affinity scheduling policy for a
group of servers or instances. Reducing the quota will not affect any existing
group, but new servers will not be allowed into groups that have become over
quota.

Possible values:

 * 10 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('quota_server_group_members',
               min=-1,
               default=10,
               help="""
Add quota values to constrain the number of servers per server group.

Possible values:

 * 10 (default) or any positive integer.
 * -1 : treated as unlimited.
"""),
    cfg.IntOpt('reservation_expire',
               default=86400,
               help="""
The number of seconds until a reservation expires. It represents the time
period for invalidating quota reservations.

Possible values:

 * 86400 (default) or any positive integer representing number of seconds.
"""),
    cfg.IntOpt('until_refresh',
               min=0,
               default=0,
               help="""
The count of reservations until usage is refreshed. This defaults to 0 (off) to
avoid additional load but it is useful to turn on to help keep quota usage
up-to-date and reduce the impact of out of sync usage issues.

Possible values:

 * 0 (default) or any positive integer.
"""),
    cfg.IntOpt('max_age',
               min=0,
               default=0,
               help="""
The number of seconds between subsequent usage refreshes. This defaults to 0
(off) to avoid additional load but it is useful to turn on to help keep quota
usage up-to-date and reduce the impact of out of sync usage issues. Note that
quotas are not updated on a periodic task, they will update on a new
reservation if max_age has passed since the last reservation.

Possible values:

 * 0 (default) or any positive integer representing number of seconds.
"""),

# TODO(pumaranikar): Add a new config to select between the db_driver and
# the no_op driver using stevedoor.
    cfg.StrOpt('quota_driver',
               default='nova.quota.DbQuotaDriver',
               deprecated_for_removal=True,
               help="""
Provides abstraction for quota checks. Users can configure a specific
driver to use for quota checks.

Possible values:

 * nova.quota.DbQuotaDriver (default) or any string representing fully
   qualified class name.
"""),
    ]


def register_opts(conf):
    conf.register_opts(quota_opts)


# TODO(pumaranikar): We can consider moving these options to quota group
# and renaming them all to drop the quota bit.
def list_opts():
    return {'DEFAULT': quota_opts}
