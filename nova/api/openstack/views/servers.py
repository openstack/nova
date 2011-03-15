import hashlib
from nova.compute import power_state
from nova.api.openstack.views import addresses as addresses_view
from nova import utils


def get_view_builder(req):
    '''
    A factory method that returns the correct builder based on the version of
    the api requested.
    '''
    version = req.environ['nova.context'].version
    addresses_builder = addresses_view.get_view_builder(req)
    if version == '1.1':
        return ViewBuilder_1_1(addresses_builder)
    else:
        return ViewBuilder_1_0(addresses_builder)


class ViewBuilder(object):
    ''' Models a server response as a python dictionary.'''

    def __init__(self, addresses_builder):
        self.addresses_builder = addresses_builder

    def build(self, inst, is_detail):
        """ Coerces into dictionary format, mapping everything to Rackspace-like
        attributes for return"""
        if is_detail:
            return self._build_detail(inst)
        else:
            return self._build_simple(inst)

    def _build_simple(self, inst):
            return dict(server=dict(id=inst['id'], name=inst['display_name']))

    def _build_detail(self, inst):
        power_mapping = {
            None: 'build',
            power_state.NOSTATE: 'build',
            power_state.RUNNING: 'active',
            power_state.BLOCKED: 'active',
            power_state.SUSPENDED: 'suspended',
            power_state.PAUSED: 'paused',
            power_state.SHUTDOWN: 'active',
            power_state.SHUTOFF: 'active',
            power_state.CRASHED: 'error',
            power_state.FAILED: 'error'}
        inst_dict = {}

        mapped_keys = dict(status='state', imageId='image_id',
            flavorId='instance_type', name='display_name', id='id')

        for k, v in mapped_keys.iteritems():
            inst_dict[k] = inst[v]

        inst_dict['status'] = power_mapping[inst_dict['status']]
        inst_dict['addresses'] = self.addresses_builder.build(inst)

        # Return the metadata as a dictionary
        metadata = {}
        for item in inst['metadata']:
            metadata[item['key']] = item['value']
        inst_dict['metadata'] = metadata

        inst_dict['hostId'] = ''
        if inst['host']:
            inst_dict['hostId'] = hashlib.sha224(inst['host']).hexdigest()

        return dict(server=inst_dict)


class ViewBuilder_1_0(ViewBuilder):
    pass


class ViewBuilder_1_1(ViewBuilder):
    pass

