# Copyright 2014, 2017 IBM Corp.
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

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as pvm_log
from pypowervm.tasks import power
from pypowervm.tasks import vterm
from pypowervm import util as pvm_u
from pypowervm.utils import lpar_builder as lpar_bldr
from pypowervm.utils import uuid as pvm_uuid
from pypowervm.utils import validation as pvm_vldn
from pypowervm.wrappers import base_partition as pvm_bp
from pypowervm.wrappers import logical_partition as pvm_lpar
import six

from nova.compute import power_state
from nova import conf
from nova import exception as exc
from nova.virt import hardware


LOG = logging.getLogger(__name__)
CONF = conf.CONF

_POWERVM_STARTABLE_STATE = (pvm_bp.LPARState.NOT_ACTIVATED,)
_POWERVM_STOPPABLE_STATE = (
    pvm_bp.LPARState.RUNNING, pvm_bp.LPARState.STARTING,
    pvm_bp.LPARState.OPEN_FIRMWARE, pvm_bp.LPARState.SHUTTING_DOWN,
    pvm_bp.LPARState.ERROR, pvm_bp.LPARState.RESUMING,
    pvm_bp.LPARState.SUSPENDING)
_POWERVM_TO_NOVA_STATE = {
    pvm_bp.LPARState.MIGRATING_RUNNING: power_state.RUNNING,
    pvm_bp.LPARState.RUNNING: power_state.RUNNING,
    pvm_bp.LPARState.STARTING: power_state.RUNNING,
    # map open firmware state to active since it can be shut down
    pvm_bp.LPARState.OPEN_FIRMWARE: power_state.RUNNING,
    # It is running until it is off.
    pvm_bp.LPARState.SHUTTING_DOWN: power_state.RUNNING,
    # It is running until the suspend completes
    pvm_bp.LPARState.SUSPENDING: power_state.RUNNING,

    pvm_bp.LPARState.MIGRATING_NOT_ACTIVE: power_state.SHUTDOWN,
    pvm_bp.LPARState.NOT_ACTIVATED: power_state.SHUTDOWN,

    pvm_bp.LPARState.UNKNOWN: power_state.NOSTATE,
    pvm_bp.LPARState.HARDWARE_DISCOVERY: power_state.NOSTATE,
    pvm_bp.LPARState.NOT_AVAILBLE: power_state.NOSTATE,

    # While resuming, we should be considered suspended still.  Only once
    # resumed will we be active (which is represented by the RUNNING state)
    pvm_bp.LPARState.RESUMING: power_state.SUSPENDED,
    pvm_bp.LPARState.SUSPENDED: power_state.SUSPENDED,

    pvm_bp.LPARState.ERROR: power_state.CRASHED}


def get_lpar_names(adp):
    """Get a list of the LPAR names."""
    return [x.name for x in pvm_lpar.LPAR.search(adp, is_mgmt_partition=False)]


def get_pvm_uuid(instance):
    """Get the corresponding PowerVM VM uuid of an instance uuid.

    Maps a OpenStack instance uuid to a PowerVM uuid.  The UUID between the
    Nova instance and PowerVM will be 1 to 1 mapped.  This method runs the
    algorithm against the instance's uuid to convert it to the PowerVM
    UUID.

    :param instance: nova.objects.instance.Instance.
    :return: The PowerVM UUID for the LPAR corresponding to the instance.
    """
    return pvm_uuid.convert_uuid_to_pvm(instance.uuid).upper()


def get_instance_wrapper(adapter, instance):
    """Get the LPAR wrapper for a given Nova instance.

    :param adapter: The adapter for the pypowervm API
    :param instance: The nova instance.
    :return: The pypowervm logical_partition wrapper.
    """
    pvm_inst_uuid = get_pvm_uuid(instance)
    try:
        return pvm_lpar.LPAR.get(adapter, uuid=pvm_inst_uuid)
    except pvm_exc.Error as e:
        with excutils.save_and_reraise_exception(logger=LOG) as sare:
            LOG.exception("Failed to retrieve LPAR associated with instance.",
                          instance=instance)
            if e.response is not None and e.response.status == 404:
                sare.reraise = False
                raise exc.InstanceNotFound(instance_id=pvm_inst_uuid)


