"""
Convert between bytestreams and higher-level AMQP types.

2007-11-05 Barry Pederson <bp@barryp.org>

"""
# Copyright (C) 2007 Barry Pederson <bp@barryp.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301

import string
from datetime import datetime
from decimal import Decimal
from struct import pack, unpack
from time import mktime

try:
    from cStringIO import StringIO
except:
    from StringIO import StringIO


DUMP_CHARS = string.letters + string.digits + string.punctuation

def _hexdump(s):
    """
    Present just for debugging help.

    """
    while s:
        x, s = s[:16], s[16:]

        hex = ['%02x' % ord(ch) for ch in x]
        hex = ' '.join(hex).ljust(50)

        char_dump = []
        for ch in x:
            if ch in DUMP_CHARS:
                char_dump.append(ch)
            else:
                char_dump.append('.')

        print hex + ''.join(char_dump)


class AMQPReader(object):
    """
    Read higher-level AMQP types from a bytestream.

    """
    def __init__(self, source):
        """
        Source should be either a file-like object with a read() method, or
        a plain (non-unicode) string.

        """
        if isinstance(source, str):
            self.input = StringIO(source)
        elif hasattr(source, 'read'):
            self.input = source
        else:
            raise ValueError('AMQPReader needs a file-like object or plain string')

        self.bitcount = self.bits = 0


    def close(self):
        self.input.close()


    def read(self, n):
        """
        Read n bytes.

        """
        self.bitcount = self.bits = 0
        return self.input.read(n)


    def read_bit(self):
        """
        Read a single boolean value.

        """
        if not self.bitcount:
            self.bits = ord(self.input.read(1))
            self.bitcount = 8
        result = (self.bits & 1) == 1
        self.bits >>= 1
        self.bitcount -= 1
        return result


    def read_octet(self):
        """
        Read one byte, return as an integer

        """
        self.bitcount = self.bits = 0
        return unpack('B', self.input.read(1))[0]


    def read_short(self):
        """
        Read an unsigned 16-bit integer

        """
        self.bitcount = self.bits = 0
        return unpack('>H', self.input.read(2))[0]


    def read_long(self):
        """
        Read an unsigned 32-bit integer

        """
        self.bitcount = self.bits = 0
        return unpack('>I', self.input.read(4))[0]


    def read_longlong(self):
        """
        Read an unsigned 64-bit integer

        """
        self.bitcount = self.bits = 0
        return unpack('>Q', self.input.read(8))[0]


    def read_shortstr(self):
        """
        Read a utf-8 encoded string that's stored in up to
        255 bytes.  Return it decoded as a Python unicode object.

        """
        self.bitcount = self.bits = 0
        slen = unpack('B', self.input.read(1))[0]
        return self.input.read(slen).decode('utf-8')


    def read_longstr(self):
        """
        Read a string that's up to 2**32 bytes, the encoding
        isn't specified in the AMQP spec, so just return it as
        a plain Python string.

        """
        self.bitcount = self.bits = 0
        slen = unpack('>I', self.input.read(4))[0]
        return self.input.read(slen)


    def read_table(self):
        """
        Read an AMQP table, and return as a Python dictionary.

        """
        self.bitcount = self.bits = 0
        tlen = unpack('>I', self.input.read(4))[0]
        table_data = AMQPReader(self.input.read(tlen))
        result = {}
        while table_data.input.tell() < tlen:
            name = table_data.read_shortstr()
            ftype = table_data.input.read(1)
            if ftype == 'S':
                val = table_data.read_longstr()
            elif ftype == 'I':
                val = unpack('>i', table_data.input.read(4))[0]
            elif ftype == 'D':
                d = table_data.read_octet()
                n = unpack('>i', table_data.input.read(4))[0]
                val = Decimal(n) / Decimal(10 ** d)
            elif ftype == 'T':
                val = table_data.read_timestamp()
            elif ftype == 'F':
                val = table_data.read_table() # recurse
            result[name] = val
        return result


    def read_timestamp(self):
        """
        Read and AMQP timestamp, which is a 64-bit integer representing
        seconds since the Unix epoch in 1-second resolution.  Return as
        a Python datetime.datetime object, expressed as localtime.

        """
        return datetime.fromtimestamp(self.read_longlong())


