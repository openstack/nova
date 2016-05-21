# needs:check_deprecation_status


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

service_opts = [
    # TODO(johngarbutt) we need a better default and minimum, in a backwards
    # compatible way for report_interval
    cfg.IntOpt('report_interval',
               default=10,
               help="""
Number of seconds indicating how frequently the state of services on a
given hypervisor is reported. Nova needs to know this to determine the
overall health of the deployment.

Related Options:

* service_down_time
  report_interval should be less than service_down_time. If service_down_time
  is less than report_interval, services will routinely be considered down,
  because they report in too rarely.
"""),
    # TODO(johngarbutt) the code enforces the min value here, but we could
    # do to add some min value here, once we sort out report_interval
    cfg.IntOpt('service_down_time',
               default=60,
               help="""
Maximum time in seconds since last check-in for up service

Each compute node periodically updates their database status based on the
specified report interval. If the compute node hasn't updated the status
for more than service_down_time, then the compute node is considered down.

Related Options:

* report_interval (service_down_time should not be less than report_interval)
"""),
    cfg.BoolOpt('periodic_enable',
               default=True,
               help="""
Enable periodic tasks.

If set to true, this option allows services to periodically run tasks
on the manager.

In case of running multiple schedulers or conductors you may want to run
periodic tasks on only one host - in this case disable this option for all
hosts but one.
"""),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               min=0,
               help="""
Number of seconds to randomly delay when starting the periodic task
scheduler to reduce stampeding.

When compute workers are restarted in unison across a cluster,
they all end up running the periodic tasks at the same time
causing problems for the external services. To mitigate this
behavior, periodic_fuzzy_delay option allows you to introduce a
random initial delay when starting the periodic task scheduler.

Possible Values:

* Any positive integer (in seconds)
* 0 : disable the random delay
"""),
    cfg.ListOpt('enabled_apis',
                item_type=cfg.types.String(choices=['osapi_compute',
                                                    'metadata']),
                default=['osapi_compute', 'metadata'],
                help="List of APIs to be enabled by default."),
    cfg.ListOpt('enabled_ssl_apis',
                default=[],
                help="""
List of APIs with enabled SSL.

Nova provides SSL support for the API servers. enabled_ssl_apis option
allows configuring the SSL support.
"""),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help="""
IP address on which the OpenStack API will listen.

The OpenStack API service listens on this IP address for incoming
requests.
"""),
    cfg.PortOpt('osapi_compute_listen_port',
               default=8774,
               help="""
Port on which the OpenStack API will listen.

The OpenStack API service listens on this port number for incoming
requests.
"""),
    cfg.IntOpt('osapi_compute_workers',
               min=1,
               help="""
Number of workers for OpenStack API service. The default will be the number
of CPUs available.

OpenStack API services can be configured to run as multi-process (workers).
This overcomes the problem of reduction in throughput when API request
concurrency increases. OpenStack API service will run in the specified
number of processes.

Possible Values:

* Any positive integer
* None (default value)
"""),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help="""
IP address on which the metadata API will listen.

The metadata API service listens on this IP address for incoming
requests.
"""),
    cfg.PortOpt('metadata_listen_port',
               default=8775,
               help="""
Port on which the metadata API will listen.

The metadata API service listens on this port number for incoming
requests.
"""),
    cfg.IntOpt('metadata_workers',
               min=1,
               help="""
Number of workers for metadata service. If not specified the number of
available CPUs will be used.

The metadata service can be configured to run as multi-process (workers).
This overcomes the problem of reduction in throughput when API request
concurrency increases. The metadata service will run in the specified
number of processes.

Possible Values:

* Any positive integer
* None (default value)
"""),
    # NOTE(sdague): the network_manager has a bunch of different in
    # tree classes that are still legit options. In Newton we should
    # turn this into a selector.
    cfg.StrOpt('network_manager',
               choices=[
                   'nova.network.manager.FlatManager',
                   'nova.network.manager.FlatDHCPManager',
                   'nova.network.manager.VlanManager',
               ],
               default='nova.network.manager.VlanManager',
               help='Full class name for the Manager for network'),
    ]


def register_opts(conf):
    conf.register_opts(service_opts)


def list_opts():
    return {'DEFAULT': service_opts}
