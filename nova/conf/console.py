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

console_group = cfg.OptGroup('console',
    title='Console Options',
    help="""
Options under this group allow to tune the configuration of the console proxy
service.

Note: in configuration of every compute is a ``console_host`` option,
which allows to select the console proxy service to connect to.
""")

console_opts = [
    cfg.ListOpt('allowed_origins',
        default=[],
        deprecated_group='DEFAULT',
        deprecated_name='console_allowed_origins',
        help="""
Adds list of allowed origins to the console websocket proxy to allow
connections from other origin hostnames.
Websocket proxy matches the host header with the origin header to
prevent cross-site requests. This list specifies if any there are
values other than host are allowed in the origin header.

Possible values:

* A list where each element is an allowed origin hostnames, else an empty list
"""),
    cfg.StrOpt('ssl_ciphers',
        help="""
OpenSSL cipher preference string that specifies what ciphers to allow for TLS
connections from clients.  For example::

    ssl_ciphers = "kEECDH+aECDSA+AES:kEECDH+AES+aRSA:kEDH+aRSA+AES"

See the man page for the OpenSSL `ciphers` command for details of the cipher
preference string format and allowed values::

    https://www.openssl.org/docs/man1.1.0/man1/ciphers.html

Related options:

* [DEFAULT] cert
* [DEFAULT] key
"""),
    cfg.StrOpt('ssl_minimum_version',
        default='default',
        choices=[
        # These values must align with SSL_OPTIONS in
        # websockify/websocketproxy.py
            ('default', 'Use the underlying system OpenSSL defaults'),
            ('tlsv1_1',
             'Require TLS v1.1 or greater for TLS connections'),
            ('tlsv1_2',
             'Require TLS v1.2 or greater for TLS connections'),
            ('tlsv1_3',
             'Require TLS v1.3 or greater for TLS connections'),
        ],
        help="""
Minimum allowed SSL/TLS protocol version.

Related options:

* [DEFAULT] cert
* [DEFAULT] key
"""),
]


def register_opts(conf):
    conf.register_group(console_group)
    conf.register_opts(console_opts, group=console_group)


def list_opts():
    return {
        console_group: console_opts,
    }
