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
    title='Conductor Options',
    help="""
Options under this group are used to define Conductor's communication,
which manager should be act as a proxy between computes and database,
and finally, how many worker processes will be used.
""",
)

ALL_OPTS = [
    cfg.StrOpt(
        'topic',
        default='conductor',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
There is no need to let users choose the RPC topic for all services - there
is little gain from this. Furthermore, it makes it really easy to break Nova
by using this option.
""",
        help="""
Topic exchange name on which conductor nodes listen.
"""),
    cfg.IntOpt(
        'workers',
        help="""
Number of workers for OpenStack Conductor service. The default will be the
number of CPUs available.
"""),
]

migrate_opts = [
    cfg.IntOpt(
        'migrate_max_retries',
        default=-1,
        min=-1,
        help="""
Number of times to retry live-migration before failing.

Possible values:

* If == -1, try until out of hosts (default)
* If == 0, only try once, no retries
* Integer greater than 0
"""),
]


def register_opts(conf):
    conf.register_group(conductor_group)
    conf.register_opts(ALL_OPTS, group=conductor_group)
    conf.register_opts(migrate_opts)


def list_opts():
    return {"DEFAULT": migrate_opts,
            conductor_group: ALL_OPTS}
