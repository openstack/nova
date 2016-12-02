# Copyright (c) 2013 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

availability_zone_opts = [
    cfg.StrOpt('internal_service_availability_zone',
        default='internal',
        help="""
This option specifies the name of the availability zone for the
internal services. Services like nova-scheduler, nova-network,
nova-conductor are internal services. These services will appear in
their own internal availability_zone.

Possible values:

* Any string representing an availability zone name
* 'internal' is the default value

"""),
    cfg.StrOpt('default_availability_zone',
        default='nova',
        help="""
Default compute node availability_zone.

This option determines the availability zone to be used when it is not
specified in the VM creation request. If this option is not set,
the default availability zone 'nova' is used.

Possible values:

* Any string representing an availability zone name
* 'nova' is the default value

""")
]


def register_opts(conf):
    conf.register_opts(availability_zone_opts)


def list_opts():
    return {'DEFAULT': availability_zone_opts}
