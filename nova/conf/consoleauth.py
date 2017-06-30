# Copyright (c) 2016 Intel, Inc.
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

consoleauth_group = cfg.OptGroup(
    name='consoleauth',
    title='Console auth options')

consoleauth_opts = [
    cfg.IntOpt('token_ttl',
        default=600,
        min=0,
        deprecated_name='console_token_ttl',
        deprecated_group='DEFAULT',
        help="""
The lifetime of a console auth token.

A console auth token is used in authorizing console access for a user.
Once the auth token time to live count has elapsed, the token is
considered expired.  Expired tokens are then deleted.
""")
]


def register_opts(conf):
    conf.register_group(consoleauth_group)
    conf.register_opts(consoleauth_opts, group=consoleauth_group)


def list_opts():
    return {consoleauth_group: consoleauth_opts}
