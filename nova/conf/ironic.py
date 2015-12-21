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
    title='Ironic Options')

api_version = cfg.IntOpt(
    'api_version',
    default=1,
    help='Version of Ironic API service endpoint.')

api_endpoint = cfg.StrOpt(
    'api_endpoint',
    help='URL for Ironic API endpoint.')

admin_username = cfg.StrOpt(
    'admin_username',
    help='Ironic keystone admin name')

admin_password = cfg.StrOpt(
    'admin_password',
    secret=True,
    help='Ironic keystone admin password.')

admin_auth_token = cfg.StrOpt(
    'admin_auth_token',
    secret=True,
    deprecated_for_removal=True,
    help='Ironic keystone auth token.'
         'DEPRECATED: use admin_username, admin_password, and '
         'admin_tenant_name instead')

admin_url = cfg.StrOpt(
    'admin_url',
    help='Keystone public API endpoint.')

client_log_level = cfg.StrOpt(
    'client_log_level',
    deprecated_for_removal=True,
    help='Log level override for ironicclient. Set this in '
         'order to override the global "default_log_levels", '
         '"verbose", and "debug" settings. '
         'DEPRECATED: use standard logging configuration.')

admin_tenant_name = cfg.StrOpt(
    'admin_tenant_name',
    help='Ironic keystone tenant name.')

api_max_retries = cfg.IntOpt(
    'api_max_retries',
    default=60,
    help=('How many retries when a request does conflict. '
          'If <= 0, only try once, no retries.'))

api_retry_interval = cfg.IntOpt(
    'api_retry_interval',
    default=2,
    help='How often to retry in seconds when a request '
         'does conflict')

ALL_OPTS = [api_version,
            api_endpoint,
            admin_username,
            admin_password,
            admin_auth_token,
            admin_url,
            client_log_level,
            admin_tenant_name,
            api_max_retries,
            api_retry_interval]


def register_opts(conf):
    conf.register_group(ironic_group)
    conf.register_opts(ALL_OPTS, group=ironic_group)


def list_opts():
    # Because of bug 1395819 in oslo.config we cannot pass in the OptGroup.
    # As soon as this bug is fixed is oslo.config and Nova uses the
    # version which contains this fix, we can pass in the OptGroup instead
    # of its name. This allows the generation of the group help too.
    return {ironic_group.name: ALL_OPTS}
