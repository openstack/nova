# Copyright 2011 Justin Santa Barbara
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

from webob import exc

from nova import exception
from nova import flags
from nova import log as logging
from nova import volume
from nova import wsgi
from nova.api.openstack import common
from nova.api.openstack import faults


LOG = logging.getLogger("nova.api.volumes")

FLAGS = flags.FLAGS


def _translate_detail_view(context, vol):
    """ Maps keys for details view"""

    d = _translate_summary_view(context, vol)

    # No additional data / lookups at the moment

    return d


def _translate_summary_view(_context, vol):
    """ Maps keys for summary view"""
    d = {}

    instance_id = None
    #    instance_data = None
    attached_to = vol.get('instance')
    if attached_to:
        instance_id = attached_to['id']
    #        instance_data = '%s[%s]' % (instance_ec2_id,
    #                                    attached_to['host'])
    d['id'] = vol['id']
    d['status'] = vol['status']
    d['size'] = vol['size']
    d['availabilityZone'] = vol['availability_zone']
    d['createdAt'] = vol['created_at']
    #    if context.is_admin:
    #        v['status'] = '%s (%s, %s, %s, %s)' % (
    #            vol['status'],
    #            vol['user_id'],
    #            vol['host'],
    #            instance_data,
    #            vol['mountpoint'])
    if vol['attach_status'] == 'attached':
        d['attachments'] = [{'attachTime': vol['attach_time'],
                             'deleteOnTermination': False,
                             'mountpoint': vol['mountpoint'],
                             'instanceId': instance_id,
                             'status': 'attached',
                             'volumeId': vol['id']}]
    else:
        d['attachments'] = [{}]

    d['displayName'] = vol['display_name']
    d['displayDescription'] = vol['display_description']
    return d


class Controller(wsgi.Controller):
    """ The Volumes API controller for the OpenStack API """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "volume": [
                    "id",
                    "status",
                    "size",
                    "availabilityZone",
                    "createdAt",
                    "displayName",
                    "displayDescription",
                    ]}}}

    def __init__(self):
        self.volume_api = volume.API()
        super(Controller, self).__init__()

    def show(self, req, id):
        """Return data about the given volume"""
        context = req.environ['nova.context']

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        return {'volume': _translate_detail_view(context, vol)}

    def delete(self, req, id):
        """ Delete a volume """
        context = req.environ['nova.context']

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            self.volume_api.delete(context, volume_id=id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPAccepted()

    def index(self, req):
        """ Returns a summary list of volumes"""
        return self._items(req, entity_maker=_translate_summary_view)

    def detail(self, req):
        """ Returns a detailed list of volumes """
        return self._items(req, entity_maker=_translate_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker"""
        context = req.environ['nova.context']

        volumes = self.volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

    def create(self, req):
        """Creates a new volume"""
        context = req.environ['nova.context']

        env = self._deserialize(req.body, req)
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        vol = env['volume']
        size = vol['size']
        LOG.audit(_("Create volume of %s GB"), size, context=context)
        new_volume = self.volume_api.create(context, size,
                                            vol.get('display_name'),
                                            vol.get('display_description'))

        # Work around problem that instance is lazy-loaded...
        volume['instance'] = None

        retval = _translate_detail_view(context, new_volume)

        return {'volume': retval}
