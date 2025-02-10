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

import os_traits
from oslo_log import log as logging
from oslo_utils import timeutils

import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.network import neutron
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils
from nova.virt import hardware

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
TENANT_METADATA_KEY = 'filter_tenant_id'


def trace_request_filter(fn):
    @functools.wraps(fn)
    def wrapper(ctxt, request_spec):
        timer = timeutils.StopWatch()
        ran = False
        with timer:
            try:
                ran = fn(ctxt, request_spec)
            finally:
                if ran:
                    # Only log info if the filter was enabled and not
                    # excluded for some reason
                    LOG.debug('Request filter %r took %.1f seconds',
                        fn.__name__, timer.elapsed())
        return ran
    return wrapper


@trace_request_filter
def isolate_aggregates(ctxt, request_spec):
    """Prepare list of aggregates that should be isolated.

    This filter will prepare the list of aggregates that should be
    ignored by the placement service. It checks if aggregates has metadata
    'trait:<trait_name>='required' and if <trait_name> is not present in
    either of flavor extra specs or image properties, then those aggregates
    will be included in the list of isolated aggregates.

    Precisely this filter gets the trait request form the image and
    flavor and unions them. Then it accumulates the set of aggregates that
    request traits are "non_matching_by_metadata_keys" and uses that to
    produce the list of isolated aggregates.
    """

    if not CONF.scheduler.enable_isolated_aggregate_filtering:
        return False

    # Get required traits set in flavor and image
    res_req = utils.ResourceRequest.from_request_spec(request_spec)
    required_traits = res_req.all_required_traits

    keys = ['trait:%s' % trait for trait in required_traits]

    isolated_aggregates = (
        objects.aggregate.AggregateList.get_non_matching_by_metadata_keys(
            ctxt, keys, 'trait:', value='required'))

    # Set list of isolated aggregates to destination object of request_spec
    if isolated_aggregates:
        if ('requested_destination' not in request_spec or
                request_spec.requested_destination is None):
            request_spec.requested_destination = objects.Destination()

        destination = request_spec.requested_destination
        destination.append_forbidden_aggregates(
            agg.uuid for agg in isolated_aggregates)

    return True


@trace_request_filter
def require_tenant_aggregate(ctxt, request_spec):
    """Require hosts in an aggregate based on tenant id.

    This will modify request_spec to request hosts in an aggregate
    defined specifically for the tenant making the request. We do that
    by looking for a nova host aggregate with metadata indicating which
    tenant it is for, and passing that aggregate uuid to placement to
    limit results accordingly.
    """

    enabled = CONF.scheduler.limit_tenants_to_placement_aggregate
    agg_required = CONF.scheduler.placement_aggregate_required_for_tenants
    if not enabled:
        return False

    aggregates = objects.AggregateList.get_by_metadata(
        ctxt, value=request_spec.project_id)
    aggregate_uuids_for_tenant = set([])
    for agg in aggregates:
        for key, value in agg.metadata.items():
            if key.startswith(TENANT_METADATA_KEY):
                aggregate_uuids_for_tenant.add(agg.uuid)
                break

    if aggregate_uuids_for_tenant:
        if ('requested_destination' not in request_spec or
                request_spec.requested_destination is None):
            request_spec.requested_destination = objects.Destination()
        destination = request_spec.requested_destination
        destination.require_aggregates(aggregate_uuids_for_tenant)
        LOG.debug('require_tenant_aggregate request filter added '
                  'aggregates %s for tenant %r',
                  ','.join(aggregate_uuids_for_tenant),
                  request_spec.project_id)
    elif agg_required:
        LOG.warning('Tenant %(tenant)s has no available aggregates',
                    {'tenant': request_spec.project_id})
        raise exception.RequestFilterFailed(
            reason=_('No hosts available for tenant'))

    return True


