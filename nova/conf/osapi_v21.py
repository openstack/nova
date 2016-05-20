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


api_opts = [
    cfg.ListOpt("extensions_blacklist",
            default=[],
            deprecated_for_removal=True,
            deprecated_group="osapi_v21",
            help="""
*DEPRECATED*

This option is a list of all of the v2.1 API extensions to never load. However,
it will be removed in the near future, after which the all the functionality
that was previously in extensions will be part of the standard API, and thus
always accessible.

* Possible values:

    A list of strings, each being the alias of an extension that you do not
    wish to load.

* Services that use this:

    ``nova-api``

* Related options:

    enabled, extensions_whitelist
"""),
        cfg.ListOpt("extensions_whitelist",
            default=[],
            deprecated_for_removal=True,
            deprecated_group="osapi_v21",
            help="""
*DEPRECATED*

This is a list of extensions. If it is empty, then *all* extensions except
those specified in the extensions_blacklist option will be loaded. If it is not
empty, then only those extensions in this list will be loaded, provided that
they are also not in the extensions_blacklist option. Once this deprecated
option is removed, after which the all the functionality that was previously in
extensions will be part of the standard API, and thus always accessible.

* Possible values:

    A list of strings, each being the alias of an extension that you wish to
    load, or an empty list, which indicates that all extensions are to be run.

* Services that use this:

    ``nova-api``

* Related options:

    enabled, extensions_blacklist
"""),
        cfg.StrOpt("project_id_regex",
            default=None,
            deprecated_for_removal=True,
            deprecated_group="osapi_v21",
            help="""
*DEPRECATED*

This option is a string representing a regular expression (regex) that matches
the project_id as contained in URLs. If not set, it will match normal UUIDs
created by keystone.

* Possible values:

    A string representing any legal regular expression

* Services that use this:

    ``nova-api``

* Related options:

    None
"""),
]

api_opts_group = cfg.OptGroup(name="osapi_v21", title="API v2.1 Options")


def register_opts(conf):
    conf.register_group(api_opts_group)
    conf.register_opts(api_opts, api_opts_group)


def list_opts():
    return {api_opts_group: api_opts}
