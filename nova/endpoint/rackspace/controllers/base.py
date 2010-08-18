from nova import wsgi

class BaseController(wsgi.Controller):
    @classmethod
    def render(cls, instance):
        if isinstance(instance, list):
            return { cls.entity_name : cls.render(instance) }
        else:
            return { "TODO": "TODO" }
    
    def serialize(self, data, request):
        """
        Serialize the given dict to the response type requested in request.
        Uses self._serialization_metadata if it exists, which is a dict mapping
        MIME types to information needed to serialize to that type.
        """
        _metadata = getattr(type(self), "_serialization_metadata", {})
        return Serializer(request.environ, _metadata).to_content_type(data)