@trace_request_filter
def map_az_to_placement_aggregate(ctxt, request_spec):
    """Map requested nova availability zones to placement aggregates.

    This will modify request_spec to request hosts in an aggregate that
    matches the desired AZ of the user's request.
    """

    az_hint = request_spec.availability_zone
    if not az_hint:
        return False

    aggregates = objects.AggregateList.get_by_metadata(ctxt,
                                                       key='availability_zone',
                                                       value=az_hint)
    if aggregates:
        if ('requested_destination' not in request_spec or
                request_spec.requested_destination is None):
            request_spec.requested_destination = objects.Destination()
        agg_uuids = [agg.uuid for agg in aggregates]
        request_spec.requested_destination.require_aggregates(agg_uuids)
        LOG.debug('map_az_to_placement_aggregate request filter added '
                  'aggregates %s for az %r',
                  ','.join(agg_uuids),
                  az_hint)

    return True


@trace_request_filter
def require_image_type_support(ctxt, request_spec):
    """Request type-specific trait on candidates.

    This will modify the request_spec to request hosts that support the
    disk_format of the image provided.
    """
    if not CONF.scheduler.query_placement_for_image_type_support:
        return False

    if request_spec.is_bfv:
        # We are booting from volume, and thus compute node image
        # disk_format support does not matter.
        return False

    disk_format = request_spec.image.disk_format
    trait_name = 'COMPUTE_IMAGE_TYPE_%s' % disk_format.upper()
    if not hasattr(os_traits, trait_name):
        LOG.error(
            'Computed trait name %r is not valid; is os-traits up to date?',
            trait_name)
        return False

    request_spec.root_required.add(trait_name)

    LOG.debug('require_image_type_support request filter added required '
              'trait %s', trait_name)

    return True


@trace_request_filter
def transform_image_metadata(ctxt, request_spec):
    """Transform image metadata to required traits.

    This will modify the request_spec to request hosts that support
    virtualisation capabilities based on the image metadata properties.
    """
    if not CONF.scheduler.image_metadata_prefilter:
        return False

    prefix_map = {
        'hw_cdrom_bus': 'COMPUTE_STORAGE_BUS',
        'hw_disk_bus': 'COMPUTE_STORAGE_BUS',
        'hw_video_model': 'COMPUTE_GRAPHICS_MODEL',
        'hw_vif_model': 'COMPUTE_NET_VIF_MODEL',
        'hw_architecture': 'HW_ARCH',
        'hw_emulation_architecture': 'COMPUTE_ARCH',
        'hw_viommu_model': 'COMPUTE_VIOMMU',
    }

    trait_names = []

    for key, prefix in prefix_map.items():
        if key in request_spec.image.properties:
            value = request_spec.image.properties.get(key).replace(
                '-', '_').upper()
            trait_name = f'{prefix}_{value}'
            if not hasattr(os_traits, trait_name):
                LOG.error('Computed trait name %r is not valid; '
                          'is os-traits up to date?', trait_name)
                return False

            trait_names.append(trait_name)

    for trait_name in trait_names:
        LOG.debug(
            'transform_image_metadata request filter added required '
            'trait %s', trait_name
        )
        request_spec.root_required.add(trait_name)

    return True


@trace_request_filter
def compute_status_filter(ctxt, request_spec):
    """Pre-filter compute node resource providers using COMPUTE_STATUS_DISABLED

    The ComputeFilter filters out hosts for compute services that are
    disabled. Compute node resource providers managed by a disabled compute
    service should have the COMPUTE_STATUS_DISABLED trait set and be excluded
    by this mandatory pre-filter.
    """
    trait_name = os_traits.COMPUTE_STATUS_DISABLED
    request_spec.root_forbidden.add(trait_name)
    LOG.debug('compute_status_filter request filter added forbidden '
              'trait %s', trait_name)
    return True


