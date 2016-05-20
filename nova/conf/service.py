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
    cfg.IntOpt('report_interval',
               default=10,
               help='Seconds between nodes reporting state to datastore'),
    cfg.BoolOpt('periodic_enable',
               default=True,
               help='Enable periodic tasks'),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               help='Range of seconds to randomly delay when starting the'
                    ' periodic task scheduler to reduce stampeding.'
                    ' (Disable by setting to 0)'),
    cfg.ListOpt('enabled_apis',
                default=['osapi_compute', 'metadata'],
                help='A list of APIs to enable by default'),
    cfg.ListOpt('enabled_ssl_apis',
                default=[],
                help='A list of APIs with enabled SSL'),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help='The IP address on which the OpenStack API will listen.'),
    cfg.IntOpt('osapi_compute_listen_port',
               default=8774,
               min=1,
               max=65535,
               help='The port on which the OpenStack API will listen.'),
    cfg.IntOpt('osapi_compute_workers',
               help='Number of workers for OpenStack API service. The default '
                    'will be the number of CPUs available.'),
    cfg.StrOpt('metadata_manager',
               default='nova.api.manager.MetadataManager',
               help='DEPRECATED: OpenStack metadata service manager',
               deprecated_for_removal=True),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help='The IP address on which the metadata API will listen.'),
    cfg.IntOpt('metadata_listen_port',
               default=8775,
               min=1,
               max=65535,
               help='The port on which the metadata API will listen.'),
    cfg.IntOpt('metadata_workers',
               help='Number of workers for metadata service. The default will '
                    'be the number of CPUs available.'),
    # NOTE(sdague): Ironic is still using this facility for their HA
    # manager. Ensure they are sorted before removing this.
    cfg.StrOpt('compute_manager',
               default='nova.compute.manager.ComputeManager',
               help='DEPRECATED: Full class name for the Manager for compute',
               deprecated_for_removal=True),
    cfg.StrOpt('console_manager',
               default='nova.console.manager.ConsoleProxyManager',
               help='DEPRECATED: Full class name for the Manager for '
                   'console proxy',
               deprecated_for_removal=True),
    cfg.StrOpt('consoleauth_manager',
               default='nova.consoleauth.manager.ConsoleAuthManager',
               help='DEPRECATED: Manager for console auth',
               deprecated_for_removal=True),
    cfg.StrOpt('cert_manager',
               default='nova.cert.manager.CertManager',
               help='DEPRECATED: Full class name for the Manager for cert',
               deprecated_for_removal=True),
    # NOTE(sdague): the network_manager has a bunch of different in
    # tree classes that are still legit options. In Newton we should
    # turn this into a selector.
    cfg.StrOpt('network_manager',
               default='nova.network.manager.VlanManager',
               help='Full class name for the Manager for network'),
    cfg.StrOpt('scheduler_manager',
               default='nova.scheduler.manager.SchedulerManager',
               help='DEPRECATED: Full class name for the Manager for '
                   'scheduler',
               deprecated_for_removal=True),
    cfg.IntOpt('service_down_time',
               default=60,
               help='Maximum time since last check-in for up service'),
    ]


def register_opts(conf):
    conf.register_opts(service_opts)


def list_opts():
    return {'DEFAULT': service_opts}