class AMQPWriter(object):
    """
    Convert higher-level AMQP types to bytestreams.

    """
    def __init__(self, dest=None):
        """
        dest may be a file-type object (with a write() method).  If None
        then a StringIO is created, and the contents can be accessed with
        this class's getvalue() method.

        """
        if dest is None:
            self.out = StringIO()
        else:
            self.out = dest

        self.bits = []
        self.bitcount = 0


    def _flushbits(self):
        if self.bits:
            for b in self.bits:
                self.out.write(pack('B', b))
            self.bits = []
            self.bitcount = 0


    def close(self):
        """
        Pass through if possible to any file-like destinations.

        """
        if hasattr(self.out, 'close'):
            self.out.close()


    def flush(self):
        """
        Pass through if possible to any file-like destinations.

        """
        if hasattr(self.out, 'flush'):
            self.out.flush()


    def getvalue(self):
        """
        Get what's been encoded so far if we're working with a StringIO.

        """
        self._flushbits()
        return self.out.getvalue()


    def write(self, s):
        """
        Write a plain Python string, with no special encoding.

        """
        self._flushbits()
        self.out.write(s)


    def write_bit(self, b):
        """
        Write a boolean value.

        """
        if b:
            b = 1
        else:
            b = 0
        shift = self.bitcount % 8
        if shift == 0:
            self.bits.append(0)
        self.bits[-1] |= (b << shift)
        self.bitcount += 1


    def write_octet(self, n):
        """
        Write an integer as an unsigned 8-bit value.

        """
        if (n < 0) or (n > 255):
            raise ValueError('Octet out of range 0..255')
        self._flushbits()
        self.out.write(pack('B', n))


    def write_short(self, n):
        """
        Write an integer as an unsigned 16-bit value.

        """
        if (n < 0) or (n > 65535):
            raise ValueError('Octet out of range 0..65535')
        self._flushbits()
        self.out.write(pack('>H', n))


    def write_long(self, n):
        """
        Write an integer as an unsigned2 32-bit value.

        """
        if (n < 0) or (n >= (2**32)):
            raise ValueError('Octet out of range 0..2**31-1')
        self._flushbits()
        self.out.write(pack('>I', n))


    def write_longlong(self, n):
        """
        Write an integer as an unsigned 64-bit value.

        """
        if (n < 0) or (n >= (2**64)):
            raise ValueError('Octet out of range 0..2**64-1')
        self._flushbits()
        self.out.write(pack('>Q', n))


    def write_shortstr(self, s):
        """
        Write a string up to 255 bytes long after encoding.  If passed
        a unicode string, encode as UTF-8.

        """
        self._flushbits()
        if isinstance(s, unicode):
            s = s.encode('utf-8')
        if len(s) > 255:
            raise ValueError('String too long')
        self.write_octet(len(s))
        self.out.write(s)


    def write_longstr(self, s):
        """
        Write a string up to 2**32 bytes long after encoding.  If passed
        a unicode string, encode as UTF-8.

        """
        self._flushbits()
        if isinstance(s, unicode):
            s = s.encode('utf-8')
        self.write_long(len(s))
        self.out.write(s)


    def write_table(self, d):
        """
        Write out a Python dictionary made of up string keys, and values
        that are strings, signed integers, Decimal, datetime.datetime, or
        sub-dictionaries following the same constraints.

        """
        self._flushbits()
        table_data = AMQPWriter()
        for k, v in d.items():
            table_data.write_shortstr(k)
            if isinstance(v, basestring):
                if isinstance(v, unicode):
                    v = v.encode('utf-8')
                table_data.write('S')
                table_data.write_longstr(v)
            elif isinstance(v, (int, long)):
                table_data.write('I')
                table_data.write(pack('>i', v))
            elif isinstance(v, Decimal):
                table_data.write('D')
                sign, digits, exponent = v.as_tuple()
                v = 0
                for d in digits:
                    v = (v * 10) + d
                if sign:
                    v = -v
                table_data.write_octet(-exponent)
                table_data.write(pack('>i', v))
            elif isinstance(v, datetime):
                table_data.write('T')
                table_data.write_timestamp(v)
                ## FIXME: timezone ?
            elif isinstance(v, dict):
                table_data.write('F')
                table_data.write_table(v)
        table_data = table_data.getvalue()
        self.write_long(len(table_data))
        self.out.write(table_data)


    def write_timestamp(self, v):
        """
        Write out a Python datetime.datetime object as a 64-bit integer
        representing seconds since the Unix epoch.

        """
        self.out.write(pack('>q', long(mktime(v.timetuple()))))


