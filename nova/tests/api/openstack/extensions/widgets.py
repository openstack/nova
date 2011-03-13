from nova import wsgi

class WidgetsController(wsgi.Controller):

    def index(self, req):
        return "Buy more widgets!"

class WidgetsExtensionResource(object):

    def __init__(self):
        pass

    def add_routes(self, mapper):
        mapper.resource('widget', 'widgets', controller=WidgetsController())


class WidgetsExtension(object):

    def __init__(self):
        pass

    def get_resources(self):
        return WidgetsExtensionResource()
