# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

""" The virtul storage array extension"""


from webob import exc

from nova import vsa
from nova import volume
from nova import compute
from nova import network
from nova import db
from nova import quota
from nova import exception
from nova import log as logging
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack import wsgi
from nova.api.openstack import servers
from nova.api.openstack.contrib import volumes
from nova.compute import instance_types

from nova import flags
FLAGS = flags.FLAGS

LOG = logging.getLogger("nova.api.vsa")


def _vsa_view(context, vsa, details=False, instances=None):
    """Map keys for vsa summary/detailed view."""
    d = {}

    d['id'] = vsa.get('id')
    d['name'] = vsa.get('name')
    d['displayName'] = vsa.get('display_name')
    d['displayDescription'] = vsa.get('display_description')

    d['createTime'] = vsa.get('created_at')
    d['status'] = vsa.get('status')

    if 'vsa_instance_type' in vsa:
        d['vcType'] = vsa['vsa_instance_type'].get('name', None)
    else:
        d['vcType'] = vsa['instance_type_id']

    d['vcCount'] = vsa.get('vc_count')
    d['driveCount'] = vsa.get('vol_count')

    d['ipAddress'] = None
    for instance in instances:
        fixed_addr = None
        floating_addr = None
        if instance['fixed_ips']:
            fixed = instance['fixed_ips'][0]
            fixed_addr = fixed['address']
            if fixed['floating_ips']:
                floating_addr = fixed['floating_ips'][0]['address']

        if floating_addr:
            d['ipAddress'] = floating_addr
            break
        else:
            d['ipAddress'] = d['ipAddress'] or fixed_addr

    return d