@trace_request_filter
def accelerators_filter(ctxt, request_spec):
    """Allow only compute nodes with accelerator support.

    This filter retains only nodes whose compute manager published the
    COMPUTE_ACCELERATORS trait, thus indicating the version of n-cpu is
    sufficient to handle accelerator requests.
    """
    trait_name = os_traits.COMPUTE_ACCELERATORS
    if request_spec.flavor.extra_specs.get('accel:device_profile'):
        request_spec.root_required.add(trait_name)
        LOG.debug('accelerators_filter request filter added required '
                  'trait %s', trait_name)
    return True


@trace_request_filter
def packed_virtqueue_filter(ctxt, request_spec):
    """Allow only compute nodes with Packed virtqueue.

    This filter retains only nodes whose compute manager published the
    COMPUTE_NET_VIRTIO_PACKED trait, thus indicates virtqueue packed feature.
    """
    trait_name = os_traits.COMPUTE_NET_VIRTIO_PACKED
    if (hardware.get_packed_virtqueue_constraint(request_spec.flavor,
                                                 request_spec.image)):
        request_spec.root_required.add(trait_name)
        LOG.debug('virtqueue_filter request filter added required '
                  'trait %s', trait_name)
    return True


@trace_request_filter
def routed_networks_filter(
    ctxt: nova_context.RequestContext,
    request_spec: 'objects.RequestSpec'
) -> bool:
    """Adds requested placement aggregates that match requested networks.

    This will modify request_spec to request hosts in aggregates that
    matches segment IDs related to requested networks.

    :param ctxt: The usual suspect for a context object.
    :param request_spec: a classic RequestSpec object containing the request.
    :returns: True if the filter was used or False if not.
    :raises: exception.InvalidRoutedNetworkConfiguration if something went
             wrong when trying to get the related segment aggregates.
    """
    if not CONF.scheduler.query_placement_for_routed_network_aggregates:
        return False

    # NOTE(sbauza): On a create operation with no specific network request, we
    # allocate the network only after scheduling when the nova-compute service
    # calls Neutron. In this case, here we just want to accept any destination
    # as fine.
    # NOTE(sbauza): This could be also going from an old compute reschedule.
    if 'requested_networks' not in request_spec:
        return True

    # This object field is not nullable
    requested_networks = request_spec.requested_networks

    # NOTE(sbauza): This field could be not created yet.
    if (
        'requested_destination' not in request_spec or
        request_spec.requested_destination is None
    ):
        request_spec.requested_destination = objects.Destination()

    # Get the clients we need
    network_api = neutron.API()
    report_api = report.report_client_singleton()

    for requested_network in requested_networks:
        network_id = None
        # Check for a specifically requested network ID.
        if "port_id" in requested_network and requested_network.port_id:
            # We have to lookup the port to see which segment(s) to support.
            port = network_api.show_port(ctxt, requested_network.port_id)[
                "port"
            ]
            if port['fixed_ips']:
                # The instance already exists with a related subnet. We need to
                # stick on this subnet.
                # NOTE(sbauza): In case of multiple IPs, we could have more
                # subnets than only one but given they would be for the same
                # port, just looking at the first subnet is needed.
                subnet_id = port['fixed_ips'][0]['subnet_id']
                try:
                    aggregates = utils.get_aggregates_for_routed_subnet(
                        ctxt, network_api, report_api, subnet_id)
                except exception.InvalidRoutedNetworkConfiguration as e:
                    raise exception.RequestFilterFailed(
                        reason=_('Aggregates not found for the subnet %s'
                        ) % subnet_id) from e
            else:
                # The port was just created without a subnet.
                network_id = port["network_id"]
        elif (
            "network_id" in requested_network and requested_network.network_id
        ):
            network_id = requested_network.network_id

        if network_id:
            # As the user only requested a network or a port unbound to a
            # segment, we are free to choose any segment from the network.
            try:
                aggregates = utils.get_aggregates_for_routed_network(
                    ctxt, network_api, report_api, network_id)
            except exception.InvalidRoutedNetworkConfiguration as e:
                raise exception.RequestFilterFailed(
                    reason=_('Aggregates not found for the network %s'
                    ) % network_id) from e

        if aggregates:
            LOG.debug(
                'routed_networks_filter request filter added the following '
                'aggregates for network ID %s: %s',
                network_id, ', '.join(aggregates))
            # NOTE(sbauza): All of the aggregates from this request will be
            # accepted, but they will have an AND relationship with any other
            # requested aggregate, like for another NIC request in this loop.
            request_spec.requested_destination.require_aggregates(aggregates)

    return True


