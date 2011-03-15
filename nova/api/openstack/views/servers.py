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
        return DataViewBuilder_1_1()
    else:
        return DataViewBuilder_1_0()


class DataViewBuilder(object):
    ''' Models a server response as a python dictionary. '''

    def build(self, inst, is_detail):
        """ Coerces into dictionary format, mapping everything to Rackspace-like
        attributes for return"""

        if not is_detail:
            return dict(server=dict(id=inst['id'], name=inst['display_name']))

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
        inst_dict['addresses'] = self._build_addresses(inst)

        # Return the metadata as a dictionary
        metadata = {}
        for item in inst['metadata']:
            metadata[item['key']] = item['value']
        inst_dict['metadata'] = metadata

        inst_dict['hostId'] = ''
        if inst['host']:
            inst_dict['hostId'] = hashlib.sha224(inst['host']).hexdigest()

        return dict(server=inst_dict)


class DataViewBuilder_1_0(DataViewBuilder):
    def _build_addresses(self, inst):
        private_ips = utils.get_from_path(inst, 'fixed_ip/address')
        public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
        return dict(public=public_ips, private=private_ips)


class DataViewBuilder_1_1(DataViewBuilder):
    def _build_addresses(self, inst):
        private_ips = utils.get_from_path(inst, 'fixed_ip/address')
        private_ips = [dict(version=4, addr=a) for a in private_ips]
        public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
        public_ips = [dict(version=4, addr=a) for a in public_ips]
        return dict(public=public_ips, private=private_ips)

