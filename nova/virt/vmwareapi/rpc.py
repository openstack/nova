# Copyright (c) 2021 SAP SE
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

"""
RPC server and client for communicating with other Vmareapi drivers directly.
This is the gateway which allows us gathering VMWare related information from
other hosts and perform cross vCenter operations.
"""
import oslo_messaging as messaging

from nova.compute import rpcapi
from nova import profiler
from nova import rpc


_NAMESPACE = 'vmwareapi'
_VERSION = '5.0'


@profiler.trace_cls("rpc")
class VmwareRpcApi(object):
    def __init__(self, server):
        target = messaging.Target(topic=rpcapi.RPC_TOPIC, version=_VERSION,
            namespace=_NAMESPACE)
        self._router = rpc.ClientRouter(rpc.get_client(target))
        self._server = server

    def _call(self, fname, ctxt, version=None, **kwargs):
        version = version or _VERSION
        cctxt = self._router.client(ctxt).prepare(server=self._server,
                                                  version=version)
        return cctxt.call(ctxt, fname, **kwargs)

    def get_vif_info(self, ctxt, vif_model=None, network_info=None):
        return self._call('get_vif_info', ctxt, vif_model=vif_model,
                          network_info=network_info,)


@profiler.trace_cls("rpc")
class VmwareRpcService(object):
    target = messaging.Target(version=_VERSION, namespace=_NAMESPACE)

    def __init__(self, driver):
        self._driver = driver

    def get_vif_info(self, ctxt, vif_model=None, network_info=None):
        return self._driver._vmops.get_vif_info(ctxt, vif_model=vif_model,
                                                network_info=network_info,
                                                )
