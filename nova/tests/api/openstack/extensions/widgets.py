from nova import wsgi

from nova.api.openstack import extensions


class WidgetsController(wsgi.Controller):

    def index(self, req):
        return "Buy more widgets!"


class WidgetsExtension(object):

    def __init__(self):
        pass

    def get_resources(self):
        resources = []
        widgets = extensions.ExtensionResource('widget', 'widgets',
                                               WidgetsController())
        resources.append(widgets)
        return resources

    def get_actions(self):
        actions = []
        actions.append(extensions.ExtensionAction('server', 'servers',
                                                    'add_widget',
                                                    self._add_widget))
        actions.append(extensions.ExtensionAction('server', 'servers',
                                                    'delete_widget',
                                                    self._delete_widget))
        return actions

    def _add_widget(self, input_dict, req, id):

        return "Widget Added."

    def _delete_widget(self, input_dict, req, id):

        return "Widget Deleted."
