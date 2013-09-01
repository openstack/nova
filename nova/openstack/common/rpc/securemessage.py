# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import collections
import os
import struct
import time

import requests

from oslo.config import cfg

from nova.openstack.common.crypto import utils as cryptoutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging

secure_message_opts = [
    cfg.BoolOpt('enabled', default=True,
                help='Whether Secure Messaging (Signing) is enabled,'
                     ' defaults to enabled'),
    cfg.BoolOpt('enforced', default=False,
                help='Whether Secure Messaging (Signing) is enforced,'
                     ' defaults to not enforced'),
    cfg.BoolOpt('encrypt', default=False,
                help='Whether Secure Messaging (Encryption) is enabled,'
                     ' defaults to not enabled'),
    cfg.StrOpt('secret_keys_file',
               help='Path to the file containing the keys, takes precedence'
                    ' over secret_key'),
    cfg.MultiStrOpt('secret_key',
                    help='A list of keys: (ex: name:<base64 encoded key>),'
                         ' ignored if secret_keys_file is set'),
    cfg.StrOpt('kds_endpoint',
               help='KDS endpoint (ex: http://kds.example.com:35357/v3)'),
]
secure_message_group = cfg.OptGroup('secure_messages',
                                    title='Secure Messaging options')

LOG = logging.getLogger(__name__)


class SecureMessageException(Exception):
    """Generic Exception for Secure Messages."""

    msg = "An unknown Secure Message related exception occurred."

    def __init__(self, msg=None):
        if msg is None:
            msg = self.msg
        super(SecureMessageException, self).__init__(msg)


class SharedKeyNotFound(SecureMessageException):
    """No shared key was found and no other external authentication mechanism
    is available.
    """

    msg = "Shared Key for [%s] Not Found. (%s)"

    def __init__(self, name, errmsg):
        super(SharedKeyNotFound, self).__init__(self.msg % (name, errmsg))


class InvalidMetadata(SecureMessageException):
    """The metadata is invalid."""

    msg = "Invalid metadata: %s"

    def __init__(self, err):
        super(InvalidMetadata, self).__init__(self.msg % err)


class InvalidSignature(SecureMessageException):
    """Signature validation failed."""

    msg = "Failed to validate signature (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidSignature, self).__init__(self.msg % (src, dst))


class UnknownDestinationName(SecureMessageException):
    """The Destination name is unknown to us."""

    msg = "Invalid destination name (%s)"

    def __init__(self, name):
        super(UnknownDestinationName, self).__init__(self.msg % name)


class InvalidEncryptedTicket(SecureMessageException):
    """The Encrypted Ticket could not be successfully handled."""

    msg = "Invalid Ticket (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidEncryptedTicket, self).__init__(self.msg % (src, dst))


class InvalidExpiredTicket(SecureMessageException):
    """The ticket received is already expired."""

    msg = "Expired ticket (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidExpiredTicket, self).__init__(self.msg % (src, dst))


class CommunicationError(SecureMessageException):
    """The Communication with the KDS failed."""

    msg = "Communication Error (target=%s): %s"

    def __init__(self, target, errmsg):
        super(CommunicationError, self).__init__(self.msg % (target, errmsg))


class InvalidArgument(SecureMessageException):
    """Bad initialization argument."""

    msg = "Invalid argument: %s"

    def __init__(self, errmsg):
        super(InvalidArgument, self).__init__(self.msg % errmsg)


Ticket = collections.namedtuple('Ticket', ['skey', 'ekey', 'esek'])


class KeyStore(object):
    """A storage class for Signing and Encryption Keys.

    This class creates an object that holds Generic Keys like Signing
    Keys, Encryption Keys, Encrypted SEK Tickets ...
    """

    def __init__(self):
        self._kvps = dict()

    def _get_key_name(self, source, target, ktype):
        return (source, target, ktype)

    def _put(self, src, dst, ktype, expiration, data):
        name = self._get_key_name(src, dst, ktype)
        self._kvps[name] = (expiration, data)

    def _get(self, src, dst, ktype):
        name = self._get_key_name(src, dst, ktype)
        if name in self._kvps:
            expiration, data = self._kvps[name]
            if expiration > time.time():
                return data
            else:
                del self._kvps[name]

        return None

    def clear(self):
        """Wipes the store clear of all data."""
        self._kvps.clear()

    def put_ticket(self, source, target, skey, ekey, esek, expiration):
        """Puts a sek pair in the cache.

        :param source: Client name
        :param target: Target name
        :param skey: The Signing Key
        :param ekey: The Encription Key
        :param esek: The token encrypted with the target key
        :param expiration: Expiration time in seconds since Epoch
        """
        keys = Ticket(skey, ekey, esek)
        self._put(source, target, 'ticket', expiration, keys)

    def get_ticket(self, source, target):
        """Returns a Ticket (skey, ekey, esek) namedtuple for the
           source/target pair.
        """
        return self._get(source, target, 'ticket')


_KEY_STORE = KeyStore()


