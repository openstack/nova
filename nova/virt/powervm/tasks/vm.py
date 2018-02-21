# Copyright 2015, 2018 IBM Corp.
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

from oslo_log import log as logging
from pypowervm import exceptions as pvm_exc
from pypowervm.tasks import storage as pvm_stg
from taskflow import task
from taskflow.types import failure as task_fail

from nova.virt.powervm import vm


LOG = logging.getLogger(__name__)


class Get(task.Task):

    """The task for getting a VM entry."""

    def __init__(self, adapter, instance):
        """Creates the Task for getting a VM entry.

        Provides the 'lpar_wrap' for other tasks.

        :param adapter: The adapter for the pypowervm API
        :param instance: The nova instance.
        """
        super(Get, self).__init__(name='get_vm', provides='lpar_wrap')
        self.adapter = adapter
        self.instance = instance

    def execute(self):
        return vm.get_instance_wrapper(self.adapter, self.instance)


class Create(task.Task):
    """The task for creating a VM."""

    def __init__(self, adapter, host_wrapper, instance, stg_ftsk):
        """Creates the Task for creating a VM.

        The revert method only needs to do something for failed rebuilds.
        Since the rebuild and build methods have different flows, it is
        necessary to clean up the destination LPAR on fails during rebuild.

        The revert method is not implemented for build because the compute
        manager calls the driver destroy operation for spawn errors. By
        not deleting the lpar, it's a cleaner flow through the destroy
        operation and accomplishes the same result.

        Any stale storage associated with the new VM's (possibly recycled) ID
        will be cleaned up.  The cleanup work will be delegated to the FeedTask
        represented by the stg_ftsk parameter.

        :param adapter: The adapter for the pypowervm API
        :param host_wrapper: The managed system wrapper
        :param instance: The nova instance.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        """
        super(Create, self).__init__(name='crt_vm', provides='lpar_wrap')
        self.instance = instance
        self.adapter = adapter
        self.host_wrapper = host_wrapper
        self.stg_ftsk = stg_ftsk

    def execute(self):
        wrap = vm.create_lpar(self.adapter, self.host_wrapper, self.instance)
        # Get rid of any stale storage and/or mappings associated with the new
        # LPAR's ID, so it doesn't accidentally have access to something it
        # oughtn't.
        LOG.info('Scrubbing stale storage.', instance=self.instance)
        pvm_stg.add_lpar_storage_scrub_tasks([wrap.id], self.stg_ftsk,
                                             lpars_exist=True)
        return wrap


class PowerOn(task.Task):
    """The task to power on the instance."""

    def __init__(self, adapter, instance):
        """Create the Task for the power on of the LPAR.

        :param adapter: The pypowervm adapter.
        :param instance: The nova instance.
        """
        super(PowerOn, self).__init__(name='pwr_vm')
        self.adapter = adapter
        self.instance = instance

    def execute(self):
        vm.power_on(self.adapter, self.instance)

    def revert(self, result, flow_failures):
        if isinstance(result, task_fail.Failure):
            # The power on itself failed...can't power off.
            LOG.debug('Power on failed.  Not performing power off.',
                      instance=self.instance)
            return

        LOG.warning('Powering off instance.', instance=self.instance)
        try:
            vm.power_off(self.adapter, self.instance, force_immediate=True)
        except pvm_exc.Error:
            # Don't raise revert exceptions
            LOG.exception("Power-off failed during revert.",
                          instance=self.instance)


class PowerOff(task.Task):
    """The task to power off a VM."""

    def __init__(self, adapter, instance, force_immediate=False):
        """Creates the Task to power off an LPAR.

        :param adapter: The adapter for the pypowervm API
        :param instance: The nova instance.
        :param force_immediate: Boolean. Perform a VSP hard power off.
        """
        super(PowerOff, self).__init__(name='pwr_off_vm')
        self.instance = instance
        self.adapter = adapter
        self.force_immediate = force_immediate

    def execute(self):
        vm.power_off(self.adapter, self.instance,
                     force_immediate=self.force_immediate)


class Delete(task.Task):
    """The task to delete the instance from the system."""

    def __init__(self, adapter, instance):
        """Create the Task to delete the VM from the system.

        :param adapter: The adapter for the pypowervm API.
        :param instance: The nova instance.
        """
        super(Delete, self).__init__(name='dlt_vm')
        self.adapter = adapter
        self.instance = instance

    def execute(self):
        vm.delete_lpar(self.adapter, self.instance)
