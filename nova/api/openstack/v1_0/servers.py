from nova import utils

def build_addresses(inst):
    private_ips = utils.get_from_path(inst, 'fixed_ip/address')
    public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
    return dict(public=public_ips, private=private_ips)
