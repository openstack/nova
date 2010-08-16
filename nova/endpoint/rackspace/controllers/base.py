from nova import wsgi

class BaseController(wsgi.Controller):
    @classmethod
    def render(cls, instance):
        if isinstance(instance, list):
            return { cls.entity_name : cls.render(instance) }
        else:
            return { "TODO": "TODO" }
