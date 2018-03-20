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

import re

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import strutils as stru
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as pvm_log
from pypowervm.tasks import power
from pypowervm.tasks import power_opts as popts
from pypowervm.tasks import vterm
from pypowervm import util as pvm_u
from pypowervm.utils import lpar_builder as lpar_bldr
from pypowervm.utils import uuid as pvm_uuid
from pypowervm.utils import validation as pvm_vldn
from pypowervm.wrappers import base_partition as pvm_bp
from pypowervm.wrappers import logical_partition as pvm_lpar
from pypowervm.wrappers import network as pvm_net
from pypowervm.wrappers import shared_proc_pool as pvm_spp
import six

from nova.compute import power_state
from nova import conf
from nova import exception as exc
from nova.i18n import _
from nova.virt import hardware


CONF = conf.CONF
LOG = logging.getLogger(__name__)

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


def get_cnas(adapter, instance, **search):
    """Returns the (possibly filtered) current CNAs on the instance.

    The Client Network Adapters are the Ethernet adapters for a VM.

    :param adapter: The pypowervm adapter.
    :param instance: The nova instance.
    :param search: Keyword arguments for CNA.search.  If omitted, all CNAs are
                   returned.
    :return The CNA wrappers that represent the ClientNetworkAdapters on the VM
    """
    meth = pvm_net.CNA.search if search else pvm_net.CNA.get

    return meth(adapter, parent_type=pvm_lpar.LPAR,
                parent_uuid=get_pvm_uuid(instance), **search)


def get_lpar_names(adp):
    """Get a list of the LPAR names.

    :param adp: A pypowervm.adapter.Adapter instance for the PowerVM API.
    :return: A list of string names of the PowerVM Logical Partitions.
    """
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


def power_off(adapter, instance, force_immediate=False, timeout=None):
    """Powers off a VM.

    :param adapter: A pypowervm.adapter.Adapter.
    :param instance: The nova instance to power off.
    :param timeout: (Optional, Default None) How long to wait for the job
                    to complete.  By default, is None which indicates it should
                    use the default from pypowervm's power off method.
     :param force_immediate: (Optional, Default False) Should it be immediately
                            shut down.
    :raises: InstancePowerOffFailure
    """
    # Synchronize power-on and power-off ops on a given instance
    with lockutils.lock('power_%s' % instance.uuid):
        entry = get_instance_wrapper(adapter, instance)
        # Get the current state and see if we can stop the VM
        LOG.debug("Powering off request for instance in state %(state)s. "
                  "Force Immediate Flag: %(force)s.",
                  {'state': entry.state, 'force': force_immediate},
                  instance=instance)
        if entry.state in _POWERVM_STOPPABLE_STATE:
            # Now stop the lpar
            try:
                LOG.debug("Power off executing.", instance=instance)
                kwargs = {'timeout': timeout} if timeout else {}
                if force_immediate:
                    power.PowerOp.stop(
                        entry, opts=popts.PowerOffOpts().vsp_hard(), **kwargs)
                else:
                    power.power_off_progressive(entry, **kwargs)
            except pvm_exc.Error as e:
                LOG.exception("PowerVM error during power_off.",
                              instance=instance)
                raise exc.InstancePowerOffFailure(reason=six.text_type(e))
        else:
            LOG.debug("Power off not required for instance %(inst)s.",
                      {'inst': instance.name})


def reboot(adapter, instance, hard):
    """Reboots a VM.

    :param adapter: A pypowervm.adapter.Adapter.
    :param instance: The nova instance to reboot.
    :param hard: Boolean True if hard reboot, False otherwise.
    :raises: InstanceRebootFailure
    """
    # Synchronize power-on and power-off ops on a given instance
    with lockutils.lock('power_%s' % instance.uuid):
        try:
            entry = get_instance_wrapper(adapter, instance)
            if entry.state != pvm_bp.LPARState.NOT_ACTIVATED:
                if hard:
                    power.PowerOp.stop(
                        entry, opts=popts.PowerOffOpts().vsp_hard().restart())
                else:
                    power.power_off_progressive(entry, restart=True)
            else:
                # pypowervm does NOT throw an exception if "already down".
                # Any other exception from pypowervm is a legitimate failure;
                # let it raise up.
                # If we get here, pypowervm thinks the instance is down.
                power.power_on(entry, None)
        except pvm_exc.Error as e:
            LOG.exception("PowerVM error during reboot.", instance=instance)
            raise exc.InstanceRebootFailure(reason=six.text_type(e))


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


