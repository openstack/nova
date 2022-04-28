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
from oslo_vmware import vim_util as vutil

from nova.compute import rpcapi
from nova.objects.instance import Instance
from nova import profiler
from nova import rpc
from nova.virt.vmwareapi import vim_util


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

    def get_relocate_spec(self, ctxt, instance=None, flavor=None,
                          factory=None):
        ser = self._call('get_relocate_spec', ctxt,
                         instance_uuid=instance.uuid, flavor=flavor)

        return vim_util.deserialize_object(factory, ser,
                                           'VirtualMachineRelocateSpec')

    def change_vm_instance_uuid(self, ctxt, instance=None, cloned_vm_ref=None,
                                uuid=None):
        cloned_vm_ref_value = vutil.get_moref_value(cloned_vm_ref)
        return self._call('change_vm_instance_uuid', ctxt,
                          instance_uuid=instance.uuid,
                          cloned_vm_ref_value=cloned_vm_ref_value,
                          uuid=uuid)

    def rollback_migrate_disk(self, ctxt, instance=None, cloned_vm_ref=None):
        cloned_vm_ref_value = vutil.get_moref_value(cloned_vm_ref)
        return self._call('rollback_migrate_disk', ctxt,
                          instance_uuid=instance.uuid,
                          cloned_vm_ref_value=cloned_vm_ref_value)

    def confirm_migration_destination(self, ctxt, instance=None):
        return self._call('confirm_migration_destination', ctxt,
                          instance_uuid=instance.uuid)

    def prepare_ds_transfer(self, ctxt, request_method=None,
                            ds_ref=None, path=None):
        ds_ref_value = vutil.get_moref_value(ds_ref)
        return self._call('prepare_ds_transfer', ctxt,
                          request_method=request_method,
                          ds_ref_value=ds_ref_value, path=path)

    def delete_config_drive_files(self, ctxt, instance=None, cdroms=None):
        serialized = [vutil.serialize_object(spec, True) for spec in cdroms]
        return self._call('delete_config_drive_files', ctxt,
                          instance_uuid=instance.uuid,
                          cdroms=serialized)

    def reconfigure_vm_device_change(self, ctxt, instance=None, devices=None):
        serialized = [vutil.serialize_object(spec, True) for spec in devices]
        return self._call('reconfigure_vm_device_change', ctxt,
                          instance_uuid=instance.uuid,
                          devices=serialized)


@profiler.trace_cls("rpc")
class VmwareRpcService(object):
    target = messaging.Target(version=_VERSION, namespace=_NAMESPACE)

    def __init__(self, vm_ops, client_factory):
        self._vm_ops = vm_ops
        self._client_factory = client_factory

    def get_vif_info(self, ctxt, vif_model=None, network_info=None):
        return self._vm_ops.get_vif_info(ctxt, vif_model=vif_model,
                                         network_info=network_info)

    def get_relocate_spec(self, ctxt, instance_uuid=None, flavor=None):
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        spec = self._vm_ops.get_relocate_spec(ctxt, instance, flavor,
                                              remote=True)
        return vim_util.serialize_object(spec, typed=True)

    def change_vm_instance_uuid(self, ctxt, instance_uuid=None,
                                cloned_vm_ref_value=None, uuid=None):
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        cloned_vm_ref = vutil.get_moref(cloned_vm_ref_value, 'VirtualMachine')

        return self._vm_ops.change_vm_instance_uuid(ctxt, instance,
                                                    cloned_vm_ref,
                                                    uuid=uuid)

    def rollback_migrate_disk(self, ctxt, instance_uuid=None,
                              cloned_vm_ref_value=None):
        cloned_vm_ref = vutil.get_moref(cloned_vm_ref_value, 'VirtualMachine')
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        return self._vm_ops.rollback_migrate_disk(ctxt, instance,
                                                  cloned_vm_ref)

    def confirm_migration_destination(self, ctxt, instance_uuid=None):
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        return self._vm_ops.confirm_migration_destination(ctxt, instance)

    def prepare_ds_transfer(self, ctxt, request_method=None,
                            ds_ref_value=None, path=None):
        ds_ref = vutil.get_moref(ds_ref_value, 'Datastore')
        return self._vm_ops.prepare_ds_transfer(ctxt,
                                                request_method=request_method,
                                                ds_ref=ds_ref,
                                                path=path)

    def delete_config_drive_files(self, ctxt, instance_uuid=None,
                                     cdroms=None):
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        cf = self._client_factory
        deserialized = [
            vutil.deserialize_object(cf, spec, "VirtualDeviceConfigSpec")
            for spec in cdroms]

        return self._vm_ops.delete_config_drive_files(ctxt,
            instance=instance, cdroms=deserialized)

    def reconfigure_vm_device_change(self, ctxt, instance_uuid=None,
                                     devices=None):
        instance = Instance.get_by_uuid(ctxt, instance_uuid, expected_attrs=[])
        cf = self._client_factory
        deserialized = [
            vutil.deserialize_object(cf, spec, "VirtualDeviceConfigSpec")
            for spec in devices]

        return self._vm_ops.reconfigure_vm_device_change(ctxt,
            instance=instance, devices=deserialized)
