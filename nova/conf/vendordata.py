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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

vendordata_group = cfg.OptGroup('vendordata_dynamic_auth',
    title='Vendordata dynamic fetch auth options',
    help="""
Options within this group control the authentication of the vendordata
subsystem of the metadata API server (and config drive) with external systems.
""")


def register_opts(conf):
    conf.register_group(vendordata_group)
    ks_loading.register_session_conf_options(conf, vendordata_group.name)
    ks_loading.register_auth_conf_options(conf, vendordata_group.name)


def list_opts():
    return {
        vendordata_group: (
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password')
        )
    }
