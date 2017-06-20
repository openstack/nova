# Copyright 2016 Cloudbase Solutions Srl
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

from eventlet import patcher
from os_win.utils.io import ioutils
from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging

from nova.console import serial as serial_console
from nova.console import type as ctype
from nova import exception
from nova.i18n import _
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import serialproxy

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

threading = patcher.original('threading')


class SerialConsoleHandler(object):
    """Handles serial console ops related to a given instance."""
    def __init__(self, instance_name):
        self._vmutils = utilsfactory.get_vmutils()
        self._pathutils = pathutils.PathUtils()

        self._instance_name = instance_name
        self._log_path = self._pathutils.get_vm_console_log_paths(
            self._instance_name)[0]

        self._client_connected = None
        self._input_queue = None
        self._output_queue = None

        self._serial_proxy = None
        self._workers = []

    def start(self):
        self._setup_handlers()

        for worker in self._workers:
            worker.start()

    def stop(self):
        for worker in self._workers:
            worker.stop()

        if self._serial_proxy:
            serial_console.release_port(self._listen_host,
                                        self._listen_port)

    def _setup_handlers(self):
        if CONF.serial_console.enabled:
            self._setup_serial_proxy_handler()

        self._setup_named_pipe_handlers()

    def _setup_serial_proxy_handler(self):
        self._listen_host = (
            CONF.serial_console.proxyclient_address)
        self._listen_port = serial_console.acquire_port(
            self._listen_host)

        LOG.info('Initializing serial proxy on '
                 '%(addr)s:%(port)s, handling connections '
                 'to instance %(instance_name)s.',
                 {'addr': self._listen_host,
                  'port': self._listen_port,
                  'instance_name': self._instance_name})

        # Use this event in order to manage
        # pending queue operations.
        self._client_connected = threading.Event()
        self._input_queue = ioutils.IOQueue(
            client_connected=self._client_connected)
        self._output_queue = ioutils.IOQueue(
            client_connected=self._client_connected)

        self._serial_proxy = serialproxy.SerialProxy(
            self._instance_name, self._listen_host,
            self._listen_port, self._input_queue,
            self._output_queue, self._client_connected)

        self._workers.append(self._serial_proxy)

    def _setup_named_pipe_handlers(self):
        # At most 2 named pipes will be used to access the vm serial ports.
        #
        # The named pipe having the 'ro' suffix will be used only for logging
        # while the 'rw' pipe will be used for interactive sessions, logging
        # only when there is no 'ro' pipe.
        serial_port_mapping = self._get_vm_serial_port_mapping()
        log_rw_pipe_output = not serial_port_mapping.get(
            constants.SERIAL_PORT_TYPE_RO)

        for pipe_type, pipe_path in serial_port_mapping.items():
            enable_logging = (pipe_type == constants.SERIAL_PORT_TYPE_RO or
                              log_rw_pipe_output)
            handler = self._get_named_pipe_handler(
                pipe_path,
                pipe_type=pipe_type,
                enable_logging=enable_logging)
            self._workers.append(handler)

    def _get_named_pipe_handler(self, pipe_path, pipe_type,
                                enable_logging):
        kwargs = {}
        if pipe_type == constants.SERIAL_PORT_TYPE_RW:
            kwargs = {'input_queue': self._input_queue,
                      'output_queue': self._output_queue,
                      'connect_event': self._client_connected}
        if enable_logging:
            kwargs['log_file'] = self._log_path

        handler = utilsfactory.get_named_pipe_handler(pipe_path, **kwargs)
        return handler

    def _get_vm_serial_port_mapping(self):
        serial_port_conns = self._vmutils.get_vm_serial_port_connections(
            self._instance_name)

        if not serial_port_conns:
            err_msg = _("No suitable serial port pipe was found "
                        "for instance %(instance_name)s")
            raise exception.NovaException(
                err_msg % {'instance_name': self._instance_name})

        serial_port_mapping = {}
        # At the moment, we tag the pipes by using a pipe path suffix
        # as we can't use the serial port ElementName attribute because of
        # a Hyper-V bug.
        for pipe_path in serial_port_conns:
            # expected pipe_path:
            # '\\.\pipe\fc1bcc91-c7d3-4116-a210-0cd151e019cd_rw'
            port_type = pipe_path[-2:]
            if port_type in [constants.SERIAL_PORT_TYPE_RO,
                             constants.SERIAL_PORT_TYPE_RW]:
                serial_port_mapping[port_type] = pipe_path
            else:
                serial_port_mapping[constants.SERIAL_PORT_TYPE_RW] = pipe_path

        return serial_port_mapping

    def get_serial_console(self):
        if not CONF.serial_console.enabled:
            raise exception.ConsoleTypeUnavailable(console_type='serial')
        return ctype.ConsoleSerial(host=self._listen_host,
                                   port=self._listen_port)
