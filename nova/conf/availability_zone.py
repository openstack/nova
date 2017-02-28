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
Availability zone for internal services.

This option determines the availability zone for the various internal nova
services, such as 'nova-scheduler', 'nova-conductor', etc.

Possible values:

* Any string representing an existing availability zone name.
"""),
    cfg.StrOpt('default_availability_zone',
        default='nova',
        help="""
Default availability zone for compute services.

This option determines the default availability zone for 'nova-compute'
services, which will be used if the service(s) do not belong to aggregates with
availability zone metadata.

Possible values:

* Any string representing an existing availability zone name.
"""),
    cfg.StrOpt('default_schedule_zone',
        help="""
Default availability zone for instances.

This option determines the default availability zone for instances, which will
be used when a user does not specify one when creating an instance. The
instance(s) will be bound to this availability zone for their lifetime.

Possible values:

* Any string representing an existing availability zone name.
* None, which means that the instance can move from one availability zone to
  another during its lifetime if it is moved from one compute node to another.
"""),
]


def register_opts(conf):
    conf.register_opts(availability_zone_opts)


def list_opts():
    return {'DEFAULT': availability_zone_opts}