def get_vm_info(adapter, instance):
    """Get the InstanceInfo for an instance.

    :param adapter: The pypowervm.adapter.Adapter for the PowerVM REST API.
    :param instance: nova.objects.instance.Instance object
    :returns: An InstanceInfo object.
    """
    pvm_uuid = get_pvm_uuid(instance)
    pvm_state = get_vm_qp(adapter, pvm_uuid, 'PartitionState')
    nova_state = _translate_vm_state(pvm_state)
    return hardware.InstanceInfo(nova_state)


def norm_mac(mac):
    """Normalizes a MAC address from pypowervm format to OpenStack.

    That means that the format will be converted to lower case and will
    have colons added.

    :param mac: A pypowervm mac address.  Ex. 1234567890AB
    :return: A mac that matches the standard neutron format.
             Ex. 12:34:56:78:90:ab
    """
    # Need the replacement if the mac is already normalized.
    mac = mac.lower().replace(':', '')
    return ':'.join(mac[i:i + 2] for i in range(0, len(mac), 2))


class VMBuilder(object):
    """Converts a Nova Instance/Flavor into a pypowervm LPARBuilder."""
    _PVM_PROC_COMPAT = 'powervm:processor_compatibility'
    _PVM_UNCAPPED = 'powervm:uncapped'
    _PVM_DED_SHAR_MODE = 'powervm:dedicated_sharing_mode'
    _PVM_SHAR_PROC_POOL = 'powervm:shared_proc_pool_name'
    _PVM_SRR_CAPABILITY = 'powervm:srr_capability'

    # Map of PowerVM extra specs to the lpar builder attributes.
    # '' is used for attributes that are not implemented yet.
    # None means there is no direct attribute mapping and must
    # be handled individually
    _ATTRS_MAP = {
        'powervm:min_mem': lpar_bldr.MIN_MEM,
        'powervm:max_mem': lpar_bldr.MAX_MEM,
        'powervm:min_vcpu': lpar_bldr.MIN_VCPU,
        'powervm:max_vcpu': lpar_bldr.MAX_VCPU,
        'powervm:proc_units': lpar_bldr.PROC_UNITS,
        'powervm:min_proc_units': lpar_bldr.MIN_PROC_U,
        'powervm:max_proc_units': lpar_bldr.MAX_PROC_U,
        'powervm:dedicated_proc': lpar_bldr.DED_PROCS,
        'powervm:shared_weight': lpar_bldr.UNCAPPED_WEIGHT,
        'powervm:availability_priority': lpar_bldr.AVAIL_PRIORITY,
        _PVM_UNCAPPED: None,
        _PVM_DED_SHAR_MODE: None,
        _PVM_PROC_COMPAT: None,
        _PVM_SHAR_PROC_POOL: None,
        _PVM_SRR_CAPABILITY: None,
    }

    _DED_SHARING_MODES_MAP = {
        'share_idle_procs': pvm_bp.DedicatedSharingMode.SHARE_IDLE_PROCS,
        'keep_idle_procs': pvm_bp.DedicatedSharingMode.KEEP_IDLE_PROCS,
        'share_idle_procs_active':
            pvm_bp.DedicatedSharingMode.SHARE_IDLE_PROCS_ACTIVE,
        'share_idle_procs_always':
            pvm_bp.DedicatedSharingMode.SHARE_IDLE_PROCS_ALWAYS,
    }

    def __init__(self, host_w, adapter):
        """Initialize the converter.

        :param host_w: The host System wrapper.
        :param adapter: The pypowervm.adapter.Adapter for the PowerVM REST API.
        """
        self.adapter = adapter
        self.host_w = host_w
        kwargs = dict(proc_units_factor=CONF.powervm.proc_units_factor)
        self.stdz = lpar_bldr.DefaultStandardize(host_w, **kwargs)

    def lpar_builder(self, inst):
        """Returns the pypowervm LPARBuilder for a given Nova flavor.

        :param inst: the VM instance
        """
        attrs = self._format_flavor(inst)
        # TODO(thorst, efried) Add in IBMi attributes
        return lpar_bldr.LPARBuilder(self.adapter, attrs, self.stdz)

    def _format_flavor(self, inst):
        """Returns the pypowervm format of the flavor.

        :param inst: The Nova VM instance.
        :return: A dict that can be used by the LPAR builder.
        """
        # The attrs are what is sent to pypowervm to convert the lpar.
        attrs = {
            lpar_bldr.NAME: pvm_u.sanitize_partition_name_for_api(inst.name),
            # The uuid is only actually set on a create of an LPAR
            lpar_bldr.UUID: get_pvm_uuid(inst),
            lpar_bldr.MEM: inst.flavor.memory_mb,
            lpar_bldr.VCPU: inst.flavor.vcpus,
            # Set the srr capability to True by default
            lpar_bldr.SRR_CAPABLE: True}

        # Loop through the extra specs and process powervm keys
        for key in inst.flavor.extra_specs.keys():
            # If it is not a valid key, then can skip.
            if not self._is_pvm_valid_key(key):
                continue

            # Look for the mapping to the lpar builder
            bldr_key = self._ATTRS_MAP.get(key)

            # Check for no direct mapping, if the value is none, need to
            # derive the complex type
            if bldr_key is None:
                self._build_complex_type(key, attrs, inst.flavor)
            else:
                # We found a direct mapping
                attrs[bldr_key] = inst.flavor.extra_specs[key]

        return attrs

    def _is_pvm_valid_key(self, key):
        """Will return if this is a valid PowerVM key.

        :param key: The powervm key.
        :return: True if valid key.  False if non-powervm key and should be
                 skipped.
        """
        # If not a powervm key, then it is not 'pvm_valid'
        if not key.startswith('powervm:'):
            return False

        # Check if this is a valid attribute
        if key not in self._ATTRS_MAP:
            # Could be a key from a future release - warn, but ignore.
            LOG.warning("Unhandled PowerVM key '%s'.", key)
            return False

        return True

    def _build_complex_type(self, key, attrs, flavor):
        """If a key does not directly map, this method derives the right value.

        Some types are complex, in that the flavor may have one key that maps
        to several different attributes in the lpar builder.  This method
        handles the complex types.

        :param key: The flavor's key.
        :param attrs: The attribute map to put the value into.
        :param flavor: The Nova instance flavor.
        :return: The value to put in for the key.
        """
        # Map uncapped to sharing mode
        if key == self._PVM_UNCAPPED:
            attrs[lpar_bldr.SHARING_MODE] = (
                pvm_bp.SharingMode.UNCAPPED
                if stru.bool_from_string(flavor.extra_specs[key], strict=True)
                else pvm_bp.SharingMode.CAPPED)
        elif key == self._PVM_DED_SHAR_MODE:
            # Dedicated sharing modes...map directly
            shr_mode_key = flavor.extra_specs[key]
            mode = self._DED_SHARING_MODES_MAP.get(shr_mode_key)
            if mode is None:
                raise exc.InvalidParameterValue(err=_(
                    "Invalid dedicated sharing mode '%s'!") % shr_mode_key)
            attrs[lpar_bldr.SHARING_MODE] = mode
        elif key == self._PVM_SHAR_PROC_POOL:
            pool_name = flavor.extra_specs[key]
            attrs[lpar_bldr.SPP] = self._spp_pool_id(pool_name)
        elif key == self._PVM_PROC_COMPAT:
            # Handle variants of the supported values
            attrs[lpar_bldr.PROC_COMPAT] = re.sub(
                r'\+', '_Plus', flavor.extra_specs[key])
        elif key == self._PVM_SRR_CAPABILITY:
            attrs[lpar_bldr.SRR_CAPABLE] = stru.bool_from_string(
                flavor.extra_specs[key], strict=True)
        else:
            # There was no mapping or we didn't handle it.  This is a BUG!
            raise KeyError(_(
                "Unhandled PowerVM key '%s'!  Please report this bug.") % key)

    def _spp_pool_id(self, pool_name):
        """Returns the shared proc pool id for a given pool name.

        :param pool_name: The shared proc pool name.
        :return: The internal API id for the shared proc pool.
        """
        if (pool_name is None or
                pool_name == pvm_spp.DEFAULT_POOL_DISPLAY_NAME):
            # The default pool is 0
            return 0

        # Search for the pool with this name
        pool_wraps = pvm_spp.SharedProcPool.search(
            self.adapter, name=pool_name, parent=self.host_w)

        # Check to make sure there is a pool with the name, and only one pool.
        if len(pool_wraps) > 1:
            msg = (_('Multiple Shared Processing Pools with name %(pool)s.') %
                   {'pool': pool_name})
            raise exc.ValidationError(msg)
        elif len(pool_wraps) == 0:
            msg = (_('Unable to find Shared Processing Pool %(pool)s') %
                   {'pool': pool_name})
            raise exc.ValidationError(msg)

        # Return the singular pool id.
        return pool_wraps[0].id
