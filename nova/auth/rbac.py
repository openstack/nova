from nova import exception
from nova.auth import users


def allow(*roles):
    def wrap(f):
        def wrapped_f(self, context, *args, **kwargs):
            if context.user.is_superuser():
                return f(self, context, *args, **kwargs)
            for role in roles:
                if __matches_role(context, role):
                    return f(self, context, *args, **kwargs)
            raise exception.NotAuthorized()
        return wrapped_f
    return wrap

def deny(*roles):
    def wrap(f):
        def wrapped_f(self, context, *args, **kwargs):
            if context.user.is_superuser():
                return f(self, context, *args, **kwargs)
            for role in roles:
                if __matches_role(context, role):
                    raise exception.NotAuthorized()
            return f(self, context, *args, **kwargs)
        return wrapped_f
    return wrap

def __matches_role(context, role):
    if role == 'all':
        return True
    if role == 'none':
        return False
    return context.project.has_role(context.user.id, role)

