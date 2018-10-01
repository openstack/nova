# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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
import inspect

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import excutils

from nova.db import base
from nova import hooks
from nova.i18n import _, _LE
from nova.network import model as network_model
from nova import objects


LOG = logging.getLogger(__name__)


@hooks.add_hook('instance_network_info')
def update_instance_cache_with_nw_info(impl, context, instance,
                                       nw_info=None, update_cells=True):
    if instance.deleted:
        LOG.debug('Instance is deleted, no further info cache update',
                  instance=instance)
        return

    try:
        if not isinstance(nw_info, network_model.NetworkInfo):
            nw_info = None
        if nw_info is None:
            nw_info = impl._get_instance_nw_info(context, instance)

        LOG.debug('Updating instance_info_cache with network_info: %s',
                  nw_info, instance=instance)

        # NOTE(comstud): The save() method actually handles updating or
        # creating the instance.  We don't need to retrieve the object
        # from the DB first.
        ic = objects.InstanceInfoCache.new(context, instance.uuid)
        ic.network_info = nw_info
        ic.save(update_cells=update_cells)
        instance.info_cache = ic
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_LE('Failed storing info cache'), instance=instance)


def refresh_cache(f):
    """Decorator to update the instance_info_cache

    Requires context and instance as function args
    """
    argspec = inspect.getargspec(f)

    @functools.wraps(f)
    def wrapper(self, context, *args, **kwargs):
        try:
            # get the instance from arguments (or raise ValueError)
            instance = kwargs.get('instance')
            if not instance:
                instance = args[argspec.args.index('instance') - 2]
        except ValueError:
            msg = _('instance is a required argument to use @refresh_cache')
            raise Exception(msg)

        with lockutils.lock('refresh_cache-%s' % instance.uuid):
            # We need to call the wrapped function with the lock held to ensure
            # that it can call _get_instance_nw_info safely.
            res = f(self, context, *args, **kwargs)
            update_instance_cache_with_nw_info(self, context, instance,
                                               nw_info=res)
        # return the original function's return value
        return res
    return wrapper


SENTINEL = object()


