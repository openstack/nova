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

from nova import utils
from nova.api.openstack import create_instance_helper as helper
from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import wsgi


class CreateServerController(servers.ControllerV11):
    def _build_view(self, req, instance, is_detail=False):
        server = super(CreateServerController, self)._build_view(req,
                                                             instance,
                                                             is_detail)
        if is_detail:
            self._build_security_groups(server['server'], instance)
        return server

    def _build_security_groups(self, response, inst):
        sg_names = []
        sec_groups = inst.get('security_groups')
        if sec_groups:
            sg_names = [sec_group['name'] for sec_group in sec_groups]

        response['security_groups'] = utils.convert_to_list_dict(sg_names,
                                                                 'name')


class Createserverext(extensions.ExtensionDescriptor):
    """The servers create ext"""
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
        body_serializers = {
            'application/xml': servers.ServerXMLSerializer(),
        }

        body_deserializers = {
            'application/xml': helper.ServerXMLDeserializerV11(),
        }

        serializer = wsgi.ResponseSerializer(body_serializers,
                                             headers_serializer)
        deserializer = wsgi.RequestDeserializer(body_deserializers)

        res = extensions.ResourceExtension('os-create-server-ext',
                                        controller=CreateServerController(),
                                        deserializer=deserializer,
                                        serializer=serializer)
        resources.append(res)

        return resources
