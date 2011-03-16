import json

from nova import wsgi

from nova.api.openstack import extensions


class WidgetsController(wsgi.Controller):

    def index(self, req):
        return "Buy more widgets!"


class Widgets(object):

    def __init__(self):
        pass

    def get_resources(self):
        resources = []
        widgets = extensions.ResourceExtension('widgets',
                                               WidgetsController())
        resources.append(widgets)
        return resources

    def get_actions(self):
        actions = []
        actions.append(extensions.ActionExtension('servers', 'add_widget',
                                                    self._add_widget))
        actions.append(extensions.ActionExtension('servers', 'delete_widget',
                                                    self._delete_widget))
        return actions

    def get_response_extensions(self):
        response_exts = []

        def _resp_handler(res):
            # only handle JSON responses
            data = json.loads(res.body)
            data['flavor']['widgets'] = "Buy more widgets!"
            return data

        widgets = extensions.ResponseExtension('/v1.0/flavors/:(id)', 'GET',
                                                _resp_handler)
        response_exts.append(widgets)
        return response_exts

    def _add_widget(self, input_dict, req, id):

        return "Widget Added."

    def _delete_widget(self, input_dict, req, id):

        return "Widget Deleted."
