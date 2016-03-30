# Copyright 2016 OpenStack Foundation
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

mks_group = cfg.OptGroup('mks', title='MKS Options')

mks_opts = [
    cfg.StrOpt('mksproxy_base_url',
               default='http://127.0.0.1:6090/',
               help='Location of MKS web console proxy, in the form '
                    '"http://127.0.0.1:6090/"'),
    cfg.BoolOpt('enabled',
                default=False,
                help='Enable MKS related features'),
    ]

ALL_MKS_OPTS = mks_opts


def register_opts(conf):
    conf.register_group(mks_group)
    conf.register_opts(ALL_MKS_OPTS, group = mks_group)


def list_opts():
    return {mks_group: ALL_MKS_OPTS}
