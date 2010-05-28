"""
Exceptions used by amqplib.client_0_8

"""
# Copyright (C) 2007-2008 Barry Pederson <bp@barryp.org>
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


__all__ =  [
            'AMQPException',
            'AMQPConnectionException',
            'AMQPChannelException',
           ]


class AMQPException(Exception):
    def __init__(self, reply_code, reply_text, method_sig):
        Exception.__init__(self)
        self.amqp_reply_code = reply_code
        self.amqp_reply_text = reply_text
        self.amqp_method_sig = method_sig
        self.args = (
            reply_code,
            reply_text,
            method_sig,
            METHOD_NAME_MAP.get(method_sig, '')
            )


class AMQPConnectionException(AMQPException):
    pass


class AMQPChannelException(AMQPException):
    pass


METHOD_NAME_MAP = {
    (10, 10): 'Connection.start',
    (10, 11): 'Connection.start_ok',
    (10, 20): 'Connection.secure',
    (10, 21): 'Connection.secure_ok',
    (10, 30): 'Connection.tune',
    (10, 31): 'Connection.tune_ok',
    (10, 40): 'Connection.open',
    (10, 41): 'Connection.open_ok',
    (10, 50): 'Connection.redirect',
    (10, 60): 'Connection.close',
    (10, 61): 'Connection.close_ok',
    (20, 10): 'Channel.open',
    (20, 11): 'Channel.open_ok',
    (20, 20): 'Channel.flow',
    (20, 21): 'Channel.flow_ok',
    (20, 30): 'Channel.alert',
    (20, 40): 'Channel.close',
    (20, 41): 'Channel.close_ok',
    (30, 10): 'Channel.access_request',
    (30, 11): 'Channel.access_request_ok',
    (40, 10): 'Channel.exchange_declare',
    (40, 11): 'Channel.exchange_declare_ok',
    (40, 20): 'Channel.exchange_delete',
    (40, 21): 'Channel.exchange_delete_ok',
    (50, 10): 'Channel.queue_declare',
    (50, 11): 'Channel.queue_declare_ok',
    (50, 20): 'Channel.queue_bind',
    (50, 21): 'Channel.queue_bind_ok',
    (50, 30): 'Channel.queue_purge',
    (50, 31): 'Channel.queue_purge_ok',
    (50, 40): 'Channel.queue_delete',
    (50, 41): 'Channel.queue_delete_ok',
    (60, 10): 'Channel.basic_qos',
    (60, 11): 'Channel.basic_qos_ok',
    (60, 20): 'Channel.basic_consume',
    (60, 21): 'Channel.basic_consume_ok',
    (60, 30): 'Channel.basic_cancel',
    (60, 31): 'Channel.basic_cancel_ok',
    (60, 40): 'Channel.basic_publish',
    (60, 50): 'Channel.basic_return',
    (60, 60): 'Channel.basic_deliver',
    (60, 70): 'Channel.basic_get',
    (60, 71): 'Channel.basic_get_ok',
    (60, 72): 'Channel.basic_get_empty',
    (60, 80): 'Channel.basic_ack',
    (60, 90): 'Channel.basic_reject',
    (60, 100): 'Channel.basic_recover',
    (90, 10): 'Channel.tx_select',
    (90, 11): 'Channel.tx_select_ok',
    (90, 20): 'Channel.tx_commit',
    (90, 21): 'Channel.tx_commit_ok',
    (90, 30): 'Channel.tx_rollback',
    (90, 31): 'Channel.tx_rollback_ok',
}