class VsaController(object):
    """The Virtual Storage Array API controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "vsa": [
                    "id",
                    "name",
                    "displayName",
                    "displayDescription",
                    "createTime",
                    "status",
                    "vcType",
                    "vcCount",
                    "driveCount",
                    "ipAddress",
                    ]}}}

    def __init__(self):
        self.vsa_api = vsa.API()
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(VsaController, self).__init__()

    def _get_instances_by_vsa_id(self, context, id):
        return self.compute_api.get_all(context,
                    search_opts={'metadata': dict(vsa_id=str(id))})

    def _items(self, req, details):
        """Return summary or detailed list of VSAs."""
        context = req.environ['nova.context']
        vsas = self.vsa_api.get_all(context)
        limited_list = common.limited(vsas, req)

        vsa_list = []
        for vsa in limited_list:
            instances = self._get_instances_by_vsa_id(context, vsa.get('id'))
            vsa_list.append(_vsa_view(context, vsa, details, instances))
        return {'vsaSet': vsa_list}

    def index(self, req):
        """Return a short list of VSAs."""
        return self._items(req, details=False)

    def detail(self, req):
        """Return a detailed list of VSAs."""
        return self._items(req, details=True)

    def show(self, req, id):
        """Return data about the given VSA."""
        context = req.environ['nova.context']

        try:
            vsa = self.vsa_api.get(context, vsa_id=id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        instances = self._get_instances_by_vsa_id(context, vsa.get('id'))
        return {'vsa': _vsa_view(context, vsa, True, instances)}

    def create(self, req, body):
        """Create a new VSA."""
        context = req.environ['nova.context']

        if not body or 'vsa' not in body:
            LOG.debug(_("No body provided"), context=context)
            return faults.Fault(exc.HTTPUnprocessableEntity())

        vsa = body['vsa']

        display_name = vsa.get('displayName')
        vc_type = vsa.get('vcType', FLAGS.default_vsa_instance_type)
        try:
            instance_type = instance_types.get_instance_type_by_name(vc_type)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        LOG.audit(_("Create VSA %(display_name)s of type %(vc_type)s"),
                    locals(), context=context)

        args = dict(display_name=display_name,
                display_description=vsa.get('displayDescription'),
                instance_type=instance_type,
                storage=vsa.get('storage'),
                shared=vsa.get('shared'),
                availability_zone=vsa.get('placement', {}).\
                                          get('AvailabilityZone'))

        vsa = self.vsa_api.create(context, **args)

        instances = self._get_instances_by_vsa_id(context, vsa.get('id'))
        return {'vsa': _vsa_view(context, vsa, True, instances)}

    def delete(self, req, id):
        """Delete a VSA."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete VSA with id: %s"), id, context=context)

        try:
            self.vsa_api.delete(context, vsa_id=id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

    def associate_address(self, req, id, body):
        """ /zadr-vsa/{vsa_id}/associate_address
        auto or manually associate an IP to VSA
        """
        context = req.environ['nova.context']

        if body is None:
            ip = 'auto'
        else:
            ip = body.get('ipAddress', 'auto')

        LOG.audit(_("Associate address %(ip)s to VSA %(id)s"),
                    locals(), context=context)

        try:
            instances = self._get_instances_by_vsa_id(context, id)
            if instances is None or len(instances) == 0:
                return faults.Fault(exc.HTTPNotFound())

            for instance in instances:
                self.network_api.allocate_for_instance(context, instance,
                                    vpn=False)
                # Placeholder
                return

        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

    def disassociate_address(self, req, id, body):
        """ /zadr-vsa/{vsa_id}/disassociate_address
        auto or manually associate an IP to VSA
        """
        context = req.environ['nova.context']

        if body is None:
            ip = 'auto'
        else:
            ip = body.get('ipAddress', 'auto')

        LOG.audit(_("Disassociate address from VSA %(id)s"),
                    locals(), context=context)
        # Placeholder


class VsaVolumeDriveController(volumes.VolumeController):
    """The base class for VSA volumes & drives.

    A child resource of the VSA object. Allows operations with
    volumes and drives created to/from particular VSA

    """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "volume": [
                    "id",
                    "name",
                    "status",
                    "size",
                    "availabilityZone",
                    "createdAt",
                    "displayName",
                    "displayDescription",
                    "vsaId",
                    ]}}}

    def __init__(self):
        self.volume_api = volume.API()
        self.vsa_api = vsa.API()
        super(VsaVolumeDriveController, self).__init__()

    def _translation(self, context, vol, vsa_id, details):
        if details:
            translation = volumes._translate_volume_detail_view
        else:
            translation = volumes._translate_volume_summary_view

        d = translation(context, vol)
        d['vsaId'] = vsa_id
        d['name'] = vol['name']
        return d

    def _check_volume_ownership(self, context, vsa_id, id):
        obj = self.object
        try:
            volume_ref = self.volume_api.get(context, volume_id=id)
        except exception.NotFound:
            LOG.error(_("%(obj)s with ID %(id)s not found"), locals())
            raise

        own_vsa_id = self.volume_api.get_volume_metadata_value(volume_ref,
                                                            self.direction)
        if  own_vsa_id != vsa_id:
            LOG.error(_("%(obj)s with ID %(id)s belongs to VSA %(own_vsa_id)s"\
                        " and not to VSA %(vsa_id)s."), locals())
            raise exception.Invalid()

    def _items(self, req, vsa_id, details):
        """Return summary or detailed list of volumes for particular VSA."""
        context = req.environ['nova.context']

        vols = self.volume_api.get_all(context,
                search_opts={'metadata': {self.direction: str(vsa_id)}})
        limited_list = common.limited(vols, req)

        res = [self._translation(context, vol, vsa_id, details) \
               for vol in limited_list]

        return {self.objects: res}

    def index(self, req, vsa_id):
        """Return a short list of volumes created from particular VSA."""
        LOG.audit(_("Index. vsa_id=%(vsa_id)s"), locals())
        return self._items(req, vsa_id, details=False)

    def detail(self, req, vsa_id):
        """Return a detailed list of volumes created from particular VSA."""
        LOG.audit(_("Detail. vsa_id=%(vsa_id)s"), locals())
        return self._items(req, vsa_id, details=True)

    def create(self, req, vsa_id, body):
        """Create a new volume from VSA."""
        LOG.audit(_("Create. vsa_id=%(vsa_id)s, body=%(body)s"), locals())
        context = req.environ['nova.context']

        if not body:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        vol = body[self.object]
        size = vol['size']
        LOG.audit(_("Create volume of %(size)s GB from VSA ID %(vsa_id)s"),
                    locals(), context=context)
        try:
            # create is supported for volumes only (drives created through VSA)
            volume_type = self.vsa_api.get_vsa_volume_type(context)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        new_volume = self.volume_api.create(context,
                            size,
                            None,
                            vol.get('displayName'),
                            vol.get('displayDescription'),
                            volume_type=volume_type,
                            metadata=dict(from_vsa_id=str(vsa_id)))

        return {self.object: self._translation(context, new_volume,
                                               vsa_id, True)}

    def update(self, req, vsa_id, id, body):
        """Update a volume."""
        context = req.environ['nova.context']

        try:
            self._check_volume_ownership(context, vsa_id, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        except exception.Invalid:
            return faults.Fault(exc.HTTPBadRequest())

        vol = body[self.object]
        updatable_fields = [{'displayName': 'display_name'},
                            {'displayDescription': 'display_description'},
                            {'status': 'status'},
                            {'providerLocation': 'provider_location'},
                            {'providerAuth': 'provider_auth'}]
        changes = {}
        for field in updatable_fields:
            key = field.keys()[0]
            val = field[key]
            if key in vol:
                changes[val] = vol[key]

        obj = self.object
        LOG.audit(_("Update %(obj)s with id: %(id)s, changes: %(changes)s"),
                    locals(), context=context)

        try:
            self.volume_api.update(context, volume_id=id, fields=changes)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPAccepted()

    def delete(self, req, vsa_id, id):
        """Delete a volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete. vsa_id=%(vsa_id)s, id=%(id)s"), locals())

        try:
            self._check_volume_ownership(context, vsa_id, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        except exception.Invalid:
            return faults.Fault(exc.HTTPBadRequest())

        return super(VsaVolumeDriveController, self).delete(req, id)

    def show(self, req, vsa_id, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Show. vsa_id=%(vsa_id)s, id=%(id)s"), locals())

        try:
            self._check_volume_ownership(context, vsa_id, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        except exception.Invalid:
            return faults.Fault(exc.HTTPBadRequest())

        return super(VsaVolumeDriveController, self).show(req, id)


class VsaVolumeController(VsaVolumeDriveController):
    """The VSA volume API controller for the Openstack API.

    A child resource of the VSA object. Allows operations with volumes created
    by particular VSA

    """

    def __init__(self):
        self.direction = 'from_vsa_id'
        self.objects = 'volumes'
        self.object = 'volume'
        super(VsaVolumeController, self).__init__()


class VsaDriveController(VsaVolumeDriveController):
    """The VSA Drive API controller for the Openstack API.

    A child resource of the VSA object. Allows operations with drives created
    for particular VSA

    """

    def __init__(self):
        self.direction = 'to_vsa_id'
        self.objects = 'drives'
        self.object = 'drive'
        super(VsaDriveController, self).__init__()

    def create(self, req, vsa_id, body):
        """Create a new drive for VSA. Should be done through VSA APIs"""
        return faults.Fault(exc.HTTPBadRequest())

    def update(self, req, vsa_id, id, body):
        """Update a drive. Should be done through VSA APIs"""
        return faults.Fault(exc.HTTPBadRequest())

    def delete(self, req, vsa_id, id):
        """Delete a volume. Should be done through VSA APIs"""
        return faults.Fault(exc.HTTPBadRequest())


class VsaVPoolController(object):
    """The vPool VSA API controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "vpool": [
                    "id",
                    "vsaId",
                    "name",
                    "displayName",
                    "displayDescription",
                    "driveCount",
                    "driveIds",
                    "protection",
                    "stripeSize",
                    "stripeWidth",
                    "createTime",
                    "status",
                    ]}}}

    def __init__(self):
        self.vsa_api = vsa.API()
        super(VsaVPoolController, self).__init__()

    def index(self, req, vsa_id):
        """Return a short list of vpools created from particular VSA."""
        return {'vpools': []}

    def create(self, req, vsa_id, body):
        """Create a new vPool for VSA."""
        return faults.Fault(exc.HTTPBadRequest())

    def update(self, req, vsa_id, id, body):
        """Update vPool parameters."""
        return faults.Fault(exc.HTTPBadRequest())

    def delete(self, req, vsa_id, id):
        """Delete a vPool."""
        return faults.Fault(exc.HTTPBadRequest())

    def show(self, req, vsa_id, id):
        """Return data about the given vPool."""
        return faults.Fault(exc.HTTPBadRequest())


