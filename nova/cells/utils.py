# Copyright (c) 2012 Rackspace Hosting
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

"""
Cells Utility Methods
"""
import random
import sys

from nova import db
from nova import exception
from nova import objects
from nova.objects import base as obj_base


# Separator used between cell names for the 'full cell name' and routing
# path
PATH_CELL_SEP = '!'
# Separator used between cell name and item
_CELL_ITEM_SEP = '@'


class ProxyObjectSerializer(obj_base.NovaObjectSerializer):
    def __init__(self):
        super(ProxyObjectSerializer, self).__init__()
        self.serializer = super(ProxyObjectSerializer, self)

    def _process_object(self, context, objprim):
        return _CellProxy.obj_from_primitive(self.serializer, objprim, context)


class _CellProxy(object):
    def __init__(self, obj, cell_path):
        self._obj = obj
        self._cell_path = cell_path

    @property
    def id(self):
        return cell_with_item(self._cell_path, self._obj.id)

    @property
    def host(self):
        return cell_with_item(self._cell_path, self._obj.host)

    def __getitem__(self, key):
        if key == 'id':
            return self.id
        if key == 'host':
            return self.host

        return getattr(self._obj, key)

    def obj_to_primitive(self):
        obj_p = self._obj.obj_to_primitive()
        obj_p['cell_proxy.class_name'] = self.__class__.__name__
        obj_p['cell_proxy.cell_path'] = self._cell_path
        return obj_p

    @classmethod
    def obj_from_primitive(cls, serializer, primitive, context=None):
        obj_primitive = primitive.copy()
        cell_path = obj_primitive.pop('cell_proxy.cell_path', None)
        klass_name = obj_primitive.pop('cell_proxy.class_name', None)
        obj = serializer._process_object(context, obj_primitive)
        if klass_name is not None and cell_path is not None:
            klass = getattr(sys.modules[__name__], klass_name)
            return klass(obj, cell_path)
        else:
            return obj

    # dict-ish syntax sugar
    def iteritems(self):
        """For backwards-compatibility with dict-based objects.

        NOTE(sbauza): May be removed in the future.
        """
        for name in self._obj.obj_fields:
            if (self._obj.obj_attr_is_set(name) or
                    name in self._obj.obj_extra_fields):
                if name == 'id':
                    yield name, self.id
                elif name == 'host':
                    yield name, self.host
                else:
                    yield name, getattr(self._obj, name)

    def __getattr__(self, key):
        return getattr(self._obj, key)


class ComputeNodeProxy(_CellProxy):
    pass


class ServiceProxy(_CellProxy):
    def __getattr__(self, key):
        if key == 'compute_node':
            # NOTE(sbauza): As the Service object is still having a nested
            # ComputeNode object that consumers of this Proxy don't use, we can
            # safely remove it from what's returned
            raise AttributeError
        return getattr(self._obj, key)


def get_instances_to_sync(context, updated_since=None, project_id=None,
        deleted=True, shuffle=False, uuids_only=False):
    """Return a generator that will return a list of active and
    deleted instances to sync with parent cells.  The list may
    optionally be shuffled for periodic updates so that multiple
    cells services aren't self-healing the same instances in nearly
    lockstep.
    """
    filters = {}
    if updated_since is not None:
        filters['changes-since'] = updated_since
    if project_id is not None:
        filters['project_id'] = project_id
    if not deleted:
        filters['deleted'] = False
    # Active instances first.
    instances = db.instance_get_all_by_filters(
            context, filters, 'deleted', 'asc')
    if shuffle:
        random.shuffle(instances)
    for instance in instances:
        if uuids_only:
            yield instance['uuid']
        else:
            yield instance


def cell_with_item(cell_name, item):
    """Turn cell_name and item into <cell_name>@<item>."""
    if cell_name is None:
        return item
    return cell_name + _CELL_ITEM_SEP + str(item)


def split_cell_and_item(cell_and_item):
    """Split a combined cell@item and return them."""
    result = cell_and_item.rsplit(_CELL_ITEM_SEP, 1)
    if len(result) == 1:
        return (None, cell_and_item)
    else:
        return result


def add_cell_to_compute_node(compute_node, cell_name):
    """Fix compute_node attributes that should be unique.  Allows
    API cell to query the 'id' by cell@id.
    """
    # NOTE(sbauza): As compute_node is a ComputeNode object, we need to wrap it
    # for adding the cell_path information
    compute_proxy = ComputeNodeProxy(compute_node, cell_name)
    try:
        service = compute_proxy.service
    except exception.ServiceNotFound:
        service = None
    if isinstance(service, objects.Service):
        compute_proxy.service = ServiceProxy(service, cell_name)
    return compute_proxy


def add_cell_to_service(service, cell_name):
    """Fix service attributes that should be unique.  Allows
    API cell to query the 'id' or 'host' by cell@id/host.
    """
    # NOTE(sbauza): As service is a Service object, we need to wrap it
    # for adding the cell_path information
    service_proxy = ServiceProxy(service, cell_name)
    return service_proxy


def add_cell_to_task_log(task_log, cell_name):
    """Fix task_log attributes that should be unique.  In particular,
    the 'id' and 'host' fields should be prepended with cell name.
    """
    task_log['id'] = cell_with_item(cell_name, task_log['id'])
    task_log['host'] = cell_with_item(cell_name, task_log['host'])
