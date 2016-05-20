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


consoleauth_topic_opt = cfg.StrOpt('consoleauth_topic',
    default='consoleauth',
    help="""
This option allows you to change the message topic used by nova-consoleauth
service when communicating via the AMQP server. Nova Console Authentication
server authenticates nova consoles. Users can then access their instances
through VNC clients. The Nova API service uses a message queue to
communicate with nova-consoleauth to get a VNC console.

Possible Values:

  * 'consoleauth' (default) or Any string representing topic exchange name.
""")

console_token_ttl = cfg.IntOpt('console_token_ttl',
    default=600,
    help="""
This option indicates the lifetime of a console auth token. A console auth
token is used in authorizing console access for a user. Once the auth token
time to live count has elapsed, the token is considered expired. Expired
tokens are then deleted.

Possible values:

  * Any positive integer. The default is 600.
""")

CONSOLEAUTH_OPTS = [consoleauth_topic_opt, console_token_ttl]


def register_opts(conf):
    conf.register_opts(CONSOLEAUTH_OPTS)


def list_opts():
    return {'DEFAULT': CONSOLEAUTH_OPTS}
