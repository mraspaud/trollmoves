#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2019
#
# Author(s):
#
#   Martin Raspaud <martin.raspaud@smhi.se>
#   Panu Lahtinen <panu.lahtinen@fmi.fi>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Test the trollmoves client."""

from unittest.mock import MagicMock, patch

from posttroll.message import Message

# The different messages that are handled.  For further tests `data`
# can be populated with more values.
MSG_PUSH = Message('/topic', 'push', data={'uid': 'file1'})
MSG_ACK = Message('/topic', 'ack', data={'uid': 'file1'})
MSG_FILE1 = Message('/topic', 'file', data={'uid': 'file1'})
UID_FILE1 = "826e8142e6baabe8af779f5f490cf5f5"
MSG_FILE2 = Message('/topic', 'file', data={'uid': 'file2',
                                            'request_address': '127.0.0.1:0'})
UID_FILE2 = '1c1c96fd2cf8330db0bfa936ce82f3b9'
MSG_BEAT = Message('/topic', 'beat', data={'uid': 'file1'})


@patch('trollmoves.heartbeat_monitor.Monitor')
@patch('trollmoves.client.Subscriber')
def test_listener(Subscriber, Monitor):
    """Test listener."""
    from trollmoves.client import Listener, ongoing_transfers, file_cache

    # Mock subscriber returning messages
    subscriber = MagicMock()
    Subscriber.return_value = subscriber

    # Mock heartbeat monitor
    beat_monitor = MagicMock()
    Monitor.return_value.__enter__.return_value = beat_monitor
    # Mock callback
    callback = MagicMock()

    # Create the listener that is configured with small processing
    # delay so it works as it would in client meant to be a hot spare
    listener = Listener('127.0.0.1:0', ['/topic'], callback, 'arg1', 'arg2',
                        processing_delay=0.02,
                        kwarg1='kwarg1', kwarg2='kwarg2')

    # Test __init__
    assert listener.topics == ['/topic']
    assert listener.callback is callback
    assert listener.subscriber is None
    assert listener.address == '127.0.0.1:0'
    assert listener.running is False
    assert listener.cargs == ('arg1', 'arg2')
    kwargs = {'processing_delay': 0.02, 'kwarg1': 'kwarg1', 'kwarg2': 'kwarg2'}
    for key, itm in listener.ckwargs.items():
        assert kwargs[key] == itm

    # "Receive" no message, and a 'push' message
    subscriber.return_value = [None, MSG_PUSH]
    # Raise something to stop listener
    callback.side_effect = [StopIteration]
    try:
        listener.run()
    except StopIteration:
        pass
    assert len(file_cache) == 0
    assert len(ongoing_transfers) == 1
    assert len(callback.mock_calls) == 1
    assert listener.subscriber is subscriber
    assert listener.running
    beat_monitor.assert_called()

    # Reset
    ongoing_transfers = {}

    # "Receive" 'push' and 'ack' messages
    subscriber.return_value = [MSG_PUSH, MSG_ACK]
    # Raise something to stop listener
    callback.side_effect = [None, StopIteration]
    try:
        listener.run()
    except StopIteration:
        pass
    assert len(file_cache) == 1
    assert len(ongoing_transfers) == 0
    assert len(callback.mock_calls) == 3

    # Receive also a 'file' and 'beat' messages
    subscriber.return_value = [MSG_PUSH, MSG_ACK, MSG_BEAT, MSG_FILE1]
    callback.side_effect = [None, None, StopIteration]
    try:
        listener.run()
    except StopIteration:
        pass
    assert len(file_cache) == 1
    assert len(ongoing_transfers) == 0
    # Messages with type 'beat' don't increment callback call-count
    assert len(callback.mock_calls) == 6

    # Test listener.stop()
    listener.stop()
    assert listener.running is False
    subscriber.close.assert_called_once()
    assert listener.subscriber is None


@patch('trollmoves.client.ongoing_transfers_lock')
def test_add_to_ongoing(lock):
    """Test add_to_ongoing()."""
    from trollmoves.client import add_to_ongoing, ongoing_transfers

    # Mock the lock context manager
    lock_cm = MagicMock()
    lock.__enter__ = lock_cm

    # Add a message to ongoing transfers
    res = add_to_ongoing(MSG_FILE1)
    lock_cm.assert_called_once()
    assert res is not None
    assert len(ongoing_transfers) == 1
    assert isinstance(ongoing_transfers[UID_FILE1], list)
    assert len(ongoing_transfers[UID_FILE1]) == 1

    # Add the same message again
    res = add_to_ongoing(MSG_FILE1)
    assert len(lock_cm.mock_calls) == 2
    assert res is None
    assert len(ongoing_transfers) == 1
    assert len(ongoing_transfers[UID_FILE1]) == 2

    # Another message, a new ongoing transfer is added
    res = add_to_ongoing(MSG_FILE2)
    assert len(lock_cm.mock_calls) == 3
    assert res is not None
    assert len(ongoing_transfers) == 2


@patch('trollmoves.client.cache_lock')
def test_add_to_file_cache(lock):
    """Test trollmoves.client.add_to_file_cache()."""
    from trollmoves.client import add_to_file_cache, file_cache

    # Mock the lock context manager
    lock_cm = MagicMock()
    lock.__enter__ = lock_cm

    # Add a file to cache
    add_to_file_cache(MSG_FILE1)
    lock_cm.assert_called_once()
    assert len(file_cache) == 1
    assert MSG_FILE1.data['uid'] in file_cache

    # Add the same file again
    add_to_file_cache(MSG_FILE1)
    assert len(lock_cm.mock_calls) == 2
    # The file should be there only once
    assert len(file_cache) == 1
    assert MSG_FILE1.data['uid'] in file_cache

    # Add another file
    add_to_file_cache(MSG_FILE2)
    assert len(lock_cm.mock_calls) == 3
    assert len(file_cache) == 2
    assert MSG_FILE2.data['uid'] in file_cache


@patch('trollmoves.client.add_to_ongoing')
@patch('trollmoves.client.ongoing_transfers')
@patch('trollmoves.client.terminate_transfers')
@patch('trollmoves.client.send_request')
@patch('trollmoves.client.send_ack')
def test_request_push(send_ack, send_request, terminate_transfers,
                      ongoing_transfers, add_to_ongoing):
    """Test trollmoves.client.request_push()."""
    from trollmoves.client import request_push, file_cache
    from tempfile import gettempdir

    ongoing_transfers[UID_FILE2].pop.return_value = MSG_FILE2
    send_request.return_value = [MSG_FILE2, 'localhost']
    publisher = MagicMock()
    kwargs = {'transfer_req_timeout': 1.0, 'req_timeout': 1.0}

    request_push(MSG_FILE2, gettempdir(), 'login', publisher=publisher,
                 **kwargs)

    send_request.assert_called_once()
    send_ack.assert_not_called()
    # The file should be added to ongoing transfers
    add_to_ongoing.assert_called_once()
    # And removed
    ongoing_transfers[UID_FILE2].pop.assert_called_once()
    # The transferred file should be in the cache
    assert MSG_FILE2.data['uid'] in file_cache
    assert len(file_cache) == 1

    # Request the same file again. Now the transfer should not be
    # started again, and `send_ack()` should be called.
    request_push(MSG_FILE2, gettempdir(), 'login', publisher=publisher,
                 **kwargs)

    send_ack.assert_called_once()
    send_request.assert_called_once()
