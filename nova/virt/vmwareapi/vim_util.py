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

from nova.virt.vmwareapi.VimService_services_types import ns0

MAX_CLONE_RETRIES = 1


def build_recursive_traversal_spec():
    """
    Builds the Traversal Spec
    """
    #Traversal through "hostFolder" branch
    visit_folders_select_spec = ns0.SelectionSpec_Def("visitFolders").pyclass()
    visit_folders_select_spec.set_element_name("visitFolders")
    select_set = [visit_folders_select_spec]
    dc_to_hf = ns0.TraversalSpec_Def("dc_to_hf").pyclass()
    dc_to_hf.set_element_name("dc_to_hf")
    dc_to_hf.set_element_type("Datacenter")
    dc_to_hf.set_element_path("hostFolder")
    dc_to_hf.set_element_skip(False)
    dc_to_hf.set_element_selectSet(select_set)

    #Traversal through "vmFolder" branch
    visit_folders_select_spec = ns0.SelectionSpec_Def("visitFolders").pyclass()
    visit_folders_select_spec.set_element_name("visitFolders")
    select_set = [visit_folders_select_spec]
    dc_to_vmf = ns0.TraversalSpec_Def("dc_to_vmf").pyclass()
    dc_to_vmf.set_element_name("dc_to_vmf")
    dc_to_vmf.set_element_type("Datacenter")
    dc_to_vmf.set_element_path("vmFolder")
    dc_to_vmf.set_element_skip(False)
    dc_to_vmf.set_element_selectSet(select_set)

    #Traversal to the DataStore from the DataCenter
    visit_folders_select_spec = \
        ns0.SelectionSpec_Def("traverseChild").pyclass()
    visit_folders_select_spec.set_element_name("traverseChild")
    select_set = [visit_folders_select_spec]
    dc_to_ds = ns0.TraversalSpec_Def("dc_to_ds").pyclass()
    dc_to_ds.set_element_name("dc_to_ds")
    dc_to_ds.set_element_type("Datacenter")
    dc_to_ds.set_element_path("datastore")
    dc_to_ds.set_element_skip(False)
    dc_to_ds.set_element_selectSet(select_set)

    #Traversal through "vm" branch
    visit_folders_select_spec = \
        ns0.SelectionSpec_Def("visitFolders").pyclass()
    visit_folders_select_spec.set_element_name("visitFolders")
    select_set = [visit_folders_select_spec]
    h_to_vm = ns0.TraversalSpec_Def("h_to_vm").pyclass()
    h_to_vm.set_element_name("h_to_vm")
    h_to_vm.set_element_type("HostSystem")
    h_to_vm.set_element_path("vm")
    h_to_vm.set_element_skip(False)
    h_to_vm.set_element_selectSet(select_set)

    #Traversal through "host" branch
    cr_to_h = ns0.TraversalSpec_Def("cr_to_h").pyclass()
    cr_to_h.set_element_name("cr_to_h")
    cr_to_h.set_element_type("ComputeResource")
    cr_to_h.set_element_path("host")
    cr_to_h.set_element_skip(False)
    cr_to_h.set_element_selectSet([])

    cr_to_ds = ns0.TraversalSpec_Def("cr_to_ds").pyclass()
    cr_to_ds.set_element_name("cr_to_ds")
    cr_to_ds.set_element_type("ComputeResource")
    cr_to_ds.set_element_path("datastore")
    cr_to_ds.set_element_skip(False)

    #Traversal through "resourcePool" branch
    rp_to_rp_select_spec = ns0.SelectionSpec_Def("rp_to_rp").pyclass()
    rp_to_rp_select_spec.set_element_name("rp_to_rp")
    rp_to_vm_select_spec = ns0.SelectionSpec_Def("rp_to_vm").pyclass()
    rp_to_vm_select_spec.set_element_name("rp_to_vm")
    select_set = [rp_to_rp_select_spec, rp_to_vm_select_spec]
    cr_to_rp = ns0.TraversalSpec_Def("cr_to_rp").pyclass()
    cr_to_rp.set_element_name("cr_to_rp")
    cr_to_rp.set_element_type("ComputeResource")
    cr_to_rp.set_element_path("resourcePool")
    cr_to_rp.set_element_skip(False)
    cr_to_rp.set_element_selectSet(select_set)

    #Traversal through all ResourcePools
    rp_to_rp_select_spec = ns0.SelectionSpec_Def("rp_to_rp").pyclass()
    rp_to_rp_select_spec.set_element_name("rp_to_rp")
    rp_to_vm_select_spec = ns0.SelectionSpec_Def("rp_to_vm").pyclass()
    rp_to_vm_select_spec.set_element_name("rp_to_vm")
    select_set = [rp_to_rp_select_spec, rp_to_vm_select_spec]
    rp_to_rp = ns0.TraversalSpec_Def("rp_to_rp").pyclass()
    rp_to_rp.set_element_name("rp_to_rp")
    rp_to_rp.set_element_type("ResourcePool")
    rp_to_rp.set_element_path("resourcePool")
    rp_to_rp.set_element_skip(False)
    rp_to_rp.set_element_selectSet(select_set)

    #Traversal through ResourcePools vm folders
    rp_to_rp_select_spec = ns0.SelectionSpec_Def("rp_to_rp").pyclass()
    rp_to_rp_select_spec.set_element_name("rp_to_rp")
    rp_to_vm_select_spec = ns0.SelectionSpec_Def("rp_to_vm").pyclass()
    rp_to_vm_select_spec.set_element_name("rp_to_vm")
    select_set = [rp_to_rp_select_spec, rp_to_vm_select_spec]
    rp_to_vm = ns0.TraversalSpec_Def("rp_to_vm").pyclass()
    rp_to_vm.set_element_name("rp_to_vm")
    rp_to_vm.set_element_type("ResourcePool")
    rp_to_vm.set_element_path("vm")
    rp_to_vm.set_element_skip(False)
    rp_to_vm.set_element_selectSet(select_set)

    #Include all Traversals and Recurse into them
    visit_folders_select_spec = \
        ns0.SelectionSpec_Def("visitFolders").pyclass()
    visit_folders_select_spec.set_element_name("visitFolders")
    select_set = [visit_folders_select_spec, dc_to_hf, dc_to_vmf,
                  cr_to_ds, cr_to_h, cr_to_rp, rp_to_rp, h_to_vm, rp_to_vm]
    traversal_spec = ns0.TraversalSpec_Def("visitFolders").pyclass()
    traversal_spec.set_element_name("visitFolders")
    traversal_spec.set_element_type("Folder")
    traversal_spec.set_element_path("childEntity")
    traversal_spec.set_element_skip(False)
    traversal_spec.set_element_selectSet(select_set)
    return traversal_spec