def power_on(adapter, instance):
    """Powers on a VM.

    :param adapter: A pypowervm.adapter.Adapter.
    :param instance: The nova instance to power on.
    :raises: InstancePowerOnFailure
    """
    # Synchronize power-on and power-off ops on a given instance
    with lockutils.lock('power_%s' % instance.uuid):
        entry = get_instance_wrapper(adapter, instance)
        # Get the current state and see if we can start the VM
        if entry.state in _POWERVM_STARTABLE_STATE:
            # Now start the lpar
            try:
                power.power_on(entry, None)
            except pvm_exc.Error as e:
                LOG.exception("PowerVM error during power_on.",
                              instance=instance)
                raise exc.InstancePowerOnFailure(reason=six.text_type(e))


def power_off(adapter, instance, force_immediate=False):
    """Powers off a VM.

    :param adapter: A pypowervm.adapter.Adapter.
    :param instance: The nova instance to power off.
    :param force_immediate: (Optional, Default False) Should it be immediately
                            shut down.
    :raises: InstancePowerOffFailure
    """
    # Synchronize power-on and power-off ops on a given instance
    with lockutils.lock('power_%s' % instance.uuid):
        entry = get_instance_wrapper(adapter, instance)
        # Get the current state and see if we can stop the VM
        LOG.debug("Powering off request for instance %(inst)s which is in "
                  "state %(state)s.  Force Immediate Flag: %(force)s.",
                  {'inst': instance.name, 'state': entry.state,
                   'force': force_immediate})
        if entry.state in _POWERVM_STOPPABLE_STATE:
            # Now stop the lpar
            try:
                LOG.debug("Power off executing for instance %(inst)s.",
                          {'inst': instance.name})
                force_flag = (power.Force.TRUE if force_immediate
                              else power.Force.ON_FAILURE)
                power.power_off(entry, None, force_immediate=force_flag)
            except pvm_exc.Error as e:
                LOG.exception("PowerVM error during power_off.",
                              instance=instance)
                raise exc.InstancePowerOffFailure(reason=six.text_type(e))
        else:
            LOG.debug("Power off not required for instance %(inst)s.",
                      {'inst': instance.name})


def delete_lpar(adapter, instance):
    """Delete an LPAR.

    :param adapter: The adapter for the pypowervm API.
    :param instance: The nova instance corresponding to the lpar to delete.
    """
    lpar_uuid = get_pvm_uuid(instance)
    # Attempt to delete the VM. To avoid failures due to open vterm, we will
    # attempt to close the vterm before issuing the delete.
    try:
        LOG.info('Deleting virtual machine.', instance=instance)
        # Ensure any vterms are closed.  Will no-op otherwise.
        vterm.close_vterm(adapter, lpar_uuid)
        # Run the LPAR delete
        resp = adapter.delete(pvm_lpar.LPAR.schema_type, root_id=lpar_uuid)
        LOG.info('Virtual machine delete status: %d', resp.status,
                 instance=instance)
        return resp
    except pvm_exc.HttpError as e:
        with excutils.save_and_reraise_exception(logger=LOG) as sare:
            if e.response and e.response.status == 404:
                # LPAR is already gone - don't fail
                sare.reraise = False
                LOG.info('Virtual Machine not found', instance=instance)
            else:
                LOG.error('HttpError deleting virtual machine.',
                          instance=instance)
    except pvm_exc.Error:
        with excutils.save_and_reraise_exception(logger=LOG):
            # Attempting to close vterm did not help so raise exception
            LOG.error('Virtual machine delete failed: LPARID=%s', lpar_uuid)


def create_lpar(adapter, host_w, instance):
    """Create an LPAR based on the host based on the instance.

    :param adapter: The adapter for the pypowervm API.
    :param host_w: The host's System wrapper.
    :param instance: The nova instance.
    :return: The LPAR wrapper response from the API.
    """
    try:
        # Translate the nova flavor into a PowerVM Wrapper Object.
        lpar_b = VMBuilder(host_w, adapter).lpar_builder(instance)
        pending_lpar_w = lpar_b.build()
        # Run validation against it.  This is just for nice(r) error messages.
        pvm_vldn.LPARWrapperValidator(pending_lpar_w,
                                      host_w).validate_all()
        # Create it. The API returns a new wrapper with the actual system data.
        return pending_lpar_w.create(parent=host_w)
    except lpar_bldr.LPARBuilderException as e:
        # Raise the BuildAbortException since LPAR failed to build
        raise exc.BuildAbortException(instance_uuid=instance.uuid, reason=e)
    except pvm_exc.HttpError as he:
        # Raise the API exception
        LOG.exception("PowerVM HttpError creating LPAR.", instance=instance)
        raise exc.PowerVMAPIFailed(inst_name=instance.name, reason=he)


