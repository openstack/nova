# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
The VMware API utility module
"""


def build_recursive_traversal_spec(client_factory):
    """Builds the Traversal Spec"""
    #Traversal through "hostFolder" branch
    visit_folders_select_spec = client_factory.create('ns0:SelectionSpec')
    visit_folders_select_spec.name = "visitFolders"
    dc_to_hf = client_factory.create('ns0:TraversalSpec')
    dc_to_hf.name = "dc_to_hf"
    dc_to_hf.type = "Datacenter"
    dc_to_hf.path = "hostFolder"
    dc_to_hf.skip = False
    dc_to_hf.selectSet = [visit_folders_select_spec]

    #Traversal through "vmFolder" branch
    visit_folders_select_spec = client_factory.create('ns0:SelectionSpec')
    visit_folders_select_spec.name = "visitFolders"
    dc_to_vmf = client_factory.create('ns0:TraversalSpec')
    dc_to_vmf.name = "dc_to_vmf"
    dc_to_vmf.type = "Datacenter"
    dc_to_vmf.path = "vmFolder"
    dc_to_vmf.skip = False
    dc_to_vmf.selectSet = [visit_folders_select_spec]

    #Traversal to the DataStore from the DataCenter
    visit_folders_select_spec = \
        client_factory.create('ns0:SelectionSpec')
    visit_folders_select_spec.name = "traverseChild"
    dc_to_ds = client_factory.create('ns0:TraversalSpec')
    dc_to_ds.name = "dc_to_ds"
    dc_to_ds.type = "Datacenter"
    dc_to_ds.path = "datastore"
    dc_to_ds.skip = False
    dc_to_ds.selectSet = [visit_folders_select_spec]

    #Traversal through "vm" branch
    visit_folders_select_spec = \
        client_factory.create('ns0:SelectionSpec')
    visit_folders_select_spec.name = "visitFolders"
    h_to_vm = client_factory.create('ns0:TraversalSpec')
    h_to_vm.name = "h_to_vm"
    h_to_vm.type = "HostSystem"
    h_to_vm.path = "vm"
    h_to_vm.skip = False
    h_to_vm.selectSet = [visit_folders_select_spec]

    #Traversal through "host" branch
    cr_to_h = client_factory.create('ns0:TraversalSpec')
    cr_to_h.name = "cr_to_h"
    cr_to_h.type = "ComputeResource"
    cr_to_h.path = "host"
    cr_to_h.skip = False
    cr_to_h.selectSet = []

    cr_to_ds = client_factory.create('ns0:TraversalSpec')
    cr_to_ds.name = "cr_to_ds"
    cr_to_ds.type = "ComputeResource"
    cr_to_ds.path = "datastore"
    cr_to_ds.skip = False

    #Traversal through "resourcePool" branch
    rp_to_rp_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_rp_select_spec.name = "rp_to_rp"
    rp_to_vm_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_vm_select_spec.name = "rp_to_vm"
    cr_to_rp = client_factory.create('ns0:TraversalSpec')
    cr_to_rp.name = "cr_to_rp"
    cr_to_rp.type = "ComputeResource"
    cr_to_rp.path = "resourcePool"
    cr_to_rp.skip = False
    cr_to_rp.selectSet = [rp_to_rp_select_spec, rp_to_vm_select_spec]

    #Traversal through all ResourcePools
    rp_to_rp_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_rp_select_spec.name = "rp_to_rp"
    rp_to_vm_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_vm_select_spec.name = "rp_to_vm"
    rp_to_rp = client_factory.create('ns0:TraversalSpec')
    rp_to_rp.name = "rp_to_rp"
    rp_to_rp.type = "ResourcePool"
    rp_to_rp.path = "resourcePool"
    rp_to_rp.skip = False
    rp_to_rp.selectSet = [rp_to_rp_select_spec, rp_to_vm_select_spec]

    #Traversal through ResourcePools vm folders
    rp_to_rp_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_rp_select_spec.name = "rp_to_rp"
    rp_to_vm_select_spec = client_factory.create('ns0:SelectionSpec')
    rp_to_vm_select_spec.name = "rp_to_vm"
    rp_to_vm = client_factory.create('ns0:TraversalSpec')
    rp_to_vm.name = "rp_to_vm"
    rp_to_vm.type = "ResourcePool"
    rp_to_vm.path = "vm"
    rp_to_vm.skip = False
    rp_to_vm.selectSet = [rp_to_rp_select_spec, rp_to_vm_select_spec]

    #Include all Traversals and Recurse into them
    visit_folders_select_spec = \
        client_factory.create('ns0:SelectionSpec')
    visit_folders_select_spec.name = "visitFolders"
    traversal_spec = client_factory.create('ns0:TraversalSpec')
    traversal_spec.name = "visitFolders"
    traversal_spec.type = "Folder"
    traversal_spec.path = "childEntity"
    traversal_spec.skip = False
    traversal_spec.selectSet = [visit_folders_select_spec, dc_to_hf, dc_to_vmf,
                  cr_to_ds, cr_to_h, cr_to_rp, rp_to_rp, h_to_vm, rp_to_vm]
    return traversal_spec


def build_property_spec(client_factory, type="VirtualMachine",
                        properties_to_collect=["name"],
                        all_properties=False):
    """Builds the Property Spec"""
    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = all_properties
    property_spec.pathSet = properties_to_collect
    property_spec.type = type
    return property_spec


def build_object_spec(client_factory, root_folder, traversal_specs):
    """Builds the object Spec"""
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = root_folder
    object_spec.skip = False
    object_spec.selectSet = traversal_specs
    return object_spec


def build_property_filter_spec(client_factory, property_specs, object_specs):
    """Builds the Property Filter Spec"""
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_filter_spec.propSet = property_specs
    property_filter_spec.objectSet = object_specs
    return property_filter_spec


def get_object_properties(vim, collector, mobj, type, properties):
    """Gets the properties of the Managed object specified"""
    client_factory = vim.client.factory
    if mobj is None:
        return None
    usecoll = collector
    if usecoll is None:
        usecoll = vim.get_service_content().propertyCollector
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = (properties == None or len(properties) == 0)
    property_spec.pathSet = properties
    property_spec.type = type
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = mobj
    object_spec.skip = False
    property_filter_spec.propSet = [property_spec]
    property_filter_spec.objectSet = [object_spec]
    return vim.RetrieveProperties(usecoll, specSet=[property_filter_spec])


def get_dynamic_property(vim, mobj, type, property_name):
    """Gets a particular property of the Managed Object"""
    obj_content = \
        get_object_properties(vim, None, mobj, type, [property_name])
    property_value = None
    if obj_content:
        dynamic_property = obj_content[0].propSet
        if dynamic_property:
            property_value = dynamic_property[0].val
    return property_value


def get_objects(vim, type, properties_to_collect=["name"], all=False):
    """Gets the list of objects of the type specified"""
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
    return vim.RetrieveProperties(vim.get_service_content().propertyCollector,
                                specSet=[property_filter_spec])


def get_prop_spec(client_factory, type, properties):
    """Builds the Property Spec Object"""
    prop_spec = client_factory.create('ns0:PropertySpec')
    prop_spec.type = type
    prop_spec.pathSet = properties
    return prop_spec


def get_obj_spec(client_factory, obj, select_set=None):
    """Builds the Object Spec object"""
    obj_spec = client_factory.create('ns0:ObjectSpec')
    obj_spec.obj = obj
    obj_spec.skip = False
    if select_set is not None:
        obj_spec.selectSet = select_set
    return obj_spec


def get_prop_filter_spec(client_factory, obj_spec, prop_spec):
    """Builds the Property Filter Spec Object"""
    prop_filter_spec = \
        client_factory.create('ns0:PropertyFilterSpec')
    prop_filter_spec.propSet = prop_spec
    prop_filter_spec.objectSet = obj_spec
    return prop_filter_spec


def get_properites_for_a_collection_of_objects(vim, type,
                                               obj_list, properties):
    """Gets the list of properties for the collection of
    objects of the type specified
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
    return vim.RetrieveProperties(vim.get_service_content().propertyCollector,
                                   specSet=[prop_filter_spec])