class NetworkAPI(base.Base):
    """Base Network API for doing networking operations.
    New operations available on specific clients must be added here as well.
    """
    def get_all(self, context):
        """Get all the networks for client."""
        raise NotImplementedError()

    def get(self, context, network_uuid):
        """Get specific network for client."""
        raise NotImplementedError()

    def create(self, context, **kwargs):
        """Create a network."""
        raise NotImplementedError()

    def delete(self, context, network_uuid):
        """Delete a specific network."""
        raise NotImplementedError()

    def disassociate(self, context, network_uuid):
        """Disassociate a network for client."""
        raise NotImplementedError()

    def get_fixed_ip(self, context, id):
        """Get fixed IP by id."""
        raise NotImplementedError()

    def get_fixed_ip_by_address(self, context, address):
        """Get fixed IP by address."""
        raise NotImplementedError()

    def get_floating_ip(self, context, id):
        """Get floating IP by id."""
        raise NotImplementedError()

    def get_floating_ip_pools(self, context):
        """Get floating IP pools."""
        raise NotImplementedError()

    def get_floating_ip_by_address(self, context, address):
        """Get floating IP by address."""
        raise NotImplementedError()

    def get_floating_ips_by_project(self, context):
        """Get floating IPs by project."""
        raise NotImplementedError()

    def get_instance_id_by_floating_address(self, context, address):
        """Get instance id by floating address."""
        raise NotImplementedError()

    def get_vifs_by_instance(self, context, instance):
        """Get vifs by instance.

        :param context: nova.context.RequestContext
        :param instance: nova.objects.instance.Instance
        :returns: nova.objects.virtual_interface.VirtualInterfaceList; the
        fields address, uuid and net_uuid should be set for each VIF object
        in the returned list.
        """
        raise NotImplementedError()

    def get_vif_by_mac_address(self, context, mac_address):
        """Get vif mac address."""
        raise NotImplementedError()

    def allocate_floating_ip(self, context, pool=None):
        """Adds (allocate) floating IP to a project from a pool."""
        raise NotImplementedError()

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes (deallocates) a floating IP with address from a project."""
        raise NotImplementedError()

    def disassociate_and_release_floating_ip(self, context, instance,
                                           floating_ip):
        """Removes (deallocates) and deletes the floating IP."""
        raise NotImplementedError()

    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating IP with a fixed IP."""
        raise NotImplementedError()

    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating IP from fixed IP it is associated with."""
        raise NotImplementedError()

    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks, macs=None,
                              security_groups=None,
                              dhcp_options=None, bind_host_id=None):
        """Allocates all network structures for an instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vpn: A boolean, if True, indicate a vpn to access the instance.
        :param requested_networks: A list of requested_networks,
            Optional value containing network_id, fixed_ip, and port_id.
        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
        :param security_groups: None or security groups to allocate for
            instance.
        :param dhcp_options: None or a set of key/value pairs that should
            determine the DHCP BOOTP response, eg. for PXE booting an instance
            configured with the baremetal hypervisor. It is expected that these
            are already formatted for the neutron v2 api.
            See nova/virt/driver.py:dhcp_options_for_instance for an example.
        :param bind_host_id: the host ID to attach to the ports being created.
        :returns: network info as from get_instance_nw_info() below
        """
        raise NotImplementedError()

    def deallocate_for_instance(self, context, instance,
                                requested_networks=None):
        """Deallocates all network structures related to instance."""
        raise NotImplementedError()

    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None,
                                   bind_host_id=None, tag=None):
        """Allocate port for instance."""
        raise NotImplementedError()

    def deallocate_port_for_instance(self, context, instance, port_id):
        """Deallocate port for instance."""
        raise NotImplementedError()

    def list_ports(self, *args, **kwargs):
        """List ports."""
        raise NotImplementedError()

    def show_port(self, *args, **kwargs):
        """Show specific port."""
        raise NotImplementedError()

    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Adds a fixed IP to instance from specified network."""
        raise NotImplementedError()

    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Removes a fixed IP from instance from specified network."""
        raise NotImplementedError()

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force adds another network to a project."""
        raise NotImplementedError()

    def associate(self, context, network_uuid, host=SENTINEL,
                  project=SENTINEL):
        """Associate or disassociate host or project to network."""
        raise NotImplementedError()

    def get_instance_nw_info(self, context, instance, **kwargs):
        """Returns all network info related to an instance."""
        with lockutils.lock('refresh_cache-%s' % instance.uuid):
            result = self._get_instance_nw_info(context, instance, **kwargs)
            # NOTE(comstud): Don't update API cell with new info_cache every
            # time we pull network info for an instance.  The periodic healing
            # of info_cache causes too many cells messages.  Healing the API
            # will happen separately.
            update_cells = kwargs.get('update_cells', False)
            update_instance_cache_with_nw_info(self, context, instance,
                                               nw_info=result,
                                               update_cells=update_cells)
        return result

    def _get_instance_nw_info(self, context, instance, **kwargs):
        """Template method, so a subclass can implement for neutron/network."""
        raise NotImplementedError()

    def create_pci_requests_for_sriov_ports(self, context,
                                            pci_requests,
                                            requested_networks):
        """Check requested networks for any SR-IOV port request.

        Create a PCI request object for each SR-IOV port, and add it to the
        pci_requests object that contains a list of PCI request object.
        """
        raise NotImplementedError()

    def validate_networks(self, context, requested_networks, num_instances):
        """validate the networks passed at the time of creating
        the server.

        Return the number of instances that can be successfully allocated
        with the requested network configuration.
        """
        raise NotImplementedError()

    def get_dns_domains(self, context):
        """Returns a list of available dns domains.
        These can be used to create DNS entries for floating IPs.
        """
        raise NotImplementedError()

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        raise NotImplementedError()

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        raise NotImplementedError()

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain."""
        raise NotImplementedError()

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
        raise NotImplementedError()

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        raise NotImplementedError()

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a public DNS domain with optional nova project."""
        raise NotImplementedError()

    def setup_networks_on_host(self, context, instance, host=None,
                                                        teardown=False):
        """Setup or teardown the network structures on hosts related to
           instance.
        """
        raise NotImplementedError()

    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance."""
        raise NotImplementedError()

    def migrate_instance_finish(self, context, instance, migration):
        """Finish migrating the network of an instance."""
        raise NotImplementedError()

    def setup_instance_network_on_host(self, context, instance, host,
                                       migration=None):
        """Setup network for specified instance on host.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param host: The host which network should be setup for instance.
        :param migration: The migration object if the instance is being
                          tracked with a migration.
        """
        raise NotImplementedError()

    def cleanup_instance_network_on_host(self, context, instance, host):
        """Cleanup network for specified instance on host.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param host: The host which network should be cleanup for instance.
        """
        raise NotImplementedError()

    def update_instance_vnic_index(self, context, instance, vif, index):
        """Update instance vnic index.

        When the 'VNIC index' extension is supported this method will update
        the vnic index of the instance on the port. A instance may have more
        than one vnic.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vif: The VIF in question.
        :param index: The index on the instance for the VIF.
        """
        pass
