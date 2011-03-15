

def get_view_builder(req):
    '''
    A factory method that returns the correct builder based on the version of
    the api requested.
    '''
    version = req.environ['version']
    base_url = req.application_url
    if version == '1.1':
        return ViewBuilder_1_1(base_url)
    else:
        return ViewBuilder_1_0()


class ViewBuilder(object):
    def __init__(self):
        pass

    def build(self, flavor_obj):
        raise NotImplementedError()


class ViewBuilder_1_1(ViewBuilder):
    def __init__(self, base_url):
        self.base_url = base_url

    def generate_href(self, flavor_id):
        return "{0}/flavors/{1}".format(self.base_url, flavor_id)


class ViewBuilder_1_0(ViewBuilder):
    pass
