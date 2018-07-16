# Copyright 2017,2018 IBM Corp.
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


zvm_opt_group = cfg.OptGroup('zvm',
                             title='zVM Options',
                             help="""
zvm options allows cloud administrator to configure related
z/VM hypervisor driver to be used within an OpenStack deployment.

zVM options are used when the compute_driver is set to use
zVM (compute_driver=zvm.ZVMDriver)
""")


zvm_opts = [
    cfg.URIOpt('cloud_connector_url',
               sample_default='http://zvm.example.org:8080/',
               help="""
URL to be used to communicate with z/VM Cloud Connector.
"""),
    cfg.StrOpt('ca_file',
               default=None,
               help="""
CA certificate file to be verified in httpd server with TLS enabled

A string, it must be a path to a CA bundle to use.
"""),
]


def register_opts(conf):
    conf.register_group(zvm_opt_group)
    conf.register_opts(zvm_opts, group=zvm_opt_group)


def list_opts():
    return {zvm_opt_group: zvm_opts}
