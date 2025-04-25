# Copyright 2015 OpenStack Foundation
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

wsgi_group = cfg.OptGroup(
    'wsgi',
    title='WSGI Options',
    help='''
Options under this group are used to configure WSGI (Web Server Gateway
Interface). WSGI is used to serve API requests.
''',
)

ALL_OPTS = [
    cfg.StrOpt(
        'api_paste_config',
        default="api-paste.ini",
        deprecated_group='DEFAULT',
        help="""
This option represents a file name for the paste.deploy config for nova-api.

Possible values:

* A string representing file name for the paste.deploy config.
"""),
    cfg.StrOpt(
        'secure_proxy_ssl_header',
        deprecated_group='DEFAULT',
        deprecated_for_removal=True,
        deprecated_since='31.0.0',
        deprecated_reason="""
The functionality of this parameter is duplicate of the http_proxy_to_wsgi
middleware of oslo.middleware and will be completely replaced.
""",
        help="""
This option specifies the HTTP header used to determine the protocol scheme
for the original request, even if it was removed by a SSL terminating proxy.

Possible values:

* None (default) - the request scheme is not influenced by any HTTP headers
* Valid HTTP header, like ``HTTP_X_FORWARDED_PROTO``

WARNING: Do not set this unless you know what you are doing.

Make sure ALL of the following are true before setting this (assuming the
values from the example above):

* Your API is behind a proxy.
* Your proxy strips the X-Forwarded-Proto header from all incoming requests.
  In other words, if end users include that header in their requests, the proxy
  will discard it.
* Your proxy sets the X-Forwarded-Proto header and sends it to API, but only
  for requests that originally come in via HTTPS.

If any of those are not true, you should keep this setting set to None.
"""),
]


def register_opts(conf):
    conf.register_group(wsgi_group)
    conf.register_opts(ALL_OPTS, group=wsgi_group)


def list_opts():
    return {wsgi_group: ALL_OPTS}
