# Copyright 2010-2011 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc.
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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.views import addresses as views_addresses
from nova.api.openstack.compute.views import flavors as views_flavors
from nova.api.openstack.compute.views import images as views_images
from nova import availability_zones as avail_zone
from nova.compute import api as compute
from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova.network import security_group_api
from nova import objects
from nova.objects import fields
from nova.objects import virtual_interface
from nova.policies import extended_server_attributes as esa_policies
from nova.policies import flavor_extra_specs as fes_policies
from nova.policies import servers as servers_policies
from nova import utils


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "servers"

    _progress_statuses = (
        "ACTIVE",
        "BUILD",
        "REBUILD",
        "RESIZE",
        "VERIFY_RESIZE",
        "MIGRATING",
    )

    _fault_statuses = (
        "ERROR", "DELETED"
    )

    # These are the lazy-loadable instance attributes required for showing
    # details about an instance. Add to this list as new things need to be
    # shown.
    _show_expected_attrs = ['flavor', 'info_cache', 'metadata']

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()
        self._address_builder = views_addresses.ViewBuilder()
        self._image_builder = views_images.ViewBuilder()
        self._flavor_builder = views_flavors.ViewBuilder()
        self.compute_api = compute.API()

    def create(self, request, instance):
        """View that should be returned when an instance is created."""

        server = {
            "server": {
                "id": instance["uuid"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
                # NOTE(sdague): historically this was the
                # os-disk-config extension, but now that extensions
                # are gone, we merge these attributes here.
                "OS-DCF:diskConfig": (
                    'AUTO' if instance.get('auto_disk_config') else 'MANUAL'),
            },
        }
        self._add_security_grps(request, [server["server"]], [instance],
                                create_request=True)

        return server

    def basic(self, request, instance, show_extra_specs=False,
              show_extended_attr=None, show_host_status=None,
              show_sec_grp=None, bdms=None, cell_down_support=False,
              show_user_data=False):
        """Generic, non-detailed view of an instance."""
        if cell_down_support and 'display_name' not in instance:
            # NOTE(tssurya): If the microversion is >= 2.69, this boolean will
            # be true in which case we check if there are instances from down
            # cells (by checking if their objects have missing keys like
            # `display_name`) and return partial constructs based on the
            # information available from the nova_api database.
            return {
                "server": {
                    "id": instance.uuid,
                    "status": "UNKNOWN",
                    "links": self._get_links(request,
                                             instance.uuid,
                                             self._collection_name),
                },
            }
        return {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }

    def get_show_expected_attrs(self, expected_attrs=None):
        """Returns a list of lazy-loadable expected attributes used by show

        This should be used when getting the instances from the database so
        that the necessary attributes are pre-loaded before needing to build
        the show response where lazy-loading can fail if an instance was
        deleted.

        :param list expected_attrs: The list of expected attributes that will
            be requested in addition to what this view builder requires. This
            method will merge the two lists and return what should be
            ultimately used when getting an instance from the database.
        :returns: merged and sorted list of expected attributes
        """
        if expected_attrs is None:
            expected_attrs = []
        # NOTE(mriedem): We sort the list so we can have predictable test
        # results.
        return sorted(list(set(self._show_expected_attrs + expected_attrs)))

    def _show_from_down_cell(self, request, instance, show_extra_specs,
                             show_server_groups):
        """Function that constructs the partial response for the instance."""
        ret = {
            "server": {
                "id": instance.uuid,
                "status": "UNKNOWN",
                "tenant_id": instance.project_id,
                "created": utils.isotime(instance.created_at),
                "links": self._get_links(
                    request, instance.uuid, self._collection_name),
            },
        }
        if 'flavor' in instance:
            # If the key 'flavor' is present for an instance from a down cell
            # it means that the request is ``GET /servers/{server_id}`` and
            # thus we include the information from the request_spec of the
            # instance like its flavor, image, avz, and user_id in addition to
            # the basic information from its instance_mapping.
            # If 'flavor' key is not present for an instance from a down cell
            # down cell it means the request is ``GET /servers/detail`` and we
            # do not expose the flavor in the response when listing servers
            # with details for performance reasons of fetching it from the
            # request specs table for the whole list of instances.
            ret["server"]["image"] = self._get_image(request, instance)
            ret["server"]["flavor"] = self._get_flavor(request, instance,
                                                       show_extra_specs)
            # in case availability zone was not requested by the user during
            # boot time, return UNKNOWN.
            avz = instance.availability_zone or "UNKNOWN"
            ret["server"]["OS-EXT-AZ:availability_zone"] = avz
            ret["server"]["OS-EXT-STS:power_state"] = instance.power_state
            # in case its an old request spec which doesn't have the user_id
            # data migrated, return UNKNOWN.
            ret["server"]["user_id"] = instance.user_id or "UNKNOWN"
            if show_server_groups:
                context = request.environ['nova.context']
                ret['server']['server_groups'] = self._get_server_groups(
                                                             context, instance)
        return ret

    @staticmethod
    def _get_host_status_unknown_only(context, instance=None):
        """We will use the unknown_only variable to tell us what host status we
        can show, if any:
          * unknown_only = False means we can show any host status.
          * unknown_only = True means that we can only show host
            status: UNKNOWN. If the host status is anything other than
            UNKNOWN, we will not include the host_status field in the
            response.
          * unknown_only = None means we cannot show host status at all and
            we will not include the host_status field in the response.
        """
        unknown_only = None
        # Check show:host_status policy first because if it passes, we know we
        # can show any host status and need not check the more restrictive
        # show:host_status:unknown-only policy.
        # Keeping target as None (which means policy will default these target
        # to context.project_id) for now which is case of 'detail' API which
        # policy is default to system and project reader.
        target = None
        if instance is not None:
            target = {'project_id': instance.project_id}
        if context.can(
                servers_policies.SERVERS % 'show:host_status',
                fatal=False, target=target):
            unknown_only = False
        # If we are not allowed to show any/all host status, check if we can at
        # least show only the host status: UNKNOWN.
        elif context.can(
                servers_policies.SERVERS %
                'show:host_status:unknown-only',
                fatal=False,
                target=target):
            unknown_only = True
        return unknown_only

    def show(self, request, instance, extend_address=True,
             show_extra_specs=None, show_AZ=True, show_config_drive=True,
             show_extended_attr=None, show_host_status=None,
             show_keypair=True, show_srv_usg=True, show_sec_grp=True,
             show_extended_status=True, show_extended_volumes=True,
             bdms=None, cell_down_support=False, show_server_groups=False,
             show_user_data=True):
        """Detailed view of a single instance."""
        if show_extra_specs is None:
            # detail will pre-calculate this for us. If we're doing show,
            # then figure it out here.
            show_extra_specs = False
            if api_version_request.is_supported(request, min_version='2.47'):
                context = request.environ['nova.context']
                show_extra_specs = context.can(
                    fes_policies.POLICY_ROOT % 'index', fatal=False)

        if cell_down_support and 'display_name' not in instance:
            # NOTE(tssurya): If the microversion is >= 2.69, this boolean will
            # be true in which case we check if there are instances from down
            # cells (by checking if their objects have missing keys like
            # `display_name`) and return partial constructs based on the
            # information available from the nova_api database.
            return self._show_from_down_cell(
                request, instance, show_extra_specs, show_server_groups)
        ip_v4 = instance.get('access_ip_v4')
        ip_v6 = instance.get('access_ip_v6')

        server = {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "status": self._get_vm_status(instance),
                "tenant_id": instance.get("project_id") or "",
                "user_id": instance.get("user_id") or "",
                "metadata": self._get_metadata(instance),
                "hostId": self._get_host_id(instance),
                "image": self._get_image(request, instance),
                "flavor": self._get_flavor(request, instance,
                                           show_extra_specs),
                "created": utils.isotime(instance["created_at"]),
                "updated": utils.isotime(instance["updated_at"]),
                "addresses": self._get_addresses(request, instance,
                                                 extend_address),
                "accessIPv4": str(ip_v4) if ip_v4 is not None else '',
                "accessIPv6": str(ip_v6) if ip_v6 is not None else '',
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
                # NOTE(sdague): historically this was the
                # os-disk-config extension, but now that extensions
                # are gone, we merge these attributes here.
                "OS-DCF:diskConfig": (
                    'AUTO' if instance.get('auto_disk_config') else 'MANUAL'),
            },
        }
        if server["server"]["status"] in self._fault_statuses:
            _inst_fault = self._get_fault(request, instance)
            if _inst_fault:
                server['server']['fault'] = _inst_fault

        if server["server"]["status"] in self._progress_statuses:
            server["server"]["progress"] = instance.get("progress", 0)

        context = request.environ['nova.context']
        if show_AZ:
            az = avail_zone.get_instance_availability_zone(context, instance)
            # NOTE(mriedem): The OS-EXT-AZ prefix should not be used for new
            # attributes after v2.1. They are only in v2.1 for backward compat
            # with v2.0.
            server["server"]["OS-EXT-AZ:availability_zone"] = az or ''

        if show_config_drive:
            server["server"]["config_drive"] = instance["config_drive"]

        if show_keypair:
            server["server"]["key_name"] = instance["key_name"]

        if show_srv_usg:
            for k in ['launched_at', 'terminated_at']:
                key = "OS-SRV-USG:" + k
                # NOTE(danms): Historically, this timestamp has been generated
                # merely by grabbing str(datetime) of a TZ-naive object. The
                # only way we can keep that with instance objects is to strip
                # the tzinfo from the stamp and str() it.
                server["server"][key] = (instance[k].replace(tzinfo=None)
                                         if instance[k] else None)
        if show_sec_grp:
            self._add_security_grps(request, [server["server"]], [instance])

        if show_extended_attr is None:
            show_extended_attr = context.can(
                esa_policies.BASE_POLICY_NAME, fatal=False,
                target={'project_id': instance.project_id})
        if show_extended_attr:
            properties = ['host', 'name', 'node']
            if api_version_request.is_supported(request, min_version='2.3'):
                # NOTE(mriedem): These will use the OS-EXT-SRV-ATTR prefix
                # below and that's OK for microversion 2.3 which is being
                # compatible with v2.0 for the ec2 API split out from Nova.
                # After this, however, new microversions should not be using
                # the OS-EXT-SRV-ATTR prefix.
                properties += ['reservation_id', 'launch_index',
                               'hostname', 'kernel_id', 'ramdisk_id',
                               'root_device_name']
                # NOTE(gmann): Since microversion 2.75, PUT and Rebuild
                # response include all the server attributes including these
                # extended attributes also. But microversion 2.57 already
                # adding the 'user_data' in Rebuild response in API method.
                # so we will skip adding the user data attribute for rebuild
                # case. 'show_user_data' is false only in case of rebuild.
                if show_user_data:
                    properties += ['user_data']
            for attr in properties:
                if attr == 'name':
                    key = "OS-EXT-SRV-ATTR:instance_%s" % attr
                elif attr == 'node':
                    key = "OS-EXT-SRV-ATTR:hypervisor_hostname"
                else:
                    # NOTE(mriedem): Nothing after microversion 2.3 should use
                    # the OS-EXT-SRV-ATTR prefix for the attribute key name.
                    key = "OS-EXT-SRV-ATTR:%s" % attr
                server["server"][key] = getattr(instance, attr)
        if show_extended_status:
            # NOTE(gmann): Removed 'locked_by' from extended status
            # to make it same as V2. If needed it can be added with
            # microversion.
            for state in ['task_state', 'vm_state', 'power_state']:
                # NOTE(mriedem): The OS-EXT-STS prefix should not be used for
                # new attributes after v2.1. They are only in v2.1 for backward
                # compat with v2.0.
                key = "%s:%s" % ('OS-EXT-STS', state)
                server["server"][key] = instance[state]
        if show_extended_volumes:
            # NOTE(mriedem): The os-extended-volumes prefix should not be used
            # for new attributes after v2.1. They are only in v2.1 for backward
            # compat with v2.0.
            add_delete_on_termination = api_version_request.is_supported(
                request, min_version='2.3')
            if bdms is None:
                bdms = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
                    context, [instance["uuid"]])
            self._add_volumes_attachments(server["server"],
                                          bdms,
                                          add_delete_on_termination)
        if (api_version_request.is_supported(request, min_version='2.16')):
            if show_host_status is None:
                unknown_only = self._get_host_status_unknown_only(
                    context, instance)
                # If we're not allowed by policy to show host status at all,
                # don't bother requesting instance host status from the compute
                # API.
                if unknown_only is not None:
                    host_status = self.compute_api.get_instance_host_status(
                                      instance)
                    # If we are allowed to show host status of some kind, set
                    # the host status field only if:
                    #   * unknown_only = False, meaning we can show any status
                    # OR
                    #   * if unknown_only = True and host_status == UNKNOWN
                    if (not unknown_only or
                            host_status == fields.HostStatus.UNKNOWN):
                        server["server"]['host_status'] = host_status

        if api_version_request.is_supported(request, min_version="2.9"):
            server["server"]["locked"] = (True if instance["locked_by"]
                                          else False)

        if api_version_request.is_supported(request, min_version="2.73"):
            server["server"]["locked_reason"] = (instance.system_metadata.get(
                                                 "locked_reason"))

        if api_version_request.is_supported(request, min_version="2.19"):
            server["server"]["description"] = instance.get(
                                                "display_description")

        if api_version_request.is_supported(request, min_version="2.26"):
            server["server"]["tags"] = [t.tag for t in instance.tags]

        if api_version_request.is_supported(request, min_version="2.63"):
            trusted_certs = None
            if instance.trusted_certs:
                trusted_certs = instance.trusted_certs.ids
            server["server"]["trusted_image_certificates"] = trusted_certs

        if show_server_groups:
            server['server']['server_groups'] = self._get_server_groups(
                                                                   context,
                                                                   instance)
        return server

    def index(self, request, instances, cell_down_support=False):
        """Show a list of servers without many details."""
        coll_name = self._collection_name
        return self._list_view(self.basic, request, instances, coll_name,
                               False, cell_down_support=cell_down_support)

    def detail(self, request, instances, cell_down_support=False):
        """Detailed view of a list of instance."""
        coll_name = self._collection_name + '/detail'
        context = request.environ['nova.context']

        if api_version_request.is_supported(request, min_version='2.47'):
            # Determine if we should show extra_specs in the inlined flavor
            # once before we iterate the list of instances
            show_extra_specs = context.can(fes_policies.POLICY_ROOT % 'index',
                                           fatal=False)
        else:
            show_extra_specs = False
        show_extended_attr = context.can(
            esa_policies.BASE_POLICY_NAME, fatal=False)

        instance_uuids = [inst['uuid'] for inst in instances]
        bdms = self._get_instance_bdms_in_multiple_cells(context,
                                                         instance_uuids)

        # NOTE(gmann): pass show_sec_grp=False in _list_view() because
        # security groups for detail method will be added by separate
        # call to self._add_security_grps by passing the all servers
        # together. That help to avoid multiple neutron call for each server.
        servers_dict = self._list_view(self.show, request, instances,
                                       coll_name, show_extra_specs,
                                       show_extended_attr=show_extended_attr,
                                       # We process host_status in aggregate.
                                       show_host_status=False,
                                       show_sec_grp=False,
                                       bdms=bdms,
                                       cell_down_support=cell_down_support)

        if api_version_request.is_supported(request, min_version='2.16'):
            unknown_only = self._get_host_status_unknown_only(context)
            # If we're not allowed by policy to show host status at all, don't
            # bother requesting instance host status from the compute API.
            if unknown_only is not None:
                self._add_host_status(list(servers_dict["servers"]), instances,
                                      unknown_only=unknown_only)

        self._add_security_grps(request, list(servers_dict["servers"]),
                                instances)
        return servers_dict

    def _list_view(self, func, request, servers, coll_name, show_extra_specs,
                   show_extended_attr=None, show_host_status=None,
                   show_sec_grp=False, bdms=None, cell_down_support=False):
        """Provide a view for a list of servers.

        :param func: Function used to format the server data
        :param request: API request
        :param servers: List of servers in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :param show_extended_attr: If the server extended attributes should be
                        included in the response dict.
        :param show_host_status: If the host status should be included in
                        the response dict.
        :param show_sec_grp: If the security group should be included in
                        the response dict.
        :param bdms: Instances bdms info from multiple cells.
        :param cell_down_support: True if the API (and caller) support
                                  returning a minimal instance
                                  construct if the relevant cell is
                                  down.
        :returns: Server data in dictionary format
        """
        server_list = [func(request, server,
                            show_extra_specs=show_extra_specs,
                            show_extended_attr=show_extended_attr,
                            show_host_status=show_host_status,
                            show_sec_grp=show_sec_grp, bdms=bdms,
                            cell_down_support=cell_down_support)["server"]
                       for server in servers
                       # Filter out the fake marker instance created by the
                       # fill_virtual_interface_list online data migration.
                       if server.uuid != virtual_interface.FAKE_UUID]
        servers_links = self._get_collection_links(request,
                                                   servers,
                                                   coll_name)
        servers_dict = dict(servers=server_list)

        if servers_links:
            servers_dict["servers_links"] = servers_links

        return servers_dict

    @staticmethod
    def _get_metadata(instance):
        return instance.metadata or {}

    @staticmethod
    def _get_vm_status(instance):
        # If the instance is deleted the vm and task states don't really matter
        if instance.get("deleted"):
            return "DELETED"
        return common.status_from_state(instance.get("vm_state"),
                                        instance.get("task_state"))

    @staticmethod
    def _get_host_id(instance):
        host = instance.get("host")
        project = str(instance.get("project_id"))
        return utils.generate_hostid(host, project)

    def _get_addresses(self, request, instance, extend_address=False):
        # Hide server addresses while the server is building.
        if instance.vm_state == vm_states.BUILDING:
            return {}
        context = request.environ["nova.context"]
        networks = common.get_networks_for_instance(context, instance)
        return self._address_builder.index(networks,
                                           extend_address)["addresses"]

    def _get_image(self, request, instance):
        image_ref = instance["image_ref"]
        if image_ref:
            image_id = str(common.get_id_from_href(image_ref))
            bookmark = self._image_builder._get_bookmark_link(request,
                                                              image_id,
                                                              "images")
            return {
                "id": image_id,
                "links": [{
                    "rel": "bookmark",
                    "href": bookmark,
                }],
            }
        else:
            return ""

    def _get_flavor_dict(self, request, instance_type, show_extra_specs):
        flavordict = {
            "vcpus": instance_type.vcpus,
            "ram": instance_type.memory_mb,
            "disk": instance_type.root_gb,
            "ephemeral": instance_type.ephemeral_gb,
            "swap": instance_type.swap,
            "original_name": instance_type.name
        }
        if show_extra_specs:
            flavordict['extra_specs'] = instance_type.extra_specs
        return flavordict

    def _get_flavor(self, request, instance, show_extra_specs):
        instance_type = instance.get_flavor()
        if not instance_type:
            LOG.warning("Instance has had its instance_type removed "
                        "from the DB", instance=instance)
            return {}

        if api_version_request.is_supported(request, min_version="2.47"):
            return self._get_flavor_dict(request, instance_type,
                                         show_extra_specs)

        flavor_id = instance_type["flavorid"]
        flavor_bookmark = self._flavor_builder._get_bookmark_link(request,
                                                                  flavor_id,
                                                                  "flavors")
        return {
            "id": str(flavor_id),
            "links": [{
                "rel": "bookmark",
                "href": flavor_bookmark,
            }],
        }

    def _load_fault(self, request, instance):
        try:
            mapping = objects.InstanceMapping.get_by_instance_uuid(
                request.environ['nova.context'], instance.uuid)
            if mapping.cell_mapping is not None:
                with nova_context.target_cell(instance._context,
                                              mapping.cell_mapping):
                    return instance.fault
        except exception.InstanceMappingNotFound:
            pass

        # NOTE(danms): No instance mapping at all, or a mapping with no cell,
        # which means a legacy environment or instance.
        return instance.fault

    def _get_fault(self, request, instance):
        if 'fault' in instance:
            fault = instance.fault
        else:
            fault = self._load_fault(request, instance)

        if not fault:
            return None

        fault_dict = {
            "code": fault["code"],
            "created": utils.isotime(fault["created_at"]),
            "message": fault["message"],
        }

        if fault.get('details', None):
            is_admin = False
            context = request.environ["nova.context"]
            if context:
                is_admin = getattr(context, 'is_admin', False)

            if is_admin or fault['code'] != 500:
                fault_dict['details'] = fault["details"]

        return fault_dict

    def _add_host_status(self, servers, instances, unknown_only=False):
        """Adds the ``host_status`` field to the list of servers

        This method takes care to filter instances from down cells since they
        do not have a host set and as such we cannot determine the host status.

        :param servers: list of detailed server dicts for the API response
            body; this list is modified by reference by updating the server
            dicts within the list
        :param instances: list of Instance objects
        :param unknown_only: whether to show only UNKNOWN host status
        """
        # Filter out instances from down cells which do not have a host field.
        instances = [instance for instance in instances if 'host' in instance]
        # Get the dict, keyed by instance.uuid, of host status values.
        host_statuses = self.compute_api.get_instances_host_statuses(instances)
        for server in servers:
            # Filter out anything that is not in the resulting dict because
            # we had to filter the list of instances above for down cells.
            if server['id'] in host_statuses:
                host_status = host_statuses[server['id']]
                if unknown_only and host_status != fields.HostStatus.UNKNOWN:
                    # Filter servers that are not allowed by policy to see
                    # host_status values other than UNKNOWN.
                    continue
                server['host_status'] = host_status

    def _add_security_grps(self, req, servers, instances,
                           create_request=False):
        if not len(servers):
            return

        # If request is a POST create server we get the security groups
        # intended for an instance from the request. This is necessary because
        # the requested security groups for the instance have not yet been sent
        # to neutron.
        # Starting from microversion 2.75, security groups is returned in
        # PUT and POST Rebuild response also.
        if not create_request:
            context = req.environ['nova.context']
            sg_instance_bindings = (
                security_group_api.get_instances_security_groups_bindings(
                    context, servers))
            for server in servers:
                groups = sg_instance_bindings.get(server['id'])
                if groups:
                    server['security_groups'] = groups

        # This section is for POST create server request. There can be
        # only one security group for POST create server request.
        else:
            # try converting to json
            req_obj = jsonutils.loads(req.body)
            # Add security group to server, if no security group was in
            # request add default since that is the group it is part of
            servers[0]['security_groups'] = req_obj['server'].get(
                'security_groups', [{'name': 'default'}])

    @staticmethod
    def _get_instance_bdms_in_multiple_cells(ctxt, instance_uuids):
        inst_maps = objects.InstanceMappingList.get_by_instance_uuids(
                        ctxt, instance_uuids)

        cell_mappings = {}
        for inst_map in inst_maps:
            if (inst_map.cell_mapping is not None and
                    inst_map.cell_mapping.uuid not in cell_mappings):
                cell_mappings.update(
                    {inst_map.cell_mapping.uuid: inst_map.cell_mapping})

        bdms = {}
        results = nova_context.scatter_gather_cells(
                        ctxt, cell_mappings.values(),
                        nova_context.CELL_TIMEOUT,
                        objects.BlockDeviceMappingList.bdms_by_instance_uuid,
                        instance_uuids)
        for cell_uuid, result in results.items():
            if isinstance(result, Exception):
                LOG.warning('Failed to get block device mappings for cell %s',
                            cell_uuid)
            elif result is nova_context.did_not_respond_sentinel:
                LOG.warning('Timeout getting block device mappings for cell '
                            '%s', cell_uuid)
            else:
                bdms.update(result)
        return bdms

    def _add_volumes_attachments(self, server, bdms,
                                 add_delete_on_termination):
        # server['id'] is guaranteed to be in the cache due to
        # the core API adding it in the 'detail' or 'show' method.
        # If that instance has since been deleted, it won't be in the
        # 'bdms' dictionary though, so use 'get' to avoid KeyErrors.
        instance_bdms = bdms.get(server['id'], [])
        volumes_attached = []
        for bdm in instance_bdms:
            if bdm.get('volume_id'):
                volume_attached = {'id': bdm['volume_id']}
                if add_delete_on_termination:
                    volume_attached['delete_on_termination'] = (
                        bdm['delete_on_termination'])
                volumes_attached.append(volume_attached)
        # NOTE(mriedem): The os-extended-volumes prefix should not be used for
        # new attributes after v2.1. They are only in v2.1 for backward compat
        # with v2.0.
        key = "os-extended-volumes:volumes_attached"
        server[key] = volumes_attached

    @staticmethod
    def _get_server_groups(context, instance):
        try:
            sg = objects.InstanceGroup.get_by_instance_uuid(context,
                                                            instance.uuid)
            return [sg.uuid]
        except exception.InstanceGroupNotFound:
            return []
