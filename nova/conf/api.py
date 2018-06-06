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

api_group = cfg.OptGroup('api',
    title='API options',
    help="""
Options under this group are used to define Nova API.
""")

auth_opts = [
    cfg.StrOpt("auth_strategy",
        default="keystone",
        choices=("keystone", "noauth2"),
        deprecated_group="DEFAULT",
        help="""
This determines the strategy to use for authentication: keystone or noauth2.
'noauth2' is designed for testing only, as it does no actual credential
checking. 'noauth2' provides administrative credentials only if 'admin' is
specified as the username.
"""),
    cfg.BoolOpt("use_forwarded_for",
        default=False,
        deprecated_group="DEFAULT",
        help="""
When True, the 'X-Forwarded-For' header is treated as the canonical remote
address. When False (the default), the 'remote_address' header is used.

You should only enable this if you have an HTML sanitizing proxy.
"""),
]

metadata_opts = [
    cfg.StrOpt("config_drive_skip_versions",
        default=("1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 "
                 "2007-12-15 2008-02-01 2008-09-01"),
        deprecated_group="DEFAULT",
        help="""
When gathering the existing metadata for a config drive, the EC2-style
metadata is returned for all versions that don't appear in this option.
As of the Liberty release, the available versions are:

* 1.0
* 2007-01-19
* 2007-03-01
* 2007-08-29
* 2007-10-10
* 2007-12-15
* 2008-02-01
* 2008-09-01
* 2009-04-04

The option is in the format of a single string, with each version separated
by a space.

Possible values:

* Any string that represents zero or more versions, separated by spaces.
"""),
    cfg.ListOpt('vendordata_providers',
        item_type=cfg.types.String(choices=['StaticJSON', 'DynamicJSON']),
        default=['StaticJSON'],
        deprecated_group="DEFAULT",
        help="""
A list of vendordata providers.

vendordata providers are how deployers can provide metadata via configdrive
and metadata that is specific to their deployment. There are currently two
supported providers: StaticJSON and DynamicJSON.

StaticJSON reads a JSON file configured by the flag vendordata_jsonfile_path
and places the JSON from that file into vendor_data.json and
vendor_data2.json.

DynamicJSON is configured via the vendordata_dynamic_targets flag, which is
documented separately. For each of the endpoints specified in that flag, a
section is added to the vendor_data2.json.

For more information on the requirements for implementing a vendordata
dynamic endpoint, please see the vendordata.rst file in the nova developer
reference.

Possible values:

* A list of vendordata providers, with StaticJSON and DynamicJSON being
  current options.

Related options:

* vendordata_dynamic_targets
* vendordata_dynamic_ssl_certfile
* vendordata_dynamic_connect_timeout
* vendordata_dynamic_read_timeout
* vendordata_dynamic_failure_fatal
"""),
    cfg.ListOpt('vendordata_dynamic_targets',
        default=[],
        deprecated_group="DEFAULT",
        help="""
A list of targets for the dynamic vendordata provider. These targets are of
the form <name>@<url>.

The dynamic vendordata provider collects metadata by contacting external REST
services and querying them for information about the instance. This behaviour
is documented in the vendordata.rst file in the nova developer reference.
"""),
    cfg.StrOpt('vendordata_dynamic_ssl_certfile',
        default='',
        deprecated_group="DEFAULT",
        help="""
Path to an optional certificate file or CA bundle to verify dynamic
vendordata REST services ssl certificates against.

Possible values:

* An empty string, or a path to a valid certificate file

Related options:

* vendordata_providers
* vendordata_dynamic_targets
* vendordata_dynamic_connect_timeout
* vendordata_dynamic_read_timeout
* vendordata_dynamic_failure_fatal
"""),
    cfg.IntOpt('vendordata_dynamic_connect_timeout',
        default=5,
        min=3,
        deprecated_group="DEFAULT",
        help="""
Maximum wait time for an external REST service to connect.

Possible values:

* Any integer with a value greater than three (the TCP packet retransmission
  timeout). Note that instance start may be blocked during this wait time,
  so this value should be kept small.

Related options:

* vendordata_providers
* vendordata_dynamic_targets
* vendordata_dynamic_ssl_certfile
* vendordata_dynamic_read_timeout
* vendordata_dynamic_failure_fatal
"""),
    cfg.IntOpt('vendordata_dynamic_read_timeout',
        default=5,
        min=0,
        deprecated_group="DEFAULT",
        help="""
Maximum wait time for an external REST service to return data once connected.

Possible values:

* Any integer. Note that instance start is blocked during this wait time,
  so this value should be kept small.

Related options:

* vendordata_providers
* vendordata_dynamic_targets
* vendordata_dynamic_ssl_certfile
* vendordata_dynamic_connect_timeout
* vendordata_dynamic_failure_fatal
"""),
    cfg.BoolOpt('vendordata_dynamic_failure_fatal',
        default=False,
        help="""
Should failures to fetch dynamic vendordata be fatal to instance boot?

Related options:

* vendordata_providers
* vendordata_dynamic_targets
* vendordata_dynamic_ssl_certfile
* vendordata_dynamic_connect_timeout
* vendordata_dynamic_read_timeout
"""),
    cfg.IntOpt("metadata_cache_expiration",
        default=15,
        min=0,
        deprecated_group="DEFAULT",
        help="""
This option is the time (in seconds) to cache metadata. When set to 0,
metadata caching is disabled entirely; this is generally not recommended for
performance reasons. Increasing this setting should improve response times
of the metadata API when under heavy load. Higher values may increase memory
usage, and result in longer times for host metadata changes to take effect.
"""),
]

