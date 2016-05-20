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

internal_service_availability_zone = cfg.StrOpt(
     'internal_service_availability_zone',
      default='internal',
      help='The availability_zone to show internal services under')

default_availability_zone = cfg.StrOpt(
     'default_availability_zone',
      default='nova',
      help='Default compute node availability_zone')

ALL_OPTS = [internal_service_availability_zone,
            default_availability_zone]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