def _translate_vm_state(pvm_state):
    """Find the current state of the lpar.

    :return: The appropriate integer state value from power_state, converted
             from the PowerVM state.
    """
    if pvm_state is None:
        return power_state.NOSTATE
    try:
        return _POWERVM_TO_NOVA_STATE[pvm_state.lower()]
    except KeyError:
        return power_state.NOSTATE


def get_vm_qp(adapter, lpar_uuid, qprop=None, log_errors=True):
    """Returns one or all quick properties of an LPAR.

    :param adapter: The pypowervm adapter.
    :param lpar_uuid: The (powervm) UUID for the LPAR.
    :param qprop: The quick property key to return.  If specified, that single
                  property value is returned.  If None/unspecified, all quick
                  properties are returned in a dictionary.
    :param log_errors: Indicator whether to log REST data after an exception
    :return: Either a single quick property value or a dictionary of all quick
             properties.
    """
    kwds = dict(root_id=lpar_uuid, suffix_type='quick', suffix_parm=qprop)
    if not log_errors:
        # Remove the log helper from the list of helpers.
        # Note that adapter.helpers returns a copy - the .remove doesn't affect
        # the adapter's original helpers list.
        helpers = adapter.helpers
        try:
            helpers.remove(pvm_log.log_helper)
        except ValueError:
            # It's not an error if we didn't find it.
            pass
        kwds['helpers'] = helpers
    try:
        resp = adapter.read(pvm_lpar.LPAR.schema_type, **kwds)
    except pvm_exc.HttpError as e:
        with excutils.save_and_reraise_exception(logger=LOG) as sare:
            # 404 error indicates the LPAR has been deleted
            if e.response and e.response.status == 404:
                sare.reraise = False
                raise exc.InstanceNotFound(instance_id=lpar_uuid)
            # else raise the original exception
    return jsonutils.loads(resp.body)


class VMBuilder(object):
    """Converts a Nova Instance/Flavor into a pypowervm LPARBuilder."""
    def __init__(self, host_w, adapter):
        """Initialize the converter.

        :param host_w: The host System wrapper.
        :param adapter: The pypowervm.adapter.Adapter for the PowerVM REST API.
        """
        self.adapter = adapter
        self.stdz = lpar_bldr.DefaultStandardize(host_w)

    def lpar_builder(self, inst):
        """Returns the pypowervm LPARBuilder for a given Nova flavor.

        :param inst: the VM instance
        """
        attrs = {
            lpar_bldr.NAME: pvm_u.sanitize_partition_name_for_api(inst.name),
            lpar_bldr.UUID: get_pvm_uuid(inst),
            lpar_bldr.MEM: inst.flavor.memory_mb,
            lpar_bldr.VCPU: inst.flavor.vcpus}
        # TODO(efried): Loop through the extra specs and process powervm keys
        # TODO(thorst, efried) Add in IBMi attributes
        return lpar_bldr.LPARBuilder(self.adapter, attrs, self.stdz)


class InstanceInfo(hardware.InstanceInfo):
    """Instance Information

    This object tries to lazy load the attributes since the compute
    manager retrieves it a lot just to check the status and doesn't need
    all the attributes.

    :param adapter: pypowervm adapter
    :param instance: nova instance
    """
    _QP_STATE = 'PartitionState'

    def __init__(self, adapter, instance):
        self._adapter = adapter
        # This is the PowerVM LPAR UUID (not the instance (UU)ID).
        self.id = get_pvm_uuid(instance)
        self._state = None

    @property
    def state(self):
        # return the state if we previously loaded it
        if self._state is not None:
            return self._state
        # otherwise, fetch the value now
        pvm_state = get_vm_qp(self._adapter, self.id, self._QP_STATE)
        self._state = _translate_vm_state(pvm_state)
        return self._state