class VsaVCController(servers.ControllerV11):
    """The VSA Virtual Controller API controller for the OpenStack API."""

    def __init__(self):
        self.vsa_api = vsa.API()
        self.compute_api = compute.API()
        self.vsa_id = None      # VP-TODO: temporary ugly hack
        super(VsaVCController, self).__init__()

    def _get_servers(self, req, is_detail):
        """Returns a list of servers, taking into account any search
        options specified.
        """

        if self.vsa_id is None:
            super(VsaVCController, self)._get_servers(req, is_detail)

        context = req.environ['nova.context']

        search_opts = {'metadata': dict(vsa_id=str(self.vsa_id))}
        instance_list = self.compute_api.get_all(
                context, search_opts=search_opts)

        limited_list = self._limit_items(instance_list, req)
        servers = [self._build_view(req, inst, is_detail)['server']
                for inst in limited_list]
        return dict(servers=servers)

    def index(self, req, vsa_id):
        """Return list of instances for particular VSA."""

        LOG.audit(_("Index instances for VSA %s"), vsa_id)

        self.vsa_id = vsa_id    # VP-TODO: temporary ugly hack
        result = super(VsaVCController, self).detail(req)
        self.vsa_id = None
        return result

    def create(self, req, vsa_id, body):
        """Create a new instance for VSA."""
        return faults.Fault(exc.HTTPBadRequest())

    def update(self, req, vsa_id, id, body):
        """Update VSA instance."""
        return faults.Fault(exc.HTTPBadRequest())

    def delete(self, req, vsa_id, id):
        """Delete VSA instance."""
        return faults.Fault(exc.HTTPBadRequest())

    def show(self, req, vsa_id, id):
        """Return data about the given instance."""
        return super(VsaVCController, self).show(req, id)


