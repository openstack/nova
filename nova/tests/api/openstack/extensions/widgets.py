from nova import wsgi

class WidgetController(wsgi.Controller):

    def index(self, req):
        return "Buy more widgets!"

class WidgetExtensionResource(object):

    def __init__(self):
        pass

    def add_routes(self, mapper):
        mapper.resource('widget', 'widgets', controller=WidgetController())


class WidgetExtension(object):

    def __init__(self):
        pass

    def get_resources(self):
        return WidgetExtensionResource()


def get_extension():
    return WidgetExtension()
