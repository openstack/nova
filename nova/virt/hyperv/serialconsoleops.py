# Copyright 2015 Cloudbase Solutions Srl
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

import functools
import os

from os_win import utilsfactory
from oslo_log import log as logging
import six

from nova import exception
from nova import utils
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import serialconsolehandler

LOG = logging.getLogger(__name__)

_console_handlers = {}


def instance_synchronized(func):
    @functools.wraps(func)
    def wrapper(self, instance_name, *args, **kwargs):
        @utils.synchronized(instance_name)
        def inner():
            return func(self, instance_name, *args, **kwargs)
        return inner()
    return wrapper


class SerialConsoleOps(object):
    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._pathutils = pathutils.PathUtils()

    @instance_synchronized
    def start_console_handler(self, instance_name):
        # Cleanup existing workers.
        self.stop_console_handler_unsync(instance_name)
        handler = None

        try:
            handler = serialconsolehandler.SerialConsoleHandler(
                instance_name)
            handler.start()
            _console_handlers[instance_name] = handler
        except Exception as exc:
            LOG.error('Instance %(instance_name)s serial console handler '
                      'could not start. Exception %(exc)s',
                      {'instance_name': instance_name,
                       'exc': exc})
            if handler:
                handler.stop()

    @instance_synchronized
    def stop_console_handler(self, instance_name):
        self.stop_console_handler_unsync(instance_name)

    def stop_console_handler_unsync(self, instance_name):
        handler = _console_handlers.get(instance_name)
        if handler:
            LOG.info("Stopping instance %(instance_name)s "
                     "serial console handler.",
                     {'instance_name': instance_name})
            handler.stop()
            del _console_handlers[instance_name]

    @instance_synchronized
    def get_serial_console(self, instance_name):
        handler = _console_handlers.get(instance_name)
        if not handler:
            raise exception.ConsoleTypeUnavailable(console_type='serial')
        return handler.get_serial_console()

    @instance_synchronized
    def get_console_output(self, instance_name):
        console_log_paths = self._pathutils.get_vm_console_log_paths(
            instance_name)

        try:
            log = b''
            # Start with the oldest console log file.
            for log_path in reversed(console_log_paths):
                if os.path.exists(log_path):
                    with open(log_path, 'rb') as fp:
                        log += fp.read()
            return log
        except IOError as err:
            raise exception.ConsoleLogOutputException(
                instance_id=instance_name, reason=six.text_type(err))

    def start_console_handlers(self):
        active_instances = self._vmutils.get_active_instances()
        for instance_name in active_instances:
            instance_path = self._pathutils.get_instance_dir(instance_name)

            # Skip instances that are not created by Nova
            if not os.path.exists(instance_path):
                continue

            self.start_console_handler(instance_name)
