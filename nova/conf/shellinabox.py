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

Interdependencies to other options:

* The IP address must be identical to the address to which the
  ``nova-shellinaboxproxy`` service is listening (see option
  ``shellinaboxproxy_host``
  in this section).
* The port must be the same as in the option ``shellinaboxproxy_port`` of this
  section.
* If you choose to use a secured websocket connection, then start this option
  with ``wss://`` instead of the unsecured ``ws://``. The options ``cert``
  and ``key`` in the ``[DEFAULT]`` section have to be set for that.
""")

proxyclient_url_opt = cfg.StrOpt('proxyclient_url',
                                 default='http://127.0.0.1',
                                 help="""
The url to which proxy clients (like ``nova-shellinaboxproxy``) should
connect to get the serial console of an instance.

Possible values:

* An http address

Services which consume this:

* ``nova-compute``

Interdependencies to other options:

* None
""")

shellinaboxproxy_host_opt = cfg.StrOpt('host',
                                       default='0.0.0.0',
                                       help="""
The IP address which is used by the ``nova-shellinaboxproxy`` service to listen
for incoming requests.

The ``nova-shellinaboxproxy`` service listens on this IP address for incoming
connection requests to instances which expose serial console.

Possible values:

* An IP address

Services which consume this:

* ``nova-shellinaboxproxy``

Interdependencies to other options:

* Ensure that this is the same IP address which is defined in the option
  ``base_url`` of this section or use ``0.0.0.0`` to listen on all addresses.
""")

shellinaboxproxy_port_opt = cfg.IntOpt('port',
                                       default=6084,
                                       min=1,
                                       max=65535,
                                       help="""
The port number which is used by the ``nova-shellinaboxproxy`` service to
listen for incoming requests.

The ``nova-shellinaboxproxy`` service listens on this port number for incoming
connection requests to instances which expose serial console.

Possible values:

* A port number

Services which consume this:

* ``nova-shellinaboxproxy``

Interdependencies to other options:

* Ensure that this is the same port number which is defined in the option
  ``base_url`` of this section.
""")


ALL_OPTS = [enabled_opt,
            base_url_opt,
            proxyclient_url_opt,
            shellinaboxproxy_host_opt,
            shellinaboxproxy_port_opt]


def register_opts(conf):
    conf.register_group(shellinabox_opt_group)
    conf.register_opts(ALL_OPTS, group=shellinabox_opt_group)


def register_cli_opts(conf):
    conf.register_group(shellinabox_opt_group)
    conf.register_cli_opts([proxyclient_url_opt,
                            base_url_opt,
                            shellinaboxproxy_host_opt,
                            shellinaboxproxy_port_opt],
                           shellinabox_opt_group)


def list_opts():
    # Because of bug 1395819 in oslo.config we cannot pass in the OptGroup.
    # As soon as this bug is fixed is oslo.config and Nova uses the
    # version which contains this fix, we can pass in the OptGroup instead
    # of its name. This allows the generation of the group help too.
    return {shellinabox_opt_group: ALL_OPTS}
