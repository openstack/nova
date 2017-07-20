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

mks_group = cfg.OptGroup('mks',
                         title='MKS Options',
                         help="""
Nova compute node uses WebMKS, a desktop sharing protocol to provide
instance console access to VM's created by VMware hypervisors.

Related options:
Following options must be set to provide console access.
* mksproxy_base_url
* enabled
""")

mks_opts = [
    cfg.URIOpt('mksproxy_base_url',
               schemes=['http', 'https'],
               default='http://127.0.0.1:6090/',
               help="""
Location of MKS web console proxy

The URL in the response points to a WebMKS proxy which
starts proxying between client and corresponding vCenter
server where instance runs. In order to use the web based
console access, WebMKS proxy should be installed and configured

Possible values:

* Must be a valid URL of the form:``http://host:port/`` or
  ``https://host:port/``
"""),
    cfg.BoolOpt('enabled',
                default=False,
                help="""
Enables graphical console access for virtual machines.
"""),
]


def register_opts(conf):
    conf.register_group(mks_group)
    conf.register_opts(mks_opts, group=mks_group)


def list_opts():
    return {mks_group: mks_opts}
