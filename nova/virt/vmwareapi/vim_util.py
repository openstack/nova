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

from oslo_vmware import vim_util as vutil


import nova.conf

CONF = nova.conf.CONF


def object_to_dict(obj, list_depth=1):
    """Convert Suds object into serializable format.

    The calling function can limit the amount of list entries that
    are converted.
    """
    d = {}
    for k, v in dict(obj).items():
        if hasattr(v, '__keylist__'):
            d[k] = object_to_dict(v, list_depth=list_depth)
        elif isinstance(v, list):
            d[k] = []
            used = 0
            for item in v:
                used = used + 1
                if used > list_depth:
                    break
                if hasattr(item, '__keylist__'):
                    d[k].append(object_to_dict(item, list_depth=list_depth))
                else:
                    d[k].append(item)
        else:
            d[k] = v
    return d


def get_object_properties(vim, collector, mobj, type, properties):
    """Gets the properties of the Managed object specified."""
    client_factory = vim.client.factory
    if mobj is None:
        return None
    usecoll = collector
    if usecoll is None:
        usecoll = vim.service_content.propertyCollector
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


def get_objects(vim, type, properties_to_collect=None, all=False):
    """Gets the list of objects of the type specified."""
    return vutil.get_objects(vim, type, CONF.vmware.maximum_objects,
                             properties_to_collect, all)


def get_inner_objects(vim, base_obj, path, inner_type,
                      properties_to_collect=None, all=False):
    """Gets the list of inner objects of the type specified."""
    client_factory = vim.client.factory
    base_type = base_obj._type
    traversal_spec = vutil.build_traversal_spec(client_factory, 'inner',
                                                base_type, path, False, [])
    object_spec = vutil.build_object_spec(client_factory,
                                          base_obj,
                                          [traversal_spec])
    property_spec = vutil.build_property_spec(client_factory, type_=inner_type,
                                properties_to_collect=properties_to_collect,
                                all_properties=all)
    property_filter_spec = vutil.build_property_filter_spec(client_factory,
                                [property_spec], [object_spec])
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = CONF.vmware.maximum_objects
    return vim.RetrievePropertiesEx(
            vim.service_content.propertyCollector,
            specSet=[property_filter_spec], options=options)


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
            vim.service_content.propertyCollector,
            specSet=[prop_filter_spec], options=options)


def get_about_info(vim):
    """Get the About Info from the service content."""
    return vim.service_content.about


def get_entity_name(session, entity):
    return session._call_method(vutil, 'get_object_property',
                                entity, 'name')


def get_array_items(array_obj):
    """Get contained items if the object is a vSphere API array."""
    array_prefix = 'ArrayOf'
    if array_obj.__class__.__name__.startswith(array_prefix):
        attr_name = array_obj.__class__.__name__.replace(array_prefix, '', 1)
        if hasattr(array_obj, attr_name):
            return getattr(array_obj, attr_name)
    return array_obj
