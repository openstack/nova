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


import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.contrib import volumes
from nova.api.openstack import extensions
from nova.api.openstack.compute import servers
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.compute import instance_types
from nova import network
from nova import exception
from nova import flags
from nova import log as logging
from nova import vsa
from nova import volume

FLAGS = flags.FLAGS

LOG = logging.getLogger("nova.api.openstack.compute.contrib.vsa")


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


def make_vsa(elem):
    elem.set('id')
    elem.set('name')
    elem.set('displayName')
    elem.set('displayDescription')
    elem.set('createTime')
    elem.set('status')
    elem.set('vcType')
    elem.set('vcCount')
    elem.set('driveCount')
    elem.set('ipAddress')


class VsaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vsa', selector='vsa')
        make_vsa(root)
        return xmlutil.MasterTemplate(root, 1)


class VsaSetTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vsaSet')
        elem = xmlutil.SubTemplateElement(root, 'vsa', selector='vsaSet')
        make_vsa(elem)
        return xmlutil.MasterTemplate(root, 1)


class VsaController(object):
    """The Virtual Storage Array API controller for the OpenStack API."""

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

    @wsgi.serializers(xml=VsaSetTemplate)
    def index(self, req):
        """Return a short list of VSAs."""
        return self._items(req, details=False)

    @wsgi.serializers(xml=VsaSetTemplate)
    def detail(self, req):
        """Return a detailed list of VSAs."""
        return self._items(req, details=True)

    @wsgi.serializers(xml=VsaTemplate)
    def show(self, req, id):
        """Return data about the given VSA."""
        context = req.environ['nova.context']

        try:
            vsa = self.vsa_api.get(context, vsa_id=id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        instances = self._get_instances_by_vsa_id(context, vsa.get('id'))
        return {'vsa': _vsa_view(context, vsa, True, instances)}

    @wsgi.serializers(xml=VsaTemplate)
    def create(self, req, body):
        """Create a new VSA."""
        context = req.environ['nova.context']

        if not body or 'vsa' not in body:
            LOG.debug(_("No body provided"), context=context)
            raise exc.HTTPUnprocessableEntity()

        vsa = body['vsa']

        display_name = vsa.get('displayName')
        vc_type = vsa.get('vcType', FLAGS.default_vsa_instance_type)
        try:
            instance_type = instance_types.get_instance_type_by_name(vc_type)
        except exception.NotFound:
            raise exc.HTTPNotFound()

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
            raise exc.HTTPNotFound()

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
                raise exc.HTTPNotFound()

            for instance in instances:
                self.network_api.allocate_for_instance(context, instance,
                                    vpn=False)
                # Placeholder
                return

        except exception.NotFound:
            raise exc.HTTPNotFound()

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


def make_volume(elem):
    volumes.make_volume(elem)
    elem.set('name')
    elem.set('vsaId')


class VsaVolumeDriveController(volumes.VolumeController):
    """The base class for VSA volumes & drives.

    A child resource of the VSA object. Allows operations with
    volumes and drives created to/from particular VSA

    """

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
            volume_ref = self.volume_api.get(context, id)
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
            raise exc.HTTPUnprocessableEntity()

        vol = body[self.object]
        size = vol['size']
        LOG.audit(_("Create volume of %(size)s GB from VSA ID %(vsa_id)s"),
                    locals(), context=context)
        try:
            # create is supported for volumes only (drives created through VSA)
            volume_type = self.vsa_api.get_vsa_volume_type(context)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        new_volume = self.volume_api.create(context,
                            size,
                            vol.get('displayName'),
                            vol.get('displayDescription'),
                            None,
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
            raise exc.HTTPNotFound()
        except exception.Invalid:
            raise exc.HTTPBadRequest()

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
            volume = self.volume_api.get(context, id)
            self.volume_api.update(context, volume, fields=changes)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    def delete(self, req, vsa_id, id):
        """Delete a volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete. vsa_id=%(vsa_id)s, id=%(id)s"), locals())

        try:
            self._check_volume_ownership(context, vsa_id, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        except exception.Invalid:
            raise exc.HTTPBadRequest()

        return super(VsaVolumeDriveController, self).delete(req, id)

    def show(self, req, vsa_id, id):
        """Return data about the given volume."""
        context = req.environ['nova.context']

        LOG.audit(_("Show. vsa_id=%(vsa_id)s, id=%(id)s"), locals())

        try:
            self._check_volume_ownership(context, vsa_id, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        except exception.Invalid:
            raise exc.HTTPBadRequest()

        return super(VsaVolumeDriveController, self).show(req, id)


class VsaVolumeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        return xmlutil.MasterTemplate(root, 1)


class VsaVolumesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        return xmlutil.MasterTemplate(root, 1)


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

    @wsgi.serializers(xml=VsaVolumesTemplate)
    def index(self, req, vsa_id):
        return super(VsaVolumeController, self).index(req, vsa_id)

    @wsgi.serializers(xml=VsaVolumesTemplate)
    def detail(self, req, vsa_id):
        return super(VsaVolumeController, self).detail(req, vsa_id)

    @wsgi.serializers(xml=VsaVolumeTemplate)
    def create(self, req, vsa_id, body):
        return super(VsaVolumeController, self).create(req, vsa_id, body)

    @wsgi.serializers(xml=VsaVolumeTemplate)
    def update(self, req, vsa_id, id, body):
        return super(VsaVolumeController, self).update(req, vsa_id, id, body)

    @wsgi.serializers(xml=VsaVolumeTemplate)
    def show(self, req, vsa_id, id):
        return super(VsaVolumeController, self).show(req, vsa_id, id)


class VsaDriveTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('drive', selector='drive')
        make_volume(root)
        return xmlutil.MasterTemplate(root, 1)


class VsaDrivesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('drives')
        elem = xmlutil.SubTemplateElement(root, 'drive', selector='drives')
        make_volume(elem)
        return xmlutil.MasterTemplate(root, 1)


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
        raise exc.HTTPBadRequest()

    def update(self, req, vsa_id, id, body):
        """Update a drive. Should be done through VSA APIs"""
        raise exc.HTTPBadRequest()

    def delete(self, req, vsa_id, id):
        """Delete a volume. Should be done through VSA APIs"""
        raise exc.HTTPBadRequest()

    @wsgi.serializers(xml=VsaDrivesTemplate)
    def index(self, req, vsa_id):
        return super(VsaDriveController, self).index(req, vsa_id)

    @wsgi.serializers(xml=VsaDrivesTemplate)
    def detail(self, req, vsa_id):
        return super(VsaDriveController, self).detail(req, vsa_id)

    @wsgi.serializers(xml=VsaDriveTemplate)
    def show(self, req, vsa_id, id):
        return super(VsaDriveController, self).show(req, vsa_id, id)


def make_vpool(elem):
    elem.set('id')
    elem.set('vsaId')
    elem.set('name')
    elem.set('displayName')
    elem.set('displayDescription')
    elem.set('driveCount')
    elem.set('protection')
    elem.set('stripeSize')
    elem.set('stripeWidth')
    elem.set('createTime')
    elem.set('status')

    drive_ids = xmlutil.SubTemplateElement(elem, 'driveIds')
    drive_id = xmlutil.SubTemplateElement(drive_ids, 'driveId',
                                          selector='driveIds')
    drive_id.text = xmlutil.Selector()


class VsaVPoolTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vpool', selector='vpool')
        make_vpool(root)
        return xmlutil.MasterTemplate(root, 1)


class VsaVPoolsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('vpools')
        elem = xmlutil.SubTemplateElement(root, 'vpool', selector='vpools')
        make_vpool(elem)
        return xmlutil.MasterTemplate(root, 1)


class VsaVPoolController(object):
    """The vPool VSA API controller for the OpenStack API."""

    def __init__(self):
        self.vsa_api = vsa.API()
        super(VsaVPoolController, self).__init__()

    @wsgi.serializers(xml=VsaVPoolsTemplate)
    def index(self, req, vsa_id):
        """Return a short list of vpools created from particular VSA."""
        return {'vpools': []}

    def create(self, req, vsa_id, body):
        """Create a new vPool for VSA."""
        raise exc.HTTPBadRequest()

    def update(self, req, vsa_id, id, body):
        """Update vPool parameters."""
        raise exc.HTTPBadRequest()

    def delete(self, req, vsa_id, id):
        """Delete a vPool."""
        raise exc.HTTPBadRequest()

    def show(self, req, vsa_id, id):
        """Return data about the given vPool."""
        raise exc.HTTPBadRequest()


class VsaVCController(servers.Controller):
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

    @wsgi.serializers(xml=servers.MinimalServersTemplate)
    def index(self, req, vsa_id):
        """Return list of instances for particular VSA."""

        LOG.audit(_("Index instances for VSA %s"), vsa_id)

        self.vsa_id = vsa_id    # VP-TODO: temporary ugly hack
        result = super(VsaVCController, self).detail(req)
        self.vsa_id = None
        return result

    def create(self, req, vsa_id, body):
        """Create a new instance for VSA."""
        raise exc.HTTPBadRequest()

    def update(self, req, vsa_id, id, body):
        """Update VSA instance."""
        raise exc.HTTPBadRequest()

    def delete(self, req, vsa_id, id):
        """Delete VSA instance."""
        raise exc.HTTPBadRequest()

    @wsgi.serializers(xml=servers.ServerTemplate)
    def show(self, req, vsa_id, id):
        """Return data about the given instance."""
        return super(VsaVCController, self).show(req, id)


class Virtual_storage_arrays(extensions.ExtensionDescriptor):
    """Virtual Storage Arrays support"""

    name = "VSAs"
    alias = "zadr-vsa"
    namespace = "http://docs.openstack.org/compute/ext/vsa/api/v1.1"
    updated = "2011-08-25T00:00:00+00:00"

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
