# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import rospy

from rosauth.srv import Authentication

import sys
import threading
import traceback
from functools import wraps

from twisted.python import log
from twisted.internet import interfaces, reactor
from twisted.internet.protocol import ReconnectingClientFactory
from zope.interface import implementer

from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json, bson

def _log_exception():
    """Log the most recent exception to ROS."""
    exc = traceback.format_exception(*sys.exc_info())
    rospy.logerr(''.join(exc))


def log_exceptions(f):
    """Decorator for logging exceptions to ROS."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except:
            _log_exception()
            raise
    return wrapper


@implementer(interfaces.IPushProducer)
class OutgoingValve:
    """Allows the Autobahn transport to pause outgoing messages from rosbridge.
    
    The purpose of this valve is to connect backpressure from the WebSocket client
    back to the rosbridge protocol, which depends on backpressure for queueing.
    Without this flow control, rosbridge will happily keep writing messages to
    the WebSocket until the system runs out of memory.

    This valve is closed and opened automatically by the Twisted TCP server.
    In practice, Twisted should only close the valve when its userspace write buffer
    is full and it should only open the valve when that buffer is empty.

    When the valve is closed, the rosbridge protocol instance's outgoing writes
    must block until the valve is opened.
    """
    def __init__(self, proto):
        self._proto = proto
        self._valve = threading.Event()
        self._finished = False

    @log_exceptions
    def relay(self, message):
        self._valve.wait()
        if self._finished:
            return
        reactor.callFromThread(self._proto.outgoing, message)

    def pauseProducing(self):
        if not self._finished:
            self._valve.clear()

    def resumeProducing(self):
        self._valve.set()

    def stopProducing(self):
        self._finished = True
        self._valve.set()

class RosbridgeWebSocketClientProtocol(WebSocketClientProtocol):
    client_id_seed = ""
    authenticate = False

    # The following are passed on to RosbridgeProtocol
    # defragmentation.py:
    fragment_timeout = 600                  # seconds
    # protocol.py:
    delay_between_messages = 0              # seconds
    max_message_size = None                 # bytes
    unregister_timeout = 10.0               # seconds
    bson_only_mode = False
    tcpNoDelay = True                       # turn off Nagle algorithm

    def set_nodelay(self, nodelay):
        self.tcpNoDelay = nodelay

    def onConnect(self, response):
        self.client_id_seed = response.peer
        rospy.loginfo("Connected to websocket server: {0}".format(self.client_id_seed))

    def onOpen(self):
        rospy.loginfo("Connection opened to websocket server: {0}".format(self.client_id_seed))
        cls = self.__class__
        parameters = {
            "fragment_timeout": cls.fragment_timeout,
            "delay_between_messages": cls.delay_between_messages,
            "max_message_size": cls.max_message_size,
            "unregister_timeout": cls.unregister_timeout,
            "bson_only_mode": cls.bson_only_mode
        }
        try:
            self.protocol = RosbridgeProtocol(self.client_id_seed, parameters=parameters)
            producer = OutgoingValve(self)
            self.transport.registerProducer(producer, True)
            producer.resumeProducing()
            self.protocol.outgoing = producer.relay
            self.authenticated = False
        except Exception as exc:
            rospy.logerr("Unable to accept incoming connection.  Reason: %s", str(exc))
        if cls.authenticate:
            rospy.loginfo("Awaiting proper authentication...")

    def outgoing(self, message):
        if type(message) == bson.BSON:
            binary = True
            message = bytes(message)
        elif type(message) == bytearray:
            binary = True
            message = bytes(message)
        else:
            binary = False
            message = message.encode('utf-8')

        self.sendMessage(message, binary)

    def onMessage(self, message, binary):
        cls = self.__class__
        if not binary:
            message = message.decode('utf-8')
        # check if we need to authenticate
        if cls.authenticate and not self.authenticated:
            try:
                if cls.bson_only_mode:
                    msg = bson.BSON(message).decode()
                else:
                    msg = json.loads(message)

                if msg['op'] == 'auth':
                    # check the authorization information
                    auth_srv = rospy.ServiceProxy('authenticate', Authentication)
                    resp = auth_srv(msg['mac'], msg['client'], msg['dest'],
                                                  msg['rand'], rospy.Time(msg['t']), msg['level'],
                                                  rospy.Time(msg['end']))
                    self.authenticated = resp.authenticated
                    if self.authenticated:
                        rospy.loginfo("Client %d has authenticated.", self.protocol.client_id)
                        return
                # if we are here, no valid authentication was given
                rospy.logwarn("Client %d did not authenticate. Closing connection.",
                              self.protocol.client_id)
                self.sendClose()
            except:
                # proper error will be handled in the protocol class
                self.protocol.incoming(message)
        else:
            # no authentication required
            self.protocol.incoming(message)

    def onClose(self, wasClean, code, reason):
        if hasattr(self, 'protocol'):
            self.protocol.finish()

        rospy.loginfo("Disconnected from websocket server: {0}".format(reason))

class RosbridgeWebSocketClientFactory(WebSocketClientFactory, ReconnectingClientFactory):
    maxDelay = 1
    protocol = RosbridgeWebSocketClientProtocol

    def clientConnectionFailed(self, connector, reason):
        self.retry(connector)

    def clientConnectionLost(self, connector, reason):
        self.retry(connector)
