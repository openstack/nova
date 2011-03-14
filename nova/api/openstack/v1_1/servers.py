from nova import utils

def build_addresses(inst):
    private_ips = utils.get_from_path(inst, 'fixed_ip/address')
    private_ips = [dict(version=4, addr=a) for a in private_ips]
    public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
    public_ips = [dict(version=4, addr=a) for a in public_ips]
    return dict(public=public_ips, private=private_ips)
