# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
The VMware API utility module.
"""

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

vmware_opts = cfg.IntOpt('maximum_objects', default=100,
                         help='The maximum number of ObjectContent data '
                              'objects that should be returned in a single '
                              'result. A positive value will cause the '
                              'operation to suspend the retrieval when the '
                              'count of objects reaches the specified '
                              'maximum. The server may still limit the count '
                              'to something less than the configured value. '
                              'Any remaining objects may be retrieved with '
                              'additional requests.')
CONF = cfg.CONF
CONF.register_opt(vmware_opts, 'vmware')
LOG = logging.getLogger(__name__)


def build_selection_spec(client_factory, name):
    """Builds the selection spec."""
    sel_spec = client_factory.create('ns0:SelectionSpec')
    sel_spec.name = name
    return sel_spec


def build_traversal_spec(client_factory, name, spec_type, path, skip,
                         select_set):
    """Builds the traversal spec object."""
    traversal_spec = client_factory.create('ns0:TraversalSpec')
    traversal_spec.name = name
    traversal_spec.type = spec_type
    traversal_spec.path = path
    traversal_spec.skip = skip
    traversal_spec.selectSet = select_set
    return traversal_spec


def build_recursive_traversal_spec(client_factory):
    """Builds the Recursive Traversal Spec to traverse the object managed
    object hierarchy.
    """
    visit_folders_select_spec = build_selection_spec(client_factory,
                                    "visitFolders")
    # For getting to hostFolder from datacenter
    dc_to_hf = build_traversal_spec(client_factory, "dc_to_hf", "Datacenter",
                                    "hostFolder", False,
                                    [visit_folders_select_spec])
    # For getting to vmFolder from datacenter
    dc_to_vmf = build_traversal_spec(client_factory, "dc_to_vmf", "Datacenter",
                                     "vmFolder", False,
                                     [visit_folders_select_spec])
    # For getting Host System to virtual machine
    h_to_vm = build_traversal_spec(client_factory, "h_to_vm", "HostSystem",
                                   "vm", False,
                                   [visit_folders_select_spec])

    # For getting to Host System from Compute Resource
    cr_to_h = build_traversal_spec(client_factory, "cr_to_h",
                                   "ComputeResource", "host", False, [])

    # For getting to datastore from Compute Resource
    cr_to_ds = build_traversal_spec(client_factory, "cr_to_ds",
                                    "ComputeResource", "datastore", False, [])

    rp_to_rp_select_spec = build_selection_spec(client_factory, "rp_to_rp")
    rp_to_vm_select_spec = build_selection_spec(client_factory, "rp_to_vm")
    # For getting to resource pool from Compute Resource
    cr_to_rp = build_traversal_spec(client_factory, "cr_to_rp",
                                "ComputeResource", "resourcePool", False,
                                [rp_to_rp_select_spec, rp_to_vm_select_spec])

    # For getting to child res pool from the parent res pool
    rp_to_rp = build_traversal_spec(client_factory, "rp_to_rp", "ResourcePool",
                                "resourcePool", False,
                                [rp_to_rp_select_spec, rp_to_vm_select_spec])

    # For getting to Virtual Machine from the Resource Pool
    rp_to_vm = build_traversal_spec(client_factory, "rp_to_vm", "ResourcePool",
                                "vm", False,
                                [rp_to_rp_select_spec, rp_to_vm_select_spec])

    # Get the assorted traversal spec which takes care of the objects to
    # be searched for from the root folder
    traversal_spec = build_traversal_spec(client_factory, "visitFolders",
                                  "Folder", "childEntity", False,
                                  [visit_folders_select_spec, dc_to_hf,
                                   dc_to_vmf, cr_to_ds, cr_to_h, cr_to_rp,
                                   rp_to_rp, h_to_vm, rp_to_vm])
    return traversal_spec


def build_property_spec(client_factory, type="VirtualMachine",
                        properties_to_collect=None,
                        all_properties=False):
    """Builds the Property Spec."""
    if not properties_to_collect:
        properties_to_collect = ["name"]

    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = all_properties
    property_spec.pathSet = properties_to_collect
    property_spec.type = type
    return property_spec


def build_object_spec(client_factory, root_folder, traversal_specs):
    """Builds the object Spec."""
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = root_folder
    object_spec.skip = False
    object_spec.selectSet = traversal_specs
    return object_spec


def build_property_filter_spec(client_factory, property_specs, object_specs):
    """Builds the Property Filter Spec."""
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_filter_spec.propSet = property_specs
    property_filter_spec.objectSet = object_specs
    return property_filter_spec


def get_object_properties(vim, collector, mobj, type, properties):
    """Gets the properties of the Managed object specified."""
    client_factory = vim.client.factory
    if mobj is None:
        return None
    usecoll = collector
    if usecoll is None:
        usecoll = vim.get_service_content().propertyCollector
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = (properties is None or len(properties) == 0)
    property_spec.pathSet = properties
    property_spec.type = type
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = mobj
    object_spec.skip = False
    property_filter_spec.propSet = [property_spec]
    property_filter_spec.objectSet = [object_spec]
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = CONF.vmware.maximum_objects
    return vim.RetrievePropertiesEx(usecoll, specSet=[property_filter_spec],
                                    options=options)


def get_dynamic_property(vim, mobj, type, property_name):
    """Gets a particular property of the Managed Object."""
    property_dict = get_dynamic_properties(vim, mobj, type, [property_name])
    return property_dict.get(property_name)


def get_dynamic_properties(vim, mobj, type, property_names):
    """Gets the specified properties of the Managed Object."""
    obj_content = get_object_properties(vim, None, mobj, type, property_names)
    if hasattr(obj_content, 'token'):
        cancel_retrieve(vim, obj_content.token)
    property_dict = {}
    if obj_content.objects:
        if hasattr(obj_content.objects[0], 'propSet'):
            dynamic_properties = obj_content.objects[0].propSet
            if dynamic_properties:
                for prop in dynamic_properties:
                    property_dict[prop.name] = prop.val
        # The object may have information useful for logging
        if hasattr(obj_content.objects[0], 'missingSet'):
            for m in obj_content.objects[0].missingSet:
                LOG.warning(_("Unable to retrieve value for %(path)s "
                              "Reason: %(reason)s"),
                            {'path': m.path,
                             'reason': m.fault.localizedMessage})
    return property_dict


def get_objects(vim, type, properties_to_collect=None, all=False):
    """Gets the list of objects of the type specified."""
    if not properties_to_collect:
        properties_to_collect = ["name"]

    client_factory = vim.client.factory
    object_spec = build_object_spec(client_factory,
                        vim.get_service_content().rootFolder,
                        [build_recursive_traversal_spec(client_factory)])
    property_spec = build_property_spec(client_factory, type=type,
                                properties_to_collect=properties_to_collect,
                                all_properties=all)
    property_filter_spec = build_property_filter_spec(client_factory,
                                [property_spec],
                                [object_spec])
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = CONF.vmware.maximum_objects
    return vim.RetrievePropertiesEx(
            vim.get_service_content().propertyCollector,
            specSet=[property_filter_spec], options=options)


def cancel_retrieve(vim, token):
    """Cancels the retrieve operation."""
    return vim.CancelRetrievePropertiesEx(
            vim.get_service_content().propertyCollector,
            token=token)


def continue_to_get_objects(vim, token):
    """Continues to get the list of objects of the type specified."""
    return vim.ContinueRetrievePropertiesEx(
            vim.get_service_content().propertyCollector,
            token=token)


def get_prop_spec(client_factory, spec_type, properties):
    """Builds the Property Spec Object."""
    prop_spec = client_factory.create('ns0:PropertySpec')
    prop_spec.type = spec_type
    prop_spec.pathSet = properties
    return prop_spec


def get_obj_spec(client_factory, obj, select_set=None):
    """Builds the Object Spec object."""
    obj_spec = client_factory.create('ns0:ObjectSpec')
    obj_spec.obj = obj
    obj_spec.skip = False
    if select_set is not None:
        obj_spec.selectSet = select_set
    return obj_spec


def get_prop_filter_spec(client_factory, obj_spec, prop_spec):
    """Builds the Property Filter Spec Object."""
    prop_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    prop_filter_spec.propSet = prop_spec
    prop_filter_spec.objectSet = obj_spec
    return prop_filter_spec


def get_properties_for_a_collection_of_objects(vim, type,
                                               obj_list, properties):
    """Gets the list of properties for the collection of
    objects of the type specified.
    """
    client_factory = vim.client.factory
    if len(obj_list) == 0:
        return []
    prop_spec = get_prop_spec(client_factory, type, properties)
    lst_obj_specs = []
    for obj in obj_list:
        lst_obj_specs.append(get_obj_spec(client_factory, obj))
    prop_filter_spec = get_prop_filter_spec(client_factory,
                                            lst_obj_specs, [prop_spec])
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = CONF.vmware.maximum_objects
    return vim.RetrievePropertiesEx(
            vim.get_service_content().propertyCollector,
            specSet=[prop_filter_spec], options=options)


def get_about_info(vim):
    """Get the About Info from the service content."""
    return vim.get_service_content().about