def build_property_spec(type="VirtualMachine", properties_to_collect=["name"],
                        all_properties=False):
    """
    Builds the Property Spec
    """
    property_spec = ns0.PropertySpec_Def("propertySpec").pyclass()
    property_spec.set_element_type(type)
    property_spec.set_element_all(all_properties)
    property_spec.set_element_pathSet(properties_to_collect)
    return property_spec


def build_object_spec(root_folder, traversal_specs):
    """
    Builds the object Spec
    """
    object_spec = ns0.ObjectSpec_Def("ObjectSpec").pyclass()
    object_spec.set_element_obj(root_folder)
    object_spec.set_element_skip(False)
    object_spec.set_element_selectSet(traversal_specs)
    return object_spec


def build_property_filter_spec(property_specs, object_specs):
    """
    Builds the Property Filter Spec
    """
    property_filter_spec = \
        ns0.PropertyFilterSpec_Def("PropertyFilterSpec").pyclass()
    property_filter_spec.set_element_propSet(property_specs)
    property_filter_spec.set_element_objectSet(object_specs)
    return property_filter_spec


def get_object_properties(vim, collector, mobj, type, properties):
    """
    Gets the properties of the Managed object specified
    """
    if mobj is None:
        return None
    usecoll = collector
    if usecoll is None:
        usecoll = vim.get_service_content().PropertyCollector
    property_filter_spec = \
        ns0.PropertyFilterSpec_Def("PropertyFilterSpec").pyclass()
    property_filter_spec._propSet = \
        [ns0.PropertySpec_Def("PropertySpec").pyclass()]
    property_filter_spec.PropSet[0]._all = \
        (properties == None or len(properties) == 0)
    property_filter_spec.PropSet[0]._type = type
    property_filter_spec.PropSet[0]._pathSet = properties

    property_filter_spec._objectSet = \
        [ns0.ObjectSpec_Def("ObjectSpec").pyclass()]
    property_filter_spec.ObjectSet[0]._obj = mobj
    property_filter_spec.ObjectSet[0]._skip = False
    return vim.RetrieveProperties(usecoll, specSet=[property_filter_spec])


