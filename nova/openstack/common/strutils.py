# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation.
# All Rights Reserved.
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

"""
System-level utilities and helper functions.
"""

import re
import sys
import unicodedata

import six

from nova.openstack.common.gettextutils import _


# Used for looking up extensions of text
# to their 'multiplied' byte amount
BYTE_MULTIPLIERS = {
    '': 1,
    't': 1024 ** 4,
    'g': 1024 ** 3,
    'm': 1024 ** 2,
    'k': 1024,
}
BYTE_REGEX = re.compile(r'(^-?\d+)(\D*)')

TRUE_STRINGS = ('1', 't', 'true', 'on', 'y', 'yes')
FALSE_STRINGS = ('0', 'f', 'false', 'off', 'n', 'no')

SLUGIFY_STRIP_RE = re.compile(r"[^\w\s-]")
SLUGIFY_HYPHENATE_RE = re.compile(r"[-\s]+")


# NOTE(flaper87): The following globals are used by `mask_password`
_SANITIZE_KEYS = ['adminPass', 'admin_pass', 'password', 'admin_password']

# NOTE(ldbragst): Let's build a list of regex objects using the list of
# _SANITIZE_KEYS we already have. This way, we only have to add the new key
# to the list of _SANITIZE_KEYS and we can generate regular expressions
# for XML and JSON automatically.
_SANITIZE_PATTERNS_2 = []
_SANITIZE_PATTERNS_1 = []

# NOTE(amrith): Some regular expressions have only one parameter, some
# have two parameters. Use different lists of patterns here.
_FORMAT_PATTERNS_1 = [r'(%(key)s\s*[=]\s*)[^\s^\'^\"]+']
_FORMAT_PATTERNS_2 = [r'(%(key)s\s*[=]\s*[\"\']).*?([\"\'])',
                      r'(%(key)s\s+[\"\']).*?([\"\'])',
                      r'([-]{2}%(key)s\s+)[^\'^\"^=^\s]+([\s]*)',
                      r'(<%(key)s>).*?(</%(key)s>)',
                      r'([\"\']%(key)s[\"\']\s*:\s*[\"\']).*?([\"\'])',
                      r'([\'"].*?%(key)s[\'"]\s*:\s*u?[\'"]).*?([\'"])',
                      r'([\'"].*?%(key)s[\'"]\s*,\s*\'--?[A-z]+\'\s*,\s*u?'
                      '[\'"]).*?([\'"])',
                      r'(%(key)s\s*--?[A-z]+\s*)\S+(\s*)']

for key in _SANITIZE_KEYS:
    for pattern in _FORMAT_PATTERNS_2:
        reg_ex = re.compile(pattern % {'key': key}, re.DOTALL)
        _SANITIZE_PATTERNS_2.append(reg_ex)

    for pattern in _FORMAT_PATTERNS_1:
        reg_ex = re.compile(pattern % {'key': key}, re.DOTALL)
        _SANITIZE_PATTERNS_1.append(reg_ex)


def int_from_bool_as_string(subject):
    """Interpret a string as a boolean and return either 1 or 0.

    Any string value in:

        ('True', 'true', 'On', 'on', '1')

    is interpreted as a boolean True.

    Useful for JSON-decoded stuff and config file parsing
    """
    return bool_from_string(subject) and 1 or 0


def bool_from_string(subject, strict=False):
    """Interpret a string as a boolean.

    A case-insensitive match is performed such that strings matching 't',
    'true', 'on', 'y', 'yes', or '1' are considered True and, when
    `strict=False`, anything else is considered False.

    Useful for JSON-decoded stuff and config file parsing.

    If `strict=True`, unrecognized values, including None, will raise a
    ValueError which is useful when parsing values passed in from an API call.
    Strings yielding False are 'f', 'false', 'off', 'n', 'no', or '0'.
    """
    if not isinstance(subject, basestring):
        subject = str(subject)

    lowered = subject.strip().lower()

    if lowered in TRUE_STRINGS:
        return True
    elif lowered in FALSE_STRINGS:
        return False
    elif strict:
        acceptable = ', '.join(
            "'%s'" % s for s in sorted(TRUE_STRINGS + FALSE_STRINGS))
        msg = _("Unrecognized value '%(val)s', acceptable values are:"
                " %(acceptable)s") % {'val': subject,
                                      'acceptable': acceptable}
        raise ValueError(msg)
    else:
        return False