file_opts = [
    cfg.StrOpt("vendordata_jsonfile_path",
        deprecated_group="DEFAULT",
        help="""
Cloud providers may store custom data in vendor data file that will then be
available to the instances via the metadata service, and to the rendering of
config-drive. The default class for this, JsonFileVendorData, loads this
information from a JSON file, whose path is configured by this option. If
there is no path set by this option, the class returns an empty dictionary.

Possible values:

* Any string representing the path to the data file, or an empty string
    (default).
""")
]

osapi_opts = [
    cfg.IntOpt("max_limit",
        default=1000,
        min=0,
        deprecated_group="DEFAULT",
        deprecated_name="osapi_max_limit",
        help="""
As a query can potentially return many thousands of items, you can limit the
maximum number of items in a single response by setting this option.
"""),
    cfg.StrOpt("compute_link_prefix",
        deprecated_group="DEFAULT",
        deprecated_name="osapi_compute_link_prefix",
        help="""
This string is prepended to the normal URL that is returned in links to the
OpenStack Compute API. If it is empty (the default), the URLs are returned
unchanged.

Possible values:

* Any string, including an empty string (the default).
"""),
    cfg.StrOpt("glance_link_prefix",
        deprecated_group="DEFAULT",
        deprecated_name="osapi_glance_link_prefix",
        help="""
This string is prepended to the normal URL that is returned in links to
Glance resources. If it is empty (the default), the URLs are returned
unchanged.

Possible values:

* Any string, including an empty string (the default).
"""),
    cfg.BoolOpt("instance_list_per_project_cells",
        default=False,
        help="""
When enabled, this will cause the API to only query cell databases
in which the tenant has mapped instances. This requires an additional
(fast) query in the API database before each list, but also
(potentially) limits the number of cell databases that must be queried
to provide the result. If you have a small number of cells, or tenants
are likely to have instances in all cells, then this should be
False. If you have many cells, especially if you confine tenants to a
small subset of those cells, this should be True.
"""),
]

# NOTE(edleafe): I would like to import the value directly from
# nova.compute.vm_states, but that creates a circular import. Since this value
# is not likely to be changed, I'm copy/pasting it here.
BUILDING = "building"  # VM only exists in DB
osapi_hide_opts = [
    cfg.ListOpt("hide_server_address_states",
        default=[BUILDING],
        deprecated_group="DEFAULT",
        deprecated_name="osapi_hide_server_address_states",
        deprecated_for_removal=True,
        deprecated_since="17.0.0",
        deprecated_reason="This option hide the server address in server "
                          "representation for configured server states. "
                          "Which makes GET server API controlled by this "
                          "config options. Due to this config options, user "
                          "would not be able to discover the API behavior on "
                          "different clouds which leads to the interop issue.",
        help="""
This option is a list of all instance states for which network address
information should not be returned from the API.

Possible values:

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
""")
]

os_network_opts = [
    cfg.BoolOpt("use_neutron_default_nets",
        default=False,
        deprecated_group="DEFAULT",
        help="""
When True, the TenantNetworkController will query the Neutron API to get the
default networks to use.

Related options:

* neutron_default_tenant_id
"""),
    cfg.StrOpt("neutron_default_tenant_id",
        default="default",
        deprecated_group="DEFAULT",
        help="""
Tenant ID for getting the default network from Neutron API (also referred in
some places as the 'project ID') to use.

Related options:

* use_neutron_default_nets
"""),
]

enable_inst_pw_opts = [
    cfg.BoolOpt("enable_instance_password",
        default=True,
        deprecated_group="DEFAULT",
        help="""
Enables returning of the instance password by the relevant server API calls
such as create, rebuild, evacuate, or rescue. If the hypervisor does not
support password injection, then the password returned will not be correct,
so if your hypervisor does not support password injection, set this to False.
""")
]

API_OPTS = (auth_opts +
            metadata_opts +
            file_opts +
            osapi_opts +
            osapi_hide_opts +
            os_network_opts +
            enable_inst_pw_opts)


def register_opts(conf):
    conf.register_group(api_group)
    conf.register_opts(API_OPTS, group=api_group)


def list_opts():
    return {api_group: API_OPTS}
