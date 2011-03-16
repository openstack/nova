import os

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


def binpath(script):
    """Returns the absolute path to a script in bin"""
    return os.path.abspath(os.path.join(__file__, "../../../../bin", script))


def lease_ip(private_ip):
    """Run add command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(context.get_admin_context(),
                                          private_ip)
    instance_ref = db.fixed_ip_get_instance(context.get_admin_context(),
                                            private_ip)
    cmd = (binpath('nova-dhcpbridge'), 'add',
           instance_ref['mac_address'],
           private_ip, 'fake')
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(*cmd, addl_env=env)
    LOG.debug("ISSUE_IP: %s, %s ", out, err)


def release_ip(private_ip):
    """Run del command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(context.get_admin_context(),
                                          private_ip)
    instance_ref = db.fixed_ip_get_instance(context.get_admin_context(),
                                            private_ip)
    cmd = (binpath('nova-dhcpbridge'), 'del',
           instance_ref['mac_address'],
           private_ip, 'fake')
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(*cmd, addl_env=env)
    LOG.debug("RELEASE_IP: %s, %s ", out, err)
