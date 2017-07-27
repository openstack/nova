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
# TODO(sfinucan): It is not possible to rename this to 'log_format'
# yet, as doing so would cause a conflict if '[DEFAULT] log_format'
# were used. When 'deprecated_group' is removed after Ocata, this
# should be changed.
    cfg.StrOpt(
        'wsgi_log_format',
        default='%(client_ip)s "%(request_line)s" status: %(status_code)s'
                ' len: %(body_length)s time: %(wall_seconds).7f',
        deprecated_group='DEFAULT',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
This option only works when running nova-api under eventlet, and
encodes very eventlet specific pieces of information. Starting in Pike
the preferred model for running nova-api is under uwsgi or apache
mod_wsgi.
""",
        help="""
It represents a python format string that is used as the template to generate
log lines. The following values can be formatted into it: client_ip,
date_time, request_line, status_code, body_length, wall_seconds.

This option is used for building custom request loglines when running
nova-api under eventlet. If used under uwsgi or apache, this option
has no effect.

Possible values:

* '%(client_ip)s "%(request_line)s" status: %(status_code)s'
  'len: %(body_length)s time: %(wall_seconds).7f' (default)
* Any formatted string formed by specific values.
"""),
    cfg.StrOpt(
        'secure_proxy_ssl_header',
        deprecated_group='DEFAULT',
        help="""
This option specifies the HTTP header used to determine the protocol scheme
for the original request, even if it was removed by a SSL terminating proxy.

Possible values:

* None (default) - the request scheme is not influenced by any HTTP headers
* Valid HTTP header, like HTTP_X_FORWARDED_PROTO

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
    cfg.StrOpt(
        'ssl_ca_file',
        deprecated_group='DEFAULT',
        help="""
This option allows setting path to the CA certificate file that should be used
to verify connecting clients.

Possible values:

* String representing path to the CA certificate file.

Related options:

* enabled_ssl_apis
"""),
    cfg.StrOpt(
        'ssl_cert_file',
        deprecated_group='DEFAULT',
        help="""
This option allows setting path to the SSL certificate of API server.

Possible values:

* String representing path to the SSL certificate.

Related options:

* enabled_ssl_apis
"""),
    cfg.StrOpt(
        'ssl_key_file',
        deprecated_group='DEFAULT',
        help="""
This option specifies the path to the file where SSL private key of API
server is stored when SSL is in effect.

Possible values:

* String representing path to the SSL private key.

Related options:

* enabled_ssl_apis
"""),
    cfg.IntOpt(
        'tcp_keepidle',
        min=0,
        default=600,
        deprecated_group='DEFAULT',
        help="""
This option sets the value of TCP_KEEPIDLE in seconds for each server socket.
It specifies the duration of time to keep connection active. TCP generates a
KEEPALIVE transmission for an application that requests to keep connection
active. Not supported on OS X.

Related options:

* keep_alive
"""),
    cfg.IntOpt(
        'default_pool_size',
        min=0,
        default=1000,
        deprecated_group='DEFAULT',
        deprecated_name='wsgi_default_pool_size',
        help="""
This option specifies the size of the pool of greenthreads used by wsgi.
It is possible to limit the number of concurrent connections using this
option.
"""),
    cfg.IntOpt(
        'max_header_line',
        min=0,
        default=16384,
        deprecated_group='DEFAULT',
        help="""
This option specifies the maximum line size of message headers to be accepted.
max_header_line may need to be increased when using large tokens (typically
those generated by the Keystone v3 API with big service catalogs).

Since TCP is a stream based protocol, in order to reuse a connection, the HTTP
has to have a way to indicate the end of the previous response and beginning
of the next. Hence, in a keep_alive case, all messages must have a
self-defined message length.
"""),
    cfg.BoolOpt(
        'keep_alive',
        default=True,
        deprecated_group='DEFAULT',
        deprecated_name='wsgi_keep_alive',
        help="""
This option allows using the same TCP connection to send and receive multiple
HTTP requests/responses, as opposed to opening a new one for every single
request/response pair. HTTP keep-alive indicates HTTP connection reuse.

Possible values:

* True : reuse HTTP connection.
* False : closes the client socket connection explicitly.

Related options:

* tcp_keepidle
"""),
    cfg.IntOpt(
        'client_socket_timeout',
        min=0,
        default=900,
        deprecated_group='DEFAULT',
        help="""
This option specifies the timeout for client connections' socket operations.
If an incoming connection is idle for this number of seconds it will be
closed. It indicates timeout on individual read/writes on the socket
connection. To wait forever set to 0.
"""),
]


def register_opts(conf):
    conf.register_group(wsgi_group)
    conf.register_opts(ALL_OPTS, group=wsgi_group)


def list_opts():
    return {wsgi_group: ALL_OPTS}
