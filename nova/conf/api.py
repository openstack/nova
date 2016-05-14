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


auth_opts = [
    cfg.BoolOpt("api_rate_limit",
            default=False,
            help="""
Determines whether rate limiting for the API is per-user. This option is only
used by v2 API. Rate limiting is removed from v2.1 API.

* Possible values:

    True, False (default)

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.StrOpt("auth_strategy",
            default="keystone",
            choices=("keystone", "noauth2"),
            help="""
This determines the strategy to use for authentication: keystone or noauth2.
'noauth2' is designed for testing only, as it does no actual credential
checking. 'noauth2' provides administrative credentials only if 'admin' is
specified as the username.

* Possible values:

    Either 'keystone' (default) or 'noauth2'.

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.BoolOpt("use_forwarded_for",
            default=False,
            help="""
When True, the 'X-Forwarded-For' header is treated as the canonical remote
address. When False (the default), the 'remote_address' header is used.

You should only enable this if you have an HTML sanitizing proxy.

* Possible values:

    True, False (default)

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
]

metadata_opts = [
    cfg.StrOpt("config_drive_skip_versions",
            default=("1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 "
                     "2007-12-15 2008-02-01 2008-09-01"),
            help="""
When gathering the existing metadata for a config drive, the EC2-style metadata
is returned for all versions that don't appear in this option. As of the
Liberty release, the available versions are:

    1.0
    2007-01-19
    2007-03-01
    2007-08-29
    2007-10-10
    2007-12-15
    2008-02-01
    2008-09-01
    2009-04-04

The option is in the format of a single string, with each version separated by
a space.

* Possible values:

    Any string that represents zero or more versions, separated by spaces. The
    default is "1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 2007-12-15
    2008-02-01 2008-09-01".

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.StrOpt("vendordata_driver",
            default="nova.api.metadata.vendordata_json.JsonFileVendorData",
            deprecated_for_removal=True,
            help="""
DEPRECATED: When returning instance metadata, this is the class that is used
for getting vendor metadata when that class isn't specified in the individual
request. The value should be the full dot-separated path to the class to use.

* Possible values:

    Any valid dot-separated class path that can be imported. The default is
    'nova.api.metadata.vendordata_json.JsonFileVendorData'.

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.IntOpt("metadata_cache_expiration",
            default=15,
            help="""
This option is the time (in seconds) to cache metadata. When set to 0, metadata
caching is disabled entirely; this is generally not recommended for performance
reasons. Increasing this setting should improve response times of the metadata
API when under heavy load. Higher values may increase memory usage, and result
in longer times for host metadata changes to take effect.

* Possible values:

    Zero or any positive integer. The default is 15.

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
]

file_opt = cfg.StrOpt("vendordata_jsonfile_path",
        help="""
Cloud providers may store custom data in vendor data file that will then be
available to the instances via the metadata service, and to the rendering of
config-drive. The default class for this, JsonFileVendorData, loads this
information from a JSON file, whose path is configured by this option. If there
is no path set by this option, the class returns an empty dictionary.

* Possible values:

    Any string representing the path to the data file, or an empty string
    (default).

* Services that use this:

    ``nova-api``

* Related options:

    None
""")

osapi_opts = [
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='The maximum number of items returned in a single '
                    'response from a collection resource'),
    cfg.StrOpt('osapi_compute_link_prefix',
               help='Base URL that will be presented to users in links '
                    'to the OpenStack Compute API'),
    cfg.StrOpt('osapi_glance_link_prefix',
               help='Base URL that will be presented to users in links '
                    'to glance resources'),
]

allow_instance_snapshots_opt = cfg.BoolOpt('allow_instance_snapshots',
        default=True,
        help='Permit instance snapshot operations.')

# NOTE(edleafe): I would like to import the value directly from
# nova.compute.vm_states, but that creates a circular import. Since this value
# is not likely to be changed, I'm copy/pasting it here.
BUILDING = "building"  # VM only exists in DB
osapi_hide_opt = cfg.ListOpt('osapi_hide_server_address_states',
                 default=[BUILDING],
                 help='List of instance states that should hide network info')

fping_path_opt = cfg.StrOpt("fping_path",
                 default="/usr/sbin/fping",
                 help="Full path to fping.")

os_network_opts = [
    cfg.BoolOpt("enable_network_quota",
                default=False,
                help='Enables or disables quota checking for tenant '
                     'networks'),
    cfg.StrOpt('use_neutron_default_nets',
                     default="False",
                     help='Control for checking for default networks'),
    cfg.StrOpt('neutron_default_tenant_id',
                     default="default",
                     help='Default tenant id when creating neutron '
                          'networks'),
    cfg.IntOpt('quota_networks',
               default=3,
               help='Number of private networks allowed per project'),
]

enable_inst_pw_opt = cfg.BoolOpt('enable_instance_password',
                default=True,
                help='Enables returning of the instance password by the'
                     ' relevant server API calls such as create, rebuild'
                     ' or rescue, If the hypervisor does not support'
                     ' password injection then the password returned will'
                     ' not be correct')

ALL_OPTS = (auth_opts +
            metadata_opts +
            [file_opt] +
            osapi_opts +
            [allow_instance_snapshots_opt] +
            [osapi_hide_opt] +
            [fping_path_opt] +
            os_network_opts +
            [enable_inst_pw_opt])


def register_opts(conf):
    conf.register_opts(auth_opts)
    conf.register_opts(metadata_opts)
    conf.register_opt(file_opt)
    conf.register_opts(osapi_opts)
    conf.register_opt(allow_instance_snapshots_opt)
    conf.register_opt(osapi_hide_opt)
    conf.register_opt(fping_path_opt)
    conf.register_opts(os_network_opts)
    conf.register_opt(enable_inst_pw_opt)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