class GenericContent(object):
    """
    Abstract base class for AMQP content.  Subclasses should
    override the PROPERTIES attribute.

    """
    PROPERTIES = [
        ('dummy', 'shortstr'),
        ]

    def __init__(self, **props):
        """
        Save the properties appropriate to this AMQP content type
        in a 'properties' dictionary.

        """
        d = {}
        for propname, _ in self.PROPERTIES:
            if propname in props:
                d[propname] = props[propname]
            # FIXME: should we ignore unknown properties?

        self.properties = d


    def __eq__(self, other):
        """
        Check if this object has the same properties as another
        content object.

        """
        return (self.properties == other.properties)


    def __getattr__(self, name):
        """
        Look for additional properties in the 'properties'
        dictionary, and if present - the 'delivery_info'
        dictionary.

        """
        if name in self.properties:
            return self.properties[name]

        if ('delivery_info' in self.__dict__) \
        and (name in self.delivery_info):
            return self.delivery_info[name]

        raise AttributeError(name)


    def __ne__(self, other):
        """
        Just return the opposite of __eq__

        """
        return not self.__eq__(other)


    def _load_properties(self, raw_bytes):
        """
        Given the raw bytes containing the property-flags and property-list
        from a content-frame-header, parse and insert into a dictionary
        stored in this object as an attribute named 'properties'.

        """
        r = AMQPReader(raw_bytes)

        #
        # Read 16-bit shorts until we get one with a low bit set to zero
        #
        flags = []
        while True:
            flag_bits = r.read_short()
            flags.append(flag_bits)
            if flag_bits & 1 == 0:
                break

        shift = 0
        d = {}
        for key, proptype in self.PROPERTIES:
            if shift == 0:
                if not flags:
                    break
                flag_bits, flags = flags[0], flags[1:]
                shift = 15
            if flag_bits & (1 << shift):
                d[key] = getattr(r, 'read_' + proptype)()
            shift -= 1

        self.properties = d


    def _serialize_properties(self):
        """
        serialize the 'properties' attribute (a dictionary) into
        the raw bytes making up a set of property flags and a
        property list, suitable for putting into a content frame header.

        """
        shift = 15
        flag_bits = 0
        flags = []
        raw_bytes = AMQPWriter()
        for key, proptype in self.PROPERTIES:
            val = self.properties.get(key, None)
            if val is not None:
                if shift == 0:
                    flags.append(flag_bits)
                    flag_bits = 0
                    shift = 15

                flag_bits |= (1 << shift)
                if proptype != 'bit':
                    getattr(raw_bytes, 'write_' + proptype)(val)

            shift -= 1

        flags.append(flag_bits)
        result = AMQPWriter()
        for flag_bits in flags:
            result.write_short(flag_bits)
        result.write(raw_bytes.getvalue())

        return result.getvalue()
