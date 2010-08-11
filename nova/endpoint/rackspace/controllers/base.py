class BaseController(object):
    @classmethod
    def render(cls, instance):
        if isinstance(instance, list):
            return [ cls.entity_name : { cls.render(instance) }
        else
            return 
        
        
