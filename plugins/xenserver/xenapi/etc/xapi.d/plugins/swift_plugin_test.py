import XenAPI
import cPickle as pickle
import swift
import uuid

session = XenAPI.Session('http://localhost')
session.login_with_password('root', 'Iz8-HXk7E0')
host, = session.xenapi.host.get_all()

args = [["a8d2a226-3102-4710-96ec-2bc872aaeb7f"],
         "/var/run/sr-mount/60c0f0a2-4a37-d740-124b-3a0af60100e9",
         'this_is_a_test_2']

kwargs = {
    'swift_enable_snet': False,
    'swift_store_user': 'nova-staging%3Anova-staging-acct',
    'swift_store_key': 'm5XWk8E',
    'swift_store_auth_version': '1',
    'swift_store_container': 'images',
    'swift_store_large_object_chunk_size': 65536,
    'swift_store_create_container_on_put': True,
    'full_auth_address': 'https://auth.dfw1.swift.racklabs.com:443/auth/v1.0',
    }

pickled = {'params': pickle.dumps(dict(args=args, kwargs=kwargs))}

'''try:
    print session.xenapi.host.call_plugin(host, 'swift', 'upload_vhd', pickled)
except Exception, e:
    print e'''

swift.upload_vhd(None, *args, **kwargs)