@trace_request_filter
def remote_managed_ports_filter(
    context: nova_context.RequestContext,
    request_spec: 'objects.RequestSpec',
) -> bool:
    """Filter out hosts without remote managed port support (driver or hw).

    If a request spec contains VNIC_TYPE_REMOTE_MANAGED ports then a
    remote-managed port trait (COMPUTE_REMOTE_MANAGED_PORTS) is added to
    the request in order to pre-filter hosts that do not use compute
    drivers supporting remote managed ports and the ones that do not have
    the device pools providing remote-managed ports (actual device
    availability besides a pool presence check is done at the time of
    PciPassthroughFilter execution).
    """
    if request_spec.requested_networks:
        network_api = neutron.API()
        for request_net in request_spec.requested_networks:
            if request_net.port_id and network_api.is_remote_managed_port(
                context, request_net.port_id):
                request_spec.root_required.add(
                    os_traits.COMPUTE_REMOTE_MANAGED_PORTS)
                LOG.debug('remote_managed_ports_filter request filter added '
                          f'trait {os_traits.COMPUTE_REMOTE_MANAGED_PORTS}')
    return True


@trace_request_filter
def ephemeral_encryption_filter(
    ctxt: nova_context.RequestContext,
    request_spec: 'objects.RequestSpec'
) -> bool:
    """Pre-filter resource provides by ephemeral encryption support

    This filter will only retain compute node resource providers that support
    ephemeral storage encryption when the associated image properties or flavor
    extra specs are present within the request spec.
    """
    # Skip if ephemeral encryption isn't requested in the flavor or image
    if not hardware.get_ephemeral_encryption_constraint(
            request_spec.flavor, request_spec.image):
        LOG.debug("ephemeral_encryption_filter skipped")
        return False

    # Always add the feature trait regardless of the format being provided
    request_spec.root_required.add(os_traits.COMPUTE_EPHEMERAL_ENCRYPTION)
    LOG.debug("ephemeral_encryption_filter added trait "
              "COMPUTE_EPHEMERAL_ENCRYPTION")

    # Try to find the format in the flavor or image and add as a trait
    eph_format = hardware.get_ephemeral_encryption_format(
        request_spec.flavor, request_spec.image)
    if eph_format:
        # We don't need to validate the trait here because the earlier call to
        # get_ephemeral_encryption_format will raise if it is not valid
        trait_name = f"COMPUTE_EPHEMERAL_ENCRYPTION_{eph_format.upper()}"
        request_spec.root_required.add(trait_name)
        LOG.debug(f"ephemeral_encryption_filter added trait {trait_name}")

    return True


ALL_REQUEST_FILTERS = [
    require_tenant_aggregate,
    map_az_to_placement_aggregate,
    require_image_type_support,
    compute_status_filter,
    isolate_aggregates,
    transform_image_metadata,
    accelerators_filter,
    packed_virtqueue_filter,
    routed_networks_filter,
    remote_managed_ports_filter,
    ephemeral_encryption_filter,
]


def process_reqspec(ctxt, request_spec):
    """Process an objects.ReqestSpec before calling placement.

    :param ctxt: A RequestContext
    :param request_spec: An objects.RequestSpec to be inspected/modified
    """
    for filter in ALL_REQUEST_FILTERS:
        filter(ctxt, request_spec)
