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

shellinabox_opt_group = cfg.OptGroup("shellinabox",
                                     title="The shellinabox console feature",
                                     help="""
The shellinabox console feature allows you to connect to a Ironic instance.""")

enabled_opt = cfg.BoolOpt('enabled',
                          default=False,
                          help="""
Enable the shellinabox console feature.

In order to use this feature, the service ``nova-shellinaboxproxy`` needs to
run. This service is typically executed on the controller node.

Possible values:

* True: Enables the feature
* False: Disables the feature

Services which consume this:

* ``nova-compute``

Interdependencies to other options:

* None
""")

base_url_opt = cfg.StrOpt('base_url',
                          default='http://127.0.0.1:6084/',
                          help="""
The URL an end user would use to connect to the ``nova-shellinaboxproxy``
service.

The ``nova-shellinaboxproxy`` service is called with this token enriched URL
and establishes the connection to the proper instance.

Possible values:

* <scheme><IP-address><port-number>

Services which consume this:

* ``nova-compute``
""")

ALL_OPTS = [enabled_opt,
            base_url_opt]


def register_opts(conf):
    conf.register_group(shellinabox_opt_group)
    conf.register_opts(ALL_OPTS, group=shellinabox_opt_group)


def register_cli_opts(conf):
    conf.register_group(shellinabox_opt_group)
    conf.register_cli_opts([base_url_opt],
                           shellinabox_opt_group)


def list_opts():
    # Because of bug 1395819 in oslo.config we cannot pass in the OptGroup.
    # As soon as this bug is fixed is oslo.config and Nova uses the
    # version which contains this fix, we can pass in the OptGroup instead
    # of its name. This allows the generation of the group help too.
    return {shellinabox_opt_group: ALL_OPTS}
