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
               default=10,
               help='Number of instances allowed per project'),
    cfg.IntOpt('quota_cores',
               default=20,
               help='Number of instance cores allowed per project'),
    cfg.IntOpt('quota_ram',
               default=50 * 1024,
               help='Megabytes of instance RAM allowed per project'),
    cfg.IntOpt('quota_floating_ips',
               default=10,
               help='Number of floating IPs allowed per project'),
    cfg.IntOpt('quota_fixed_ips',
               default=-1,
               help='Number of fixed IPs allowed per project (this should be '
                    'at least the number of instances allowed)'),
    cfg.IntOpt('quota_metadata_items',
               default=128,
               help='Number of metadata items allowed per instance'),
    cfg.IntOpt('quota_injected_files',
               default=5,
               help='Number of injected files allowed'),
    cfg.IntOpt('quota_injected_file_content_bytes',
               default=10 * 1024,
               help='Number of bytes allowed per injected file'),
    cfg.IntOpt('quota_injected_file_path_length',
               default=255,
               help='Length of injected file path'),
    cfg.IntOpt('quota_security_groups',
               default=10,
               help='Number of security groups per project'),
    cfg.IntOpt('quota_security_group_rules',
               default=20,
               help='Number of security rules per security group'),
    cfg.IntOpt('quota_key_pairs',
               default=100,
               help='Number of key pairs per user'),
    cfg.IntOpt('quota_server_groups',
               default=10,
               help='Number of server groups per project'),
    cfg.IntOpt('quota_server_group_members',
               default=10,
               help='Number of servers per server group'),
    cfg.IntOpt('reservation_expire',
               default=86400,
               help='Number of seconds until a reservation expires'),
    cfg.IntOpt('until_refresh',
               default=0,
               help='Count of reservations until usage is refreshed. This '
                    'defaults to 0(off) to avoid additional load but it is '
                    'useful to turn on to help keep quota usage up to date '
                    'and reduce the impact of out of sync usage issues.'),
    cfg.IntOpt('max_age',
               default=0,
               help='Number of seconds between subsequent usage refreshes. '
                    'This defaults to 0(off) to avoid additional load but it '
                    'is useful to turn on to help keep quota usage up to date '
                    'and reduce the impact of out of sync usage issues. '
                    'Note that quotas are not updated on a periodic task, '
                    'they will update on a new reservation if max_age has '
                    'passed since the last reservation'),
    cfg.StrOpt('quota_driver',
               default='nova.quota.DbQuotaDriver',
               help='Default driver to use for quota checks'),
    ]


def register_opts(conf):
    conf.register_opts(quota_opts)


def list_opts():
    return {'DEFAULT': quota_opts}