def safe_decode(text, incoming=None, errors='strict'):
    """Decodes incoming str using `incoming` if they're not already unicode.

    :param incoming: Text's current encoding
    :param errors: Errors handling policy. See here for valid
        values http://docs.python.org/2/library/codecs.html
    :returns: text or a unicode `incoming` encoded
                representation of it.
    :raises TypeError: If text is not an isntance of basestring
    """
    if not isinstance(text, basestring):
        raise TypeError("%s can't be decoded" % type(text))

    if isinstance(text, unicode):
        return text

    if not incoming:
        incoming = (sys.stdin.encoding or
                    sys.getdefaultencoding())

    try:
        return text.decode(incoming, errors)
    except UnicodeDecodeError:
        # Note(flaper87) If we get here, it means that
        # sys.stdin.encoding / sys.getdefaultencoding
        # didn't return a suitable encoding to decode
        # text. This happens mostly when global LANG
        # var is not set correctly and there's no
        # default encoding. In this case, most likely
        # python will use ASCII or ANSI encoders as
        # default encodings but they won't be capable
        # of decoding non-ASCII characters.
        #
        # Also, UTF-8 is being used since it's an ASCII
        # extension.
        return text.decode('utf-8', errors)


def safe_encode(text, incoming=None,
                encoding='utf-8', errors='strict'):
    """Encodes incoming str/unicode using `encoding`.

    If incoming is not specified, text is expected to be encoded with
    current python's default encoding. (`sys.getdefaultencoding`)

    :param incoming: Text's current encoding
    :param encoding: Expected encoding for text (Default UTF-8)
    :param errors: Errors handling policy. See here for valid
        values http://docs.python.org/2/library/codecs.html
    :returns: text or a bytestring `encoding` encoded
                representation of it.
    :raises TypeError: If text is not an isntance of basestring
    """
    if not isinstance(text, basestring):
        raise TypeError("%s can't be encoded" % type(text))

    if not incoming:
        incoming = (sys.stdin.encoding or
                    sys.getdefaultencoding())

    if isinstance(text, unicode):
        return text.encode(encoding, errors)
    elif text and encoding != incoming:
        # Decode text before encoding it with `encoding`
        text = safe_decode(text, incoming, errors)
        return text.encode(encoding, errors)

    return text


def to_bytes(text, default=0):
    """Converts a string into an integer of bytes.

    Looks at the last characters of the text to determine
    what conversion is needed to turn the input text into a byte number.
    Supports "B, K(B), M(B), G(B), and T(B)". (case insensitive)

    :param text: String input for bytes size conversion.
    :param default: Default return value when text is blank.

    """
    match = BYTE_REGEX.search(text)
    if match:
        magnitude = int(match.group(1))
        mult_key_org = match.group(2)
        if not mult_key_org:
            return magnitude
    elif text:
        msg = _('Invalid string format: %s') % text
        raise TypeError(msg)
    else:
        return default
    mult_key = mult_key_org.lower().replace('b', '', 1)
    multiplier = BYTE_MULTIPLIERS.get(mult_key)
    if multiplier is None:
        msg = _('Unknown byte multiplier: %s') % mult_key_org
        raise TypeError(msg)
    return magnitude * multiplier


def to_slug(value, incoming=None, errors="strict"):
    """Normalize string.

    Convert to lowercase, remove non-word characters, and convert spaces
    to hyphens.

    Inspired by Django's `slugify` filter.

    :param value: Text to slugify
    :param incoming: Text's current encoding
    :param errors: Errors handling policy. See here for valid
        values http://docs.python.org/2/library/codecs.html
    :returns: slugified unicode representation of `value`
    :raises TypeError: If text is not an instance of basestring
    """
    value = safe_decode(value, incoming, errors)
    # NOTE(aababilov): no need to use safe_(encode|decode) here:
    # encodings are always "ascii", error handling is always "ignore"
    # and types are always known (first: unicode; second: str)
    value = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore").decode("ascii")
    value = SLUGIFY_STRIP_RE.sub("", value).strip().lower()
    return SLUGIFY_HYPHENATE_RE.sub("-", value)


def mask_password(message, secret="***"):
    """Replace password with 'secret' in message.

    :param message: The string which includes security information.
    :param secret: value with which to replace passwords.
    :returns: The unicode value of message with the password fields masked.

    For example:

    >>> mask_password("'adminPass' : 'aaaaa'")
    "'adminPass' : '***'"
    >>> mask_password("'admin_pass' : 'aaaaa'")
    "'admin_pass' : '***'"
    >>> mask_password('"password" : "aaaaa"')
    '"password" : "***"'
    >>> mask_password("'original_password' : 'aaaaa'")
    "'original_password' : '***'"
    >>> mask_password("u'original_password' :   u'aaaaa'")
    "u'original_password' :   u'***'"
    """
    message = six.text_type(message)

    # NOTE(ldbragst): Check to see if anything in message contains any key
    # specified in _SANITIZE_KEYS, if not then just return the message since
    # we don't have to mask any passwords.
    if not any(key in message for key in _SANITIZE_KEYS):
        return message

    substitute = r'\g<1>' + secret + r'\g<2>'
    for pattern in _SANITIZE_PATTERNS_2:
        message = re.sub(pattern, substitute, message)

    substitute = r'\g<1>' + secret
    for pattern in _SANITIZE_PATTERNS_1:
        message = re.sub(pattern, substitute, message)

    return message
