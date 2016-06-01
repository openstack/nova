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
            deprecated_for_removal=True,
            deprecated_group="DEFAULT",
            help="""
*DEPRECATED*

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
    cfg.IntOpt("osapi_max_limit",
            default=1000,
            help="""
As a query can potentially return many thousands of items, you can limit the
maximum number of items in a single response by setting this option.

* Possible values:

    Any positive integer. Default is 1000.

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.StrOpt("osapi_compute_link_prefix",
            help="""
This string is prepended to the normal URL that is returned in links to the
OpenStack Compute API. If it is empty (the default), the URLs are returned
unchanged.

* Possible values:

    Any string, including an empty string (the default).

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
    cfg.StrOpt("osapi_glance_link_prefix",
            help="""
This string is prepended to the normal URL that is returned in links to Glance
resources. If it is empty (the default), the URLs are returned unchanged.

* Possible values:

    Any string, including an empty string (the default).

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
]

allow_instance_snapshots_opt = cfg.BoolOpt("allow_instance_snapshots",
        default=True,
        help="""
Operators can turn off the ability for a user to take snapshots of their
instances by setting this option to False. When disabled, any attempt to take a
snapshot will result in a HTTP 400 response ("Bad Request").

* Possible values:

    True (default), False

* Services that use this:

    ``nova-api``

* Related options:

    None
""")

# NOTE(edleafe): I would like to import the value directly from
# nova.compute.vm_states, but that creates a circular import. Since this value
# is not likely to be changed, I'm copy/pasting it here.
BUILDING = "building"  # VM only exists in DB
osapi_hide_opt = cfg.ListOpt('osapi_hide_server_address_states',
        default=[BUILDING],
        help="""
This option is a list of all instance states for which network address
information should not be returned from the API.

* Possible values:

    A list of strings, where each string is a valid VM state, as defined in
    nova/compute/vm_states.py. As of the Newton release, they are:

    * "active"
    * "building"
    * "paused"
    * "suspended"
    * "stopped"
    * "rescued"
    * "resized"
    * "soft-delete"
    * "deleted"
    * "error"
    * "shelved"
    * "shelved_offloaded"

    The default value is ["building"].

* Services that use this:

    ``nova-api``

* Related options:

    None
""")

fping_path_opt = cfg.StrOpt("fping_path",
        default="/usr/sbin/fping",
        help="""
The full path to the fping binary.

* Possible values:

    Any string representing a valid file path. The default is
    "/usr/sbin/fping".

* Services that use this:

    ``nova-api``

* Related options:

    None
""")

os_network_opts = [
    cfg.BoolOpt("enable_network_quota",
            default=False,
            help="""
This option is used to enable or disable quota checking for tenant networks.

* Services that use this:

    ``nova-api``

Possible values:

    True, False (default)

* Related options:

    quota_networks
"""),
    cfg.BoolOpt('use_neutron_default_nets',
            default=False,
            help="""
When "True" (note that this is a string value, not a boolean), the
TenantNetworkController will query the Neutron API to get the default networks
to use.

* Services that use this:

    ``nova-api``

Possible values:

    True, False (default)

* Related options:

    neutron_default_tenant_id
"""),
    cfg.StrOpt('neutron_default_tenant_id',
            default="default",
            help="""
When getting the default network from the Neutron API, this is the tenant ID
(also referred in some places as the 'project ID') to use. The default is the
string 'default'.

* Services that use this:

    ``nova-api``

Possible values:

    A string representing a valid tenant ID

* Related options:

    use_neutron_default_nets
"""),
    cfg.IntOpt('quota_networks',
            default=3,
            help="""
This option controls the number of private networks that can be created per
project (or per tenant).

* Services that use this:

    ``nova-api``

Possible values:

    Any positive integer. The default is 3.

* Related options:

    enable_network_quota
"""),
]

enable_inst_pw_opt = cfg.BoolOpt('enable_instance_password',
        default=True,
        help="""
Enables returning of the instance password by the relevant server API calls
such as create, rebuild, evacuate, or rescue. If the hypervisor does not
support password injection, then the password returned will not be correct, so
if your hypervisor does not support password injection, set this to False.

* Services that use this:

    ``nova-api``

Possible values:

    True (default), False

* Related options:

    None
""")

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
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
