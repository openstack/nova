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

import functools
import socket

from eventlet import patcher

from nova import exception
from nova.i18n import _
from nova.virt.hyperv import constants

# Note(lpetrut): Eventlet greenpipes are not supported on Windows. The named
# pipe handlers implemented in os-win use Windows API calls which can block
# the whole thread. In order to avoid this, those workers run in separate
# 'native' threads.
#
# As this proxy communicates with those workers via queues, the serial console
# proxy workers have to run in 'native' threads as well.
threading = patcher.original('threading')


def handle_socket_errors(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except socket.error:
            self._client_connected.clear()
    return wrapper


class SerialProxy(threading.Thread):
    def __init__(self, instance_name, addr, port, input_queue,
                 output_queue, client_connected):
        super(SerialProxy, self).__init__()
        self.setDaemon(True)

        self._instance_name = instance_name
        self._addr = addr
        self._port = port
        self._conn = None

        self._input_queue = input_queue
        self._output_queue = output_queue
        self._client_connected = client_connected
        self._stopped = threading.Event()

    def _setup_socket(self):
        try:
            self._sock = socket.socket(socket.AF_INET,
                                       socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_REUSEADDR,
                                  1)
            self._sock.bind((self._addr, self._port))
            self._sock.listen(1)
        except socket.error as err:
            self._sock.close()
            msg = (_('Failed to initialize serial proxy on'
                     '%(addr)s:%(port)s, handling connections '
                     'to instance %(instance_name)s. Error: %(error)s') %
                   {'addr': self._addr,
                    'port': self._port,
                    'instance_name': self._instance_name,
                    'error': err})
            raise exception.NovaException(msg)

    def stop(self):
        self._stopped.set()
        self._client_connected.clear()
        if self._conn:
            self._conn.shutdown(socket.SHUT_RDWR)
            self._conn.close()
        self._sock.close()

    def run(self):
        self._setup_socket()
        while not self._stopped.isSet():
            self._accept_conn()

    @handle_socket_errors
    def _accept_conn(self):
        self._conn, client_addr = self._sock.accept()
        self._client_connected.set()

        workers = []
        for job in [self._get_data, self._send_data]:
            worker = threading.Thread(target=job)
            worker.setDaemon(True)
            worker.start()
            workers.append(worker)

        for worker in workers:
            worker_running = (worker.is_alive() and
                              worker is not threading.current_thread())
            if worker_running:
                worker.join()

        self._conn.close()
        self._conn = None

    @handle_socket_errors
    def _get_data(self):
        while self._client_connected.isSet():
            data = self._conn.recv(constants.SERIAL_CONSOLE_BUFFER_SIZE)
            if not data:
                self._client_connected.clear()
                return
            self._input_queue.put(data)

    @handle_socket_errors
    def _send_data(self):
        while self._client_connected.isSet():
            data = self._output_queue.get_burst()
            if data:
                self._conn.sendall(data)
