
'''
Utility methods for working with WSGI servers
'''

class Util(object):

    @staticmethod
    def route(reqstr, controllers):
        if len(reqstr) == 0:
            return Util.select_root_controller(controllers), []
        parts = [x for x in reqstr.split("/") if len(x) > 0]
        if len(parts) == 0:
            return Util.select_root_controller(controllers), []
        return controllers[parts[0]], parts[1:]

    @staticmethod
    def select_root_controller(controllers):
        if '' in controllers:
            return controllers['']
        else:
            return None