class _KDSClient(object):

    USER_AGENT = 'oslo-incubator/rpc'

    def __init__(self, endpoint=None, timeout=None):
        """A KDS Client class."""

        self._endpoint = endpoint
        if timeout is not None:
            self.timeout = float(timeout)
        else:
            self.timeout = None

    def _do_get(self, url, request):
        req_kwargs = dict()
        req_kwargs['headers'] = dict()
        req_kwargs['headers']['User-Agent'] = self.USER_AGENT
        req_kwargs['headers']['Content-Type'] = 'application/json'
        req_kwargs['data'] = jsonutils.dumps({'request': request})
        if self.timeout is not None:
            req_kwargs['timeout'] = self.timeout

        try:
            resp = requests.get(url, **req_kwargs)
        except requests.ConnectionError as e:
            err = "Unable to establish connection. %s" % e
            raise CommunicationError(url, err)

        return resp

    def _get_reply(self, url, resp):
        if resp.text:
            try:
                body = jsonutils.loads(resp.text)
                reply = body['reply']
            except (KeyError, TypeError, ValueError):
                msg = "Failed to decode reply: %s" % resp.text
                raise CommunicationError(url, msg)
        else:
            msg = "No reply data was returned."
            raise CommunicationError(url, msg)

        return reply

    def _get_ticket(self, request, url=None, redirects=10):
        """Send an HTTP request.

        Wraps around 'requests' to handle redirects and common errors.
        """
        if url is None:
            if not self._endpoint:
                raise CommunicationError(url, 'Endpoint not configured')
            url = self._endpoint + '/kds/ticket'

        while redirects:
            resp = self._do_get(url, request)
            if resp.status_code in (301, 302, 305):
                # Redirected. Reissue the request to the new location.
                url = resp.headers['location']
                redirects -= 1
                continue
            elif resp.status_code != 200:
                msg = "Request returned failure status: %s (%s)"
                err = msg % (resp.status_code, resp.text)
                raise CommunicationError(url, err)

            return self._get_reply(url, resp)

        raise CommunicationError(url, "Too many redirections, giving up!")

    def get_ticket(self, source, target, crypto, key):

        # prepare metadata
        md = {'requestor': source,
              'target': target,
              'timestamp': time.time(),
              'nonce': struct.unpack('Q', os.urandom(8))[0]}
        metadata = base64.b64encode(jsonutils.dumps(md))

        # sign metadata
        signature = crypto.sign(key, metadata)

        # HTTP request
        reply = self._get_ticket({'metadata': metadata,
                                  'signature': signature})

        # verify reply
        signature = crypto.sign(key, (reply['metadata'] + reply['ticket']))
        if signature != reply['signature']:
            raise InvalidEncryptedTicket(md['source'], md['destination'])
        md = jsonutils.loads(base64.b64decode(reply['metadata']))
        if ((md['source'] != source or
             md['destination'] != target or
             md['expiration'] < time.time())):
            raise InvalidEncryptedTicket(md['source'], md['destination'])

        # return ticket data
        tkt = jsonutils.loads(crypto.decrypt(key, reply['ticket']))

        return tkt, md['expiration']


# we need to keep a global nonce, as this value should never repeat non
# matter how many SecureMessage objects we create
_NONCE = None


def _get_nonce():
    """We keep a single counter per instance, as it is so huge we can't
    possibly cycle through within 1/100 of a second anyway.
    """

    global _NONCE
    # Lazy initialize, for now get a random value, multiply by 2^32 and
    # use it as the nonce base. The counter itself will rotate after
    # 2^32 increments.
    if _NONCE is None:
        _NONCE = [struct.unpack('I', os.urandom(4))[0], 0]

    # Increment counter and wrap at 2^32
    _NONCE[1] += 1
    if _NONCE[1] > 0xffffffff:
        _NONCE[1] = 0

    # Return base + counter
    return long((_NONCE[0] * 0xffffffff)) + _NONCE[1]


