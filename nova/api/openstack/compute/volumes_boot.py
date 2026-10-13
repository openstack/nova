# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.api.openstack.compute.schemas import servers as schema
from nova.api.openstack.compute import servers
from nova.api.openstack import wsgi
from nova.api import validation


class VolumesBootController(servers.ServersController):
    """This API is deprecated from microversion '2.103'."""

    @wsgi.api_version('2.1', '2.102')
    @wsgi.expected_errors((400, 403))
    @validation.query_schema(schema.index_query, '2.1', '2.25')
    @validation.query_schema(schema.index_query_v226, '2.26', '2.65')
    @validation.query_schema(schema.index_query_v266, '2.66', '2.72')
    @validation.query_schema(schema.index_query_v273, '2.73', '2.74')
    @validation.query_schema(schema.index_query_v275, '2.75')
    @validation.response_body_schema(schema.index_response, '2.1', '2.68')
    @validation.response_body_schema(schema.index_response_v269, '2.69')
    def index(self, req):
        return super().index(req)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.expected_errors((400, 403))
    @validation.query_schema(schema.index_query, '2.1', '2.25')
    @validation.query_schema(schema.index_query_v226, '2.26', '2.65')
    @validation.query_schema(schema.index_query_v266, '2.66', '2.72')
    @validation.query_schema(schema.index_query_v273, '2.73', '2.74')
    @validation.query_schema(schema.index_query_v275, '2.75')
    @validation.response_body_schema(schema.detail_response, '2.1', '2.2')
    @validation.response_body_schema(schema.detail_response_v23, '2.3', '2.8')
    @validation.response_body_schema(schema.detail_response_v29, '2.9', '2.15')
    @validation.response_body_schema(schema.detail_response_v216, '2.16', '2.18')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v219, '2.19', '2.25')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v226, '2.26', '2.46')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v247, '2.47', '2.62')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v263, '2.63', '2.68')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v269, '2.69', '2.72')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v273, '2.73', '2.89')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v290, '2.90', '2.95')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v296, '2.96', '2.97')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v298, '2.98', '2.99')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v2100, '2.100')
    def detail(self, req):
        return super().detail(req)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.expected_errors(404)
    @validation.query_schema(schema.show_query, '2.1', '2.101')
    @validation.query_schema(schema.show_query_v2102, '2.102')
    @validation.response_body_schema(schema.show_response, '2.0', '2.2')
    @validation.response_body_schema(schema.show_response_v23, '2.3', '2.8')
    @validation.response_body_schema(schema.show_response_v29, '2.9', '2.15')
    @validation.response_body_schema(schema.show_response_v216, '2.16', '2.18')
    @validation.response_body_schema(schema.show_response_v219, '2.19', '2.25')
    @validation.response_body_schema(schema.show_response_v226, '2.26', '2.46')
    @validation.response_body_schema(schema.show_response_v247, '2.47', '2.62')
    @validation.response_body_schema(schema.show_response_v263, '2.63', '2.68')
    @validation.response_body_schema(schema.show_response_v269, '2.69', '2.70')
    @validation.response_body_schema(schema.show_response_v271, '2.71', '2.72')
    @validation.response_body_schema(schema.show_response_v273, '2.73', '2.89')
    @validation.response_body_schema(schema.show_response_v290, '2.90', '2.95')
    @validation.response_body_schema(schema.show_response_v296, '2.96', '2.97')
    @validation.response_body_schema(schema.show_response_v298, '2.98', '2.99')
    @validation.response_body_schema(schema.show_response_v2100, '2.100')
    def show(self, req, id):
        return super().show(req, id)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 409))
    @validation.schema(schema.create_v20, '2.0', '2.0')
    @validation.schema(schema.create, '2.1', '2.18')
    @validation.schema(schema.create_v219, '2.19', '2.31')
    @validation.schema(schema.create_v232, '2.32', '2.32')
    @validation.schema(schema.create_v233, '2.33', '2.36')
    @validation.schema(schema.create_v237, '2.37', '2.41')
    @validation.schema(schema.create_v242, '2.42', '2.51')
    @validation.schema(schema.create_v252, '2.52', '2.56')
    @validation.schema(schema.create_v257, '2.57', '2.62')
    @validation.schema(schema.create_v263, '2.63', '2.66')
    @validation.schema(schema.create_v267, '2.67', '2.73')
    @validation.schema(schema.create_v274, '2.74', '2.89')
    @validation.schema(schema.create_v290, '2.90', '2.93')
    @validation.schema(schema.create_v294, '2.94')
    @validation.response_body_schema(schema.create_response)
    def create(self, req, body):
        return super().create(req, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(204)
    @wsgi.expected_errors((404, 409))
    @validation.response_body_schema(schema.delete_response)
    def delete(self, req, id):
        return super().delete(req, id)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.expected_errors(404)
    @validation.schema(schema.update_v20, '2.0', '2.0')
    @validation.schema(schema.update, '2.1', '2.18')
    @validation.schema(schema.update_v219, '2.19', '2.89')
    @validation.schema(schema.update_v290, '2.90', '2.93')
    @validation.schema(schema.update_v294, '2.94')
    @validation.response_body_schema(schema.update_response, '2.0', '2.8')
    @validation.response_body_schema(schema.update_response_v29, '2.9', '2.18')
    @validation.response_body_schema(schema.update_response_v219, '2.19', '2.25')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v226, '2.26', '2.46')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v247, '2.47', '2.62')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v263, '2.63', '2.70')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v271, '2.71', '2.72')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v273, '2.73', '2.74')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v275, '2.75', '2.95')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v296, '2.96', '2.97')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v298, '2.98', '2.99')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v2100, '2.100')
    def update(self, req, id, body):
        return super().update(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(204)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('confirmResize')
    @validation.schema(schema.confirm_resize)
    @validation.response_body_schema(schema.confirm_resize_response)
    def _confirm_resize(self, req, id, body):
        return super()._confirm_resize(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('revertResize')
    @validation.schema(schema.revert_resize)
    @validation.response_body_schema(schema.revert_resize_response)
    def _revert_resize(self, req, id, body):
        return super()._revert_resize(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('reboot')
    @validation.schema(schema.reboot)
    @validation.response_body_schema(schema.reboot_response)
    def _reboot(self, req, id, body):
        return super()._reboot(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 401, 403, 404, 409))
    @wsgi.action('resize')
    @validation.schema(schema.resize)
    @validation.response_body_schema(schema.resize_response)
    def _resize(self, req, id, body):
        return super()._resize(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('rebuild')
    @validation.schema(schema.rebuild_v20, '2.0', '2.0')
    @validation.schema(schema.rebuild, '2.1', '2.18')
    @validation.schema(schema.rebuild_v219, '2.19', '2.53')
    @validation.schema(schema.rebuild_v254, '2.54', '2.56')
    @validation.schema(schema.rebuild_v257, '2.57', '2.62')
    @validation.schema(schema.rebuild_v263, '2.63', '2.89')
    @validation.schema(schema.rebuild_v290, '2.90', '2.93')
    @validation.schema(schema.rebuild_v294, '2.94')
    @validation.response_body_schema(schema.rebuild_response, '2.0', '2.8')
    @validation.response_body_schema(schema.rebuild_response_v29, '2.9', '2.18')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v219, '2.19', '2.25')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v226, '2.26', '2.46')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v247, '2.47', '2.53')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v254, '2.54', '2.56')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v257, '2.57', '2.62')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v263, '2.63', '2.70')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v271, '2.71', '2.72')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v273, '2.73', '2.74')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v275, '2.75', '2.95')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v296, '2.96', '2.97')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v298, '2.98', '2.99')  # noqa: E501
    @validation.response_body_schema(schema.rebuild_response_v2100, '2.100')
    def _rebuild(self, req, id, body):
        return super()._rebuild(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('createImage')
    @validation.schema(schema.create_image, '2.0', '2.0')
    @validation.schema(schema.create_image, '2.1')
    @validation.response_body_schema(schema.create_image_response, '2.0', '2.44')  # noqa: E501
    @validation.response_body_schema(schema.create_image_response_v245, '2.45')
    def _create_image(self, req, id, body):
        return super()._create_image(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('os-start')
    @validation.schema(schema.start_server)
    @validation.response_body_schema(schema.start_server_response)
    def _start(self, req, id, body):
        return super()._start(req, id, body=body)

    @wsgi.api_version('2.1', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('os-stop')
    @validation.schema(schema.stop_server)
    @validation.response_body_schema(schema.stop_server_response)
    def _stop(self, req, id, body):
        return super()._stop(req, id, body=body)

    @wsgi.api_version('2.17', '2.102')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('trigger_crash_dump')
    @validation.schema(schema.trigger_crash_dump)
    @validation.response_body_schema(schema.trigger_crash_dump_response)
    def _trigger_crash_dump(self, req, id, body):
        return super()._trigger_crash_dump(req, id, body=body)
