# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Generic Node base class for all workers that run on hosts."""

import os
import random
import sys

from oslo.config import cfg
from oslo import messaging
from oslo.utils import importutils
from oslo_concurrency import processutils

from nova import baserpc
from nova import conductor
from nova import context
from nova import debugger
from nova import exception
from nova.i18n import _, _LE, _LW
from nova.objects import base as objects_base
from nova.openstack.common import log as logging
from nova.openstack.common import service
from nova import rpc
from nova import servicegroup
from nova import utils
from nova import version
from nova import wsgi

LOG = logging.getLogger(__name__)

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
                default=['ec2', 'osapi_compute', 'metadata'],
                help='A list of APIs to enable by default'),
    cfg.ListOpt('enabled_ssl_apis',
                default=[],
                help='A list of APIs with enabled SSL'),
    cfg.StrOpt('ec2_listen',
               default="0.0.0.0",
               help='The IP address on which the EC2 API will listen.'),
    cfg.IntOpt('ec2_listen_port',
               default=8773,
               help='The port on which the EC2 API will listen.'),
    cfg.IntOpt('ec2_workers',
               help='Number of workers for EC2 API service. The default will '
                    'be equal to the number of CPUs available.'),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help='The IP address on which the OpenStack API will listen.'),
    cfg.IntOpt('osapi_compute_listen_port',
               default=8774,
               help='The port on which the OpenStack API will listen.'),
    cfg.IntOpt('osapi_compute_workers',
               help='Number of workers for OpenStack API service. The default '
                    'will be the number of CPUs available.'),
    cfg.StrOpt('metadata_manager',
               default='nova.api.manager.MetadataManager',
               help='OpenStack metadata service manager'),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help='The IP address on which the metadata API will listen.'),
    cfg.IntOpt('metadata_listen_port',
               default=8775,
               help='The port on which the metadata API will listen.'),
    cfg.IntOpt('metadata_workers',
               help='Number of workers for metadata service. The default will '
                    'be the number of CPUs available.'),
    cfg.StrOpt('compute_manager',
               default='nova.compute.manager.ComputeManager',
               help='Full class name for the Manager for compute'),
    cfg.StrOpt('console_manager',
               default='nova.console.manager.ConsoleProxyManager',
               help='Full class name for the Manager for console proxy'),
    cfg.StrOpt('consoleauth_manager',
               default='nova.consoleauth.manager.ConsoleAuthManager',
               help='Manager for console auth'),
    cfg.StrOpt('cert_manager',
               default='nova.cert.manager.CertManager',
               help='Full class name for the Manager for cert'),
    cfg.StrOpt('network_manager',
               default='nova.network.manager.VlanManager',
               help='Full class name for the Manager for network'),
    cfg.StrOpt('scheduler_manager',
               default='nova.scheduler.manager.SchedulerManager',
               help='Full class name for the Manager for scheduler'),
    cfg.IntOpt('service_down_time',
               default=60,
               help='Maximum time since last check-in for up service'),
    ]

CONF = cfg.CONF
CONF.register_opts(service_opts)
CONF.import_opt('host', 'nova.netconf')


