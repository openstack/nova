# Copyright (c) 2010 OpenStack Foundation
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

conductor_group = cfg.OptGroup(
    'conductor',
    title='Conductor Options')

use_local = cfg.BoolOpt(
    'use_local',
    default=False,
    help='DEPRECATED: Perform nova-conductor operations locally. '
         'This legacy mode was introduced to bridge a gap during '
         'the transition to the conductor service. It no longer '
         'represents a reasonable alternative for deployers. '
         'Removal may be as early as 14.0',
    deprecated_for_removal='True')

topic = cfg.StrOpt(
    'topic',
    default='conductor',
    help='The topic on which conductor nodes listen')

manager = cfg.StrOpt(
    'manager',
    default='nova.conductor.manager.ConductorManager',
    help='Full class name for the Manager for conductor')

workers = cfg.IntOpt(
    'workers',
    help='Number of workers for OpenStack Conductor service. '
         'The default will be the number of CPUs available.')

ALL_OPTS = [
    use_local,
    topic,
    manager,
    workers]


def register_opts(conf):
    conf.register_group(conductor_group)
    conf.register_opts(ALL_OPTS, group=conductor_group)


def list_opts():
    return {conductor_group: ALL_OPTS}
