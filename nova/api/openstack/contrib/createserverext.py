# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
#    under the License
from webob import exc

from nova import exception
import nova.image
from nova import network
from nova import quota
from nova import rpc

from nova.api.openstack import create_instance_helper as helper
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.compute import instance_types
from nova.api.openstack import servers
from nova.api.openstack import wsgi
from nova.auth import manager as auth_manager


class CreateInstanceHelperEx(helper.CreateInstanceHelper):
    def __init__(self, controller):
        super(CreateInstanceHelperEx, self).__init__(controller)

    def create_instance(self, req, body, create_method):
        """Creates a new server for the given user as per
        the network information if it is provided
        """
        if not body:
            raise faults.Fault(exc.HTTPUnprocessableEntity())

        context = req.environ['nova.context']

        password = self.controller._get_server_admin_password(body['server'])

        key_name = None
        key_data = None
        key_pairs = auth_manager.AuthManager.get_key_pairs(context)
        if key_pairs:
            key_pair = key_pairs[0]
            key_name = key_pair['name']
            key_data = key_pair['public_key']

        image_href = self.controller._image_ref_from_req_data(body)
        try:
            image_service, image_id = nova.image.get_image_service(image_href)
            kernel_id, ramdisk_id = self._get_kernel_ramdisk_from_image(
                                                req, image_id)
            images = set([str(x['id']) for x in image_service.index(context)])
            assert str(image_id) in images
        except Exception, e:
            msg = _("Cannot find requested image %(image_href)s: %(e)s" %
                                                                    locals())
            raise faults.Fault(exc.HTTPBadRequest(explanation=msg))

        personality = body['server'].get('personality')

        injected_files = []
        if personality:
            injected_files = self._get_injected_files(personality)

        requested_networks = body['server'].get('networks')

        if requested_networks is not None:
            requested_networks = self._get_requested_networks(
                                                    requested_networks)

        flavor_id = self.controller._flavor_id_from_req_data(body)

        if not 'name' in body['server']:
            msg = _("Server name is not defined")
            raise exc.HTTPBadRequest(explanation=msg)

        zone_blob = body['server'].get('blob')
        name = body['server']['name']
        self._validate_server_name(name)
        name = name.strip()

        reservation_id = body['server'].get('reservation_id')
        min_count = body['server'].get('min_count')
        max_count = body['server'].get('max_count')
        # min_count and max_count are optional.  If they exist, they come
        # in as strings.  We want to default 'min_count' to 1, and default
        # 'max_count' to be 'min_count'.
        min_count = int(min_count) if min_count else 1
        max_count = int(max_count) if max_count else min_count
        if min_count > max_count:
            min_count = max_count

        try:
            inst_type = \
                    instance_types.get_instance_type_by_flavor_id(flavor_id)
            extra_values = {
                'instance_type': inst_type,
                'image_ref': image_href,
                'password': password}

            return (extra_values,
                    create_method(context,
                                  inst_type,
                                  image_id,
                                  kernel_id=kernel_id,
                                  ramdisk_id=ramdisk_id,
                                  display_name=name,
                                  display_description=name,
                                  key_name=key_name,
                                  key_data=key_data,
                                  metadata=body['server'].get('metadata', {}),
                                  injected_files=injected_files,
                                  admin_password=password,
                                  zone_blob=zone_blob,
                                  reservation_id=reservation_id,
                                  min_count=min_count,
                                  max_count=max_count,
                                  requested_networks=requested_networks))
        except quota.QuotaError as error:
            self._handle_quota_error(error)
        except exception.ImageNotFound as error:
            msg = _("Can not find requested image")
            raise faults.Fault(exc.HTTPBadRequest(explanation=msg))
        except rpc.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % \
                    {'err_type': err.exc_type, 'err_msg': err.value}
            raise faults.Fault(exc.HTTPBadRequest(explanation=msg))

        # Let the caller deal with unhandled exceptions.

    def _validate_fixed_ip(self, value):
        if not isinstance(value, basestring):
            msg = _("Fixed IP is not a string or unicode")
            raise exc.HTTPBadRequest(explanation=msg)

        if value.strip() == '':
            msg = _("Fixed IP is an empty string")
            raise exc.HTTPBadRequest(explanation=msg)

    def _get_requested_networks(self, requested_networks):
        """
        Create a list of requested networks from the networks attribute
        """
        networks = []
        for network in requested_networks:
            try:
                network_id = network['id']
                network_id = int(network_id)
                #fixed IP address is optional
                #if the fixed IP address is not provided then
                #it will use one of the available IP address from the network
                fixed_ip = network.get('fixed_ip', None)
                if fixed_ip is not None:
                    self._validate_fixed_ip(fixed_ip)
                # check if the network id is already present in the list,
                # we don't want duplicate networks to be passed
                # at the boot time
                for id, ip in networks:
                    if id == network_id:
                        expl = _("Duplicate networks (%s) are not allowed")\
                                % network_id
                        raise faults.Fault(exc.HTTPBadRequest(
                                               explanation=expl))

                networks.append((network_id, fixed_ip))
            except KeyError as key:
                expl = _('Bad network format: missing %s') % key
                raise faults.Fault(exc.HTTPBadRequest(explanation=expl))
            except ValueError:
                expl = _("Bad networks format: network id should "
                         "be integer (%s)") % network_id
                raise faults.Fault(exc.HTTPBadRequest(explanation=expl))
            except TypeError:
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)

        return networks


class CreateServerExtController(servers.ControllerV11):
    """This is the controller for the extended version
    of the create server OS V1.1
    """
    def __init__(self):
        super(CreateServerExtController, self).__init__()
        self.helper = CreateInstanceHelperEx(self)


class Createserverext(extensions.ExtensionDescriptor):
    """The servers create ext

    Exposes addFixedIp and removeFixedIp actions on servers.

    """
    def get_name(self):
        return "Createserverext"

    def get_alias(self):
        return "os-create-server-ext"

    def get_description(self):
        return "Extended support to the Create Server v1.1 API"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/createserverext/api/v1.1"

    def get_updated(self):
        return "2011-07-19T00:00:00+00:00"

    def get_resources(self):
        resources = []

        headers_serializer = servers.HeadersSerializer()
        metadata = servers._get_metadata()
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11),
        }

        body_deserializers = {
            'application/xml': helper.ServerXMLDeserializer(),
        }

        serializer = wsgi.ResponseSerializer(body_serializers,
                                             headers_serializer)
        deserializer = wsgi.RequestDeserializer(body_deserializers)

        res = extensions.ResourceExtension('os-create-server-ext',
                                        controller=CreateServerExtController(),
                                        deserializer=deserializer,
                                        serializer=serializer)
        resources.append(res)

        return resources