def get_dynamic_property(vim, mobj, type, property_name):
    """
    Gets a particular property of the Managed Object
    """
    obj_content = \
        get_object_properties(vim, None, mobj, type, [property_name])
    property_value = None
    if obj_content:
        dynamic_property = obj_content[0].PropSet
        if dynamic_property:
            property_value = dynamic_property[0].Val
    return property_value


def get_objects(vim, type, properties_to_collect=["name"], all=False):
    """
    Gets the list of objects of the type specified
    """
    object_spec = build_object_spec(vim.get_service_content().RootFolder,
                                [build_recursive_traversal_spec()])
    property_spec = build_property_spec(type=type,
                                properties_to_collect=properties_to_collect,
                                all_properties=all)
    property_filter_spec = build_property_filter_spec([property_spec],
                                [object_spec])
    return vim.RetrieveProperties(vim.get_service_content().PropertyCollector,
                                specSet=[property_filter_spec])


def get_traversal_spec(type, path, name="traversalSpec"):
    """
    Builds the traversal spec object
    """
    t_spec = ns0.TraversalSpec_Def(name).pyclass()
    t_spec._name = name
    t_spec._type = type
    t_spec._path = path
    t_spec._skip = False
    return t_spec


def get_prop_spec(type, properties):
    """
    Builds the Property Spec Object
    """
    prop_spec = ns0.PropertySpec_Def("PropertySpec").pyclass()
    prop_spec._type = type
    prop_spec._pathSet = properties
    return prop_spec


def get_obj_spec(obj, select_set=None):
    """
    Builds the Object Spec object
    """
    obj_spec = ns0.ObjectSpec_Def("ObjectSpec").pyclass()
    obj_spec._obj = obj
    obj_spec._skip = False
    if select_set is not None:
        obj_spec._selectSet = select_set
    return obj_spec


def get_prop_filter_spec(obj_spec, prop_spec):
    """
    Builds the Property Filter Spec Object
    """
    prop_filter_spec = \
        ns0.PropertyFilterSpec_Def("PropertyFilterSpec").pyclass()
    prop_filter_spec._propSet = prop_spec
    prop_filter_spec._objectSet = obj_spec
    return prop_filter_spec


def get_properites_for_a_collection_of_objects(vim, type,
                                               obj_list, properties):
    """
    Gets the list of properties for the collection of
    objects of the type specified
    """
    if len(obj_list) == 0:
        return []
    prop_spec = get_prop_spec(type, properties)
    lst_obj_specs = []
    for obj in obj_list:
        lst_obj_specs.append(get_obj_spec(obj))
    prop_filter_spec = get_prop_filter_spec(lst_obj_specs, [prop_spec])
    return vim.RetrieveProperties(vim.get_service_content().PropertyCollector,
                                   specSet=[prop_filter_spec])
