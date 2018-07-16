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


from nova.conf import paths


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
    cfg.StrOpt('image_tmp_path',
               default=paths.state_path_def('images'),
               sample_default="$state_path/images",
               help="""
The path at which images will be stored (snapshot, deploy, etc).

Images used for deploy and images captured via snapshot
need to be stored on the local disk of the compute host.
This configuration identifies the directory location.

Possible values:
    A file system path on the host running the compute service.
"""),
    cfg.IntOpt('reachable_timeout',
               default=300,
               help="""
Timeout (seconds) to wait for an instance to start.

The z/VM driver relies on communication between the instance and cloud
connector. After an instance is created, it must have enough time to wait
for all the network info to be written into the user directory.
The driver will keep rechecking network status to the instance with the
timeout value, If setting network failed, it will notify the user that
starting the instance failed and put the instance in ERROR state.
The underlying z/VM guest will then be deleted.

Possible Values:
    Any positive integer. Recommended to be at least 300 seconds (5 minutes),
    but it will vary depending on instance and system load.
    A value of 0 is used for debug. In this case the underlying z/VM guest
    will not be deleted when the instance is marked in ERROR state.
"""),
]


def register_opts(conf):
    conf.register_group(zvm_opt_group)
    conf.register_opts(zvm_opts, group=zvm_opt_group)


def list_opts():
    return {zvm_opt_group: zvm_opts}
