# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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
Base Key and SymmetricKey Classes

This module defines the Key and SymmetricKey classes. The Key class is the base
class to represent all encryption keys. The basis for this class was copied
from Java.
"""

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class Key(object):
    """Base class to represent all keys."""

    @abc.abstractmethod
    def get_algorithm(self):
        """Returns the key's algorithm.

        Returns the key's algorithm. For example, "DSA" indicates that this key
        is a DSA key and "AES" indicates that this key is an AES key.
        """
        pass

    @abc.abstractmethod
    def get_format(self):
        """Returns the encoding format.

        Returns the key's encoding format or None if this key is not encoded.
        """
        pass

    @abc.abstractmethod
    def get_encoded(self):
        """Returns the key in the format specified by its encoding."""
        pass


class SymmetricKey(Key):
    """This class represents symmetric keys."""

    def __init__(self, alg, key):
        """Create a new SymmetricKey object.

        The arguments specify the algorithm for the symmetric encryption and
        the bytes for the key.
        """
        self.alg = alg
        self.key = key

    def get_algorithm(self):
        """Returns the algorithm for symmetric encryption."""
        return self.alg

    def get_format(self):
        """This method returns 'RAW'."""
        return "RAW"

    def get_encoded(self):
        """Returns the key in its encoded format."""
        return self.key

    def __eq__(self, other):
        if isinstance(other, SymmetricKey):
            return (self.alg == other.alg and
                    self.key == other.key)
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result
