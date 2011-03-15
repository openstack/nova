import hashlib
from nova.compute import power_state
from nova import utils


def get_view_builder(req):
    '''
    A factory method that returns the correct builder based on the version of
    the api requested.
    '''
    version = req.environ['nova.context'].version
    if version == '1.1':
        return ViewBuilder_1_1()
    else:
        return ViewBuilder_1_0()


class ViewBuilder(object):
    ''' Models a server addresses response as a python dictionary.'''

    def build(self, inst):
        raise NotImplementedError()


class ViewBuilder_1_0(ViewBuilder):
    def build(self, inst):
        private_ips = utils.get_from_path(inst, 'fixed_ip/address')
        public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
        return dict(public=public_ips, private=private_ips)


class ViewBuilder_1_1(ViewBuilder):
    def build(self, inst):
        private_ips = utils.get_from_path(inst, 'fixed_ip/address')
        private_ips = [dict(version=4, addr=a) for a in private_ips]
        public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
        public_ips = [dict(version=4, addr=a) for a in public_ips]
        return dict(public=public_ips, private=private_ips)