class SecureMessage(object):
    """A Secure Message object.

    This class creates a signing/encryption facility for RPC messages.
    It encapsulates all the necessary crypto primitives to insulate
    regular code from the intricacies of message authentication, validation
    and optionally encryption.

    :param topic: The topic name of the queue
    :param host: The server name, together with the topic it forms a unique
                 name that is used to source signing keys, and verify
                 incoming messages.
    :param conf: a ConfigOpts object
    :param key: (optional) explicitly pass in endpoint private key.
                  If not provided it will be sourced from the service config
    :param key_store: (optional) Storage class for local caching
    :param encrypt: (defaults to False) Whether to encrypt messages
    :param enctype: (defaults to AES) Cipher to use
    :param hashtype: (defaults to SHA256) Hash function to use for signatures
    """

    def __init__(self, topic, host, conf, key=None, key_store=None,
                 encrypt=None, enctype='AES', hashtype='SHA256'):

        conf.register_group(secure_message_group)
        conf.register_opts(secure_message_opts, group='secure_messages')

        self._name = '%s.%s' % (topic, host)
        self._key = key
        self._conf = conf.secure_messages
        self._encrypt = self._conf.encrypt if (encrypt is None) else encrypt
        self._crypto = cryptoutils.SymmetricCrypto(enctype, hashtype)
        self._hkdf = cryptoutils.HKDF(hashtype)
        self._kds = _KDSClient(self._conf.kds_endpoint)

        if self._key is None:
            self._key = self._init_key(topic, self._name)
        if self._key is None:
            err = "Secret Key (or key file) is missing or malformed"
            raise SharedKeyNotFound(self._name, err)

        self._key_store = key_store or _KEY_STORE

    def _init_key(self, topic, name):
        keys = None
        if self._conf.secret_keys_file:
            with open(self._conf.secret_keys_file, 'r') as f:
                keys = f.readlines()
        elif self._conf.secret_key:
            keys = self._conf.secret_key

        if keys is None:
            return None

        for k in keys:
            if k[0] == '#':
                continue
            if ':' not in k:
                break
            svc, key = k.split(':', 1)
            if svc == topic or svc == name:
                return base64.b64decode(key)

        return None

    def _split_key(self, key, size):
        sig_key = key[:size]
        enc_key = key[size:]
        return sig_key, enc_key

    def _decode_esek(self, key, source, target, timestamp, esek):
        """This function decrypts the esek buffer passed in and returns a
        KeyStore to be used to check and decrypt the received message.

        :param key: The key to use to decrypt the ticket (esek)
        :param source: The name of the source service
        :param traget: The name of the target service
        :param timestamp: The incoming message timestamp
        :param esek: a base64 encoded encrypted block containing a JSON string
        """
        rkey = None

        try:
            s = self._crypto.decrypt(key, esek)
            j = jsonutils.loads(s)

            rkey = base64.b64decode(j['key'])
            expiration = j['timestamp'] + j['ttl']
            if j['timestamp'] > timestamp or timestamp > expiration:
                raise InvalidExpiredTicket(source, target)

        except Exception:
            raise InvalidEncryptedTicket(source, target)

        info = '%s,%s,%s' % (source, target, str(j['timestamp']))

        sek = self._hkdf.expand(rkey, info, len(key) * 2)

        return self._split_key(sek, len(key))

    def _get_ticket(self, target):
        """This function will check if we already have a SEK for the specified
        target in the cache, or will go and try to fetch a new SEK from the key
        server.

        :param target: The name of the target service
        """
        ticket = self._key_store.get_ticket(self._name, target)

        if ticket is not None:
            return ticket

        tkt, expiration = self._kds.get_ticket(self._name, target,
                                               self._crypto, self._key)

        self._key_store.put_ticket(self._name, target,
                                   base64.b64decode(tkt['skey']),
                                   base64.b64decode(tkt['ekey']),
                                   tkt['esek'], expiration)
        return self._key_store.get_ticket(self._name, target)

    def encode(self, version, target, json_msg):
        """This is the main encoding function.

        It takes a target and a message and returns a tuple consisting of a
        JSON serialized metadata object, a JSON serialized (and optionally
        encrypted) message, and a signature.

        :param version: the current envelope version
        :param target: The name of the target service (usually with hostname)
        :param json_msg: a serialized json message object
        """
        ticket = self._get_ticket(target)

        metadata = jsonutils.dumps({'source': self._name,
                                    'destination': target,
                                    'timestamp': time.time(),
                                    'nonce': _get_nonce(),
                                    'esek': ticket.esek,
                                    'encryption': self._encrypt})

        message = json_msg
        if self._encrypt:
            message = self._crypto.encrypt(ticket.ekey, message)

        signature = self._crypto.sign(ticket.skey,
                                      version + metadata + message)

        return (metadata, message, signature)

    def decode(self, version, metadata, message, signature):
        """This is the main decoding function.

        It takes a version, metadata, message and signature strings and
        returns a tuple with a (decrypted) message and metadata or raises
        an exception in case of error.

        :param version: the current envelope version
        :param metadata: a JSON serialized object with metadata for validation
        :param message: a JSON serialized (base64 encoded encrypted) message
        :param signature: a base64 encoded signature
        """
        md = jsonutils.loads(metadata)

        check_args = ('source', 'destination', 'timestamp',
                      'nonce', 'esek', 'encryption')
        for arg in check_args:
            if arg not in md:
                raise InvalidMetadata('Missing metadata "%s"' % arg)

        if md['destination'] != self._name:
            # TODO(simo) handle group keys by checking target
            raise UnknownDestinationName(md['destination'])

        try:
            skey, ekey = self._decode_esek(self._key,
                                           md['source'], md['destination'],
                                           md['timestamp'], md['esek'])
        except InvalidExpiredTicket:
            raise
        except Exception:
            raise InvalidMetadata('Failed to decode ESEK for %s/%s' % (
                                  md['source'], md['destination']))

        sig = self._crypto.sign(skey, version + metadata + message)

        if sig != signature:
            raise InvalidSignature(md['source'], md['destination'])

        if md['encryption'] is True:
            msg = self._crypto.decrypt(ekey, message)
        else:
            msg = message

        return (md, msg)