class Service(service.Service):
    """Service object for binaries running on hosts.

    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    it state to the database services table.
    """

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_enable=None, periodic_fuzzy_delay=None,
                 periodic_interval_max=None, db_allowed=True,
                 *args, **kwargs):
        super(Service, self).__init__()
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        # NOTE(russellb) We want to make sure to create the servicegroup API
        # instance early, before creating other things such as the manager,
        # that will also create a servicegroup API instance.  Internally, the
        # servicegroup only allocates a single instance of the driver API and
        # we want to make sure that our value of db_allowed is there when it
        # gets created.  For that to happen, this has to be the first instance
        # of the servicegroup API.
        self.servicegroup_api = servicegroup.API(db_allowed=db_allowed)
        manager_class = importutils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.rpcserver = None
        self.report_interval = report_interval
        self.periodic_enable = periodic_enable
        self.periodic_fuzzy_delay = periodic_fuzzy_delay
        self.periodic_interval_max = periodic_interval_max
        self.saved_args, self.saved_kwargs = args, kwargs
        self.backdoor_port = None
        self.conductor_api = conductor.API(use_local=db_allowed)
        self.conductor_api.wait_until_ready(context.get_admin_context())

    def start(self):
        verstr = version.version_string_with_package()
        LOG.audit(_('Starting %(topic)s node (version %(version)s)'),
                  {'topic': self.topic, 'version': verstr})
        self.basic_config_check()
        self.manager.init_host()
        self.model_disconnected = False
        ctxt = context.get_admin_context()
        try:
            self.service_ref = self.conductor_api.service_get_by_args(ctxt,
                    self.host, self.binary)
            self.service_id = self.service_ref['id']
        except exception.NotFound:
            try:
                self.service_ref = self._create_service_ref(ctxt)
            except (exception.ServiceTopicExists,
                    exception.ServiceBinaryExists):
                # NOTE(danms): If we race to create a record with a sibling
                # worker, don't fail here.
                self.service_ref = self.conductor_api.service_get_by_args(ctxt,
                    self.host, self.binary)

        self.manager.pre_start_hook()

        if self.backdoor_port is not None:
            self.manager.backdoor_port = self.backdoor_port

        LOG.debug("Creating RPC server for service %s", self.topic)

        target = messaging.Target(topic=self.topic, server=self.host)

        endpoints = [
            self.manager,
            baserpc.BaseRPCAPI(self.manager.service_name, self.backdoor_port)
        ]
        endpoints.extend(self.manager.additional_endpoints)

        serializer = objects_base.NovaObjectSerializer()

        self.rpcserver = rpc.get_server(target, endpoints, serializer)
        self.rpcserver.start()

        self.manager.post_start_hook()

        LOG.debug("Join ServiceGroup membership for this service %s",
                  self.topic)
        # Add service to the ServiceGroup membership group.
        self.servicegroup_api.join(self.host, self.topic, self)

        if self.periodic_enable:
            if self.periodic_fuzzy_delay:
                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
            else:
                initial_delay = None

            self.tg.add_dynamic_timer(self.periodic_tasks,
                                     initial_delay=initial_delay,
                                     periodic_interval_max=
                                        self.periodic_interval_max)

    def _create_service_ref(self, context):
        svc_values = {
            'host': self.host,
            'binary': self.binary,
            'topic': self.topic,
            'report_count': 0,
        }
        service = self.conductor_api.service_create(context, svc_values)
        self.service_id = service['id']
        return service

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_enable=None,
               periodic_fuzzy_delay=None, periodic_interval_max=None,
               db_allowed=True):
        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_enable: defaults to CONF.periodic_enable
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay
        :param periodic_interval_max: if set, the max time to wait between runs

        """
        if not host:
            host = CONF.host
        if not binary:
            binary = os.path.basename(sys.argv[0])
        if not topic:
            topic = binary.rpartition('nova-')[2]
        if not manager:
            manager_cls = ('%s_manager' %
                           binary.rpartition('nova-')[2])
            manager = CONF.get(manager_cls, None)
        if report_interval is None:
            report_interval = CONF.report_interval
        if periodic_enable is None:
            periodic_enable = CONF.periodic_enable
        if periodic_fuzzy_delay is None:
            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay

        debugger.init()

        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_enable=periodic_enable,
                          periodic_fuzzy_delay=periodic_fuzzy_delay,
                          periodic_interval_max=periodic_interval_max,
                          db_allowed=db_allowed)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore."""
        self.stop()
        try:
            self.conductor_api.service_destroy(context.get_admin_context(),
                                               self.service_id)
        except exception.NotFound:
            LOG.warning(_LW('Service killed that has no database entry'))

    def stop(self):
        try:
            self.rpcserver.stop()
            self.rpcserver.wait()
        except Exception:
            pass

        try:
            self.manager.cleanup_host()
        except Exception:
            LOG.exception(_LE('Service error occurred during cleanup_host'))
            pass

        super(Service, self).stop()

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        return self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)

    def basic_config_check(self):
        """Perform basic config checks before starting processing."""
        # Make sure the tempdir exists and is writable
        try:
            with utils.tempdir():
                pass
        except Exception as e:
            LOG.error(_LE('Temporary directory is invalid: %s'), e)
            sys.exit(1)


class WSGIService(object):
    """Provides ability to launch API from a 'paste' configuration."""

    def __init__(self, name, loader=None, use_ssl=False, max_url_len=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param loader: Loads the WSGI application using the given name.
        :returns: None

        """
        self.name = name
        self.manager = self._get_manager()
        self.loader = loader or wsgi.Loader()
        self.app = self.loader.load_app(name)
        # inherit all compute_api worker counts from osapi_compute
        if name.startswith('openstack_compute_api'):
            wname = 'osapi_compute'
        else:
            wname = name
        self.host = getattr(CONF, '%s_listen' % name, "0.0.0.0")
        self.port = getattr(CONF, '%s_listen_port' % name, 0)
        self.workers = (getattr(CONF, '%s_workers' % wname, None) or
                        processutils.get_worker_count())
        if self.workers and self.workers < 1:
            worker_name = '%s_workers' % name
            msg = (_("%(worker_name)s value of %(workers)s is invalid, "
                     "must be greater than 0") %
                   {'worker_name': worker_name,
                    'workers': str(self.workers)})
            raise exception.InvalidInput(msg)
        self.use_ssl = use_ssl
        self.server = wsgi.Server(name,
                                  self.app,
                                  host=self.host,
                                  port=self.port,
                                  use_ssl=self.use_ssl,
                                  max_url_len=max_url_len)
        # Pull back actual port used
        self.port = self.server.port
        self.backdoor_port = None

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None

        """
        self.server.reset()

    def _get_manager(self):
        """Initialize a Manager object appropriate for this service.

        Use the service name to look up a Manager subclass from the
        configuration and initialize an instance. If no class name
        is configured, just return None.

        :returns: a Manager instance, or None.

        """
        fl = '%s_manager' % self.name
        if fl not in CONF:
            return None

        manager_class_name = CONF.get(fl, None)
        if not manager_class_name:
            return None

        manager_class = importutils.import_class(manager_class_name)
        return manager_class()

    def start(self):
        """Start serving this service using loaded configuration.

        Also, retrieve updated port number in case '0' was passed in, which
        indicates a random port should be used.

        :returns: None

        """
        if self.manager:
            self.manager.init_host()
            self.manager.pre_start_hook()
            if self.backdoor_port is not None:
                self.manager.backdoor_port = self.backdoor_port
        self.server.start()
        if self.manager:
            self.manager.post_start_hook()

    def stop(self):
        """Stop serving this API.

        :returns: None

        """
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None

        """
        self.server.wait()


def process_launcher():
    return service.ProcessLauncher()


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(server, workers=None):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = service.launch(server, workers=workers)


def wait():
    _launcher.wait()
