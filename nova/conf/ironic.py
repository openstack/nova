# Copyright 2015 Intel Corporation
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

ironic_group = cfg.OptGroup(
    'ironic',
    title='Ironic Options',
    help="""
Configuration options for Ironic driver (Bare Metal).
If using the Ironic driver following options must be set:
* admin_url
* admin_tenant_name
* admin_username
* admin_password
* api_endpoint
""")

ironic_options = [
    cfg.IntOpt('api_version',
        default=1,
        deprecated_for_removal=True,
        help="""
Version of Ironic API service endpoint.
This option is deprecated and setting the API version is not possible anymore.
"""),
    cfg.StrOpt(
        # TODO(raj_singh): Get this value from keystone service catalog
        'api_endpoint',
        sample_default='http://ironic.example.org:6385/',
        help='URL for the Ironic API endpoint'),
    cfg.StrOpt(
        'admin_username',
        help='Ironic keystone admin username'),
    cfg.StrOpt(
        'admin_password',
        secret=True,
        help='Ironic keystone admin password'),
    cfg.StrOpt(
        'admin_auth_token',
        secret=True,
        deprecated_for_removal=True,
        help="""
Ironic keystone auth token. This option is deprecated and
admin_username, admin_password and admin_tenant_name options
are used for authorization.
"""),
    cfg.StrOpt(
        # TODO(raj_singh): Change this option admin_url->auth_url to make it
        # consistent with other clients (Neutron, Cinder). It requires lot
        # of work in Ironic client to make this happen.
        'admin_url',
        help='Keystone public API endpoint'),
    cfg.StrOpt(
        'cafile',
        default=None,
        help="""
Path to the PEM encoded Certificate Authority file to be used when verifying
HTTPs connections with the Ironic driver. By default this option is not used.

Possible values:

* None - Default
* Path to the CA file
"""),
    cfg.StrOpt(
        'admin_tenant_name',
        help='Ironic keystone tenant name'),
    cfg.IntOpt(
        'api_max_retries',
        # TODO(raj_singh): Change this default to some sensible number
        default=60,
        min=0,
        help="""
The number of times to retry when a request conflicts.
If set to 0, only try once, no retries.

Related options:

* api_retry_interval
"""),
    cfg.IntOpt(
        'api_retry_interval',
        default=2,
        min=0,
        help="""
The number of seconds to wait before retrying the request.

Related options:

* api_max_retries
"""),
]


def register_opts(conf):
    conf.register_group(ironic_group)
    conf.register_opts(ironic_options, group=ironic_group)


def list_opts():
    return {ironic_group: ironic_options}