class Virtual_storage_arrays(extensions.ExtensionDescriptor):

    def get_name(self):
        return "VSAs"

    def get_alias(self):
        return "zadr-vsa"

    def get_description(self):
        return "Virtual Storage Arrays support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/vsa/api/v1.1"

    def get_updated(self):
        return "2011-08-25T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
                            'zadr-vsa',
                            VsaController(),
                            collection_actions={'detail': 'GET'},
                            member_actions={'add_capacity': 'POST',
                                            'remove_capacity': 'POST',
                                            'associate_address': 'POST',
                                            'disassociate_address': 'POST'})
        resources.append(res)

        res = extensions.ResourceExtension('volumes',
                            VsaVolumeController(),
                            collection_actions={'detail': 'GET'},
                            parent=dict(
                                member_name='vsa',
                                collection_name='zadr-vsa'))
        resources.append(res)

        res = extensions.ResourceExtension('drives',
                            VsaDriveController(),
                            collection_actions={'detail': 'GET'},
                            parent=dict(
                                member_name='vsa',
                                collection_name='zadr-vsa'))
        resources.append(res)

        res = extensions.ResourceExtension('vpools',
                            VsaVPoolController(),
                            parent=dict(
                                member_name='vsa',
                                collection_name='zadr-vsa'))
        resources.append(res)

        res = extensions.ResourceExtension('instances',
                            VsaVCController(),
                            parent=dict(
                                member_name='vsa',
                                collection_name='zadr-vsa'))
        resources.append(res)

        return resources
