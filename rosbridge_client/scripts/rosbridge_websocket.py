#!/usr/bin/env python
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

from __future__ import print_function
import rospy
import sys

from twisted.python import log
from twisted.internet import reactor, ssl
from twisted.internet.error import CannotListenError, ReactorNotRunning
from distutils.version import LooseVersion
import autobahn #to check version
from autobahn.twisted.websocket import WebSocketServerFactory, connectWS
from autobahn.websocket.compress import (PerMessageDeflateOffer,
                                         PerMessageDeflateOfferAccept)
log.startLogging(sys.stdout)

from rosbridge_client import RosbridgeWebSocketClientProtocol, RosbridgeWebSocketClientFactory

from rosbridge_library.capabilities.advertise import Advertise
from rosbridge_library.capabilities.publish import Publish
from rosbridge_library.capabilities.subscribe import Subscribe
from rosbridge_library.capabilities.advertise_service import AdvertiseService
from rosbridge_library.capabilities.unadvertise_service import UnadvertiseService
from rosbridge_library.capabilities.call_service import CallService

def shutdown_hook():
    try:
        reactor.stop()
    except ReactorNotRunning:
        rospy.logwarn("Can't stop the reactor, it wasn't running")


if __name__ == "__main__":
    rospy.init_node("rosbridge_websocket")
    rospy.on_shutdown(shutdown_hook)    # register shutdown hook to stop the server

    ##################################################
    # Parameter handling                             #
    ##################################################
    use_compression = rospy.get_param('~use_compression', False)
    jwt_token = rospy.get_param('~jwt_token')

    socketServerURL = rospy.get_param('~ros_bridge_socket_server_url')

   # get RosbridgeProtocol parameters
    RosbridgeWebSocketClientProtocol.fragment_timeout = rospy.get_param('~fragment_timeout',
                                                          RosbridgeWebSocketClientProtocol.fragment_timeout)
    RosbridgeWebSocketClientProtocol.delay_between_messages = rospy.get_param('~delay_between_messages',
                                                                RosbridgeWebSocketClientProtocol.delay_between_messages)
    RosbridgeWebSocketClientProtocol.max_message_size = rospy.get_param('~max_message_size',
                                                          RosbridgeWebSocketClientProtocol.max_message_size)
    RosbridgeWebSocketClientProtocol.unregister_timeout = rospy.get_param('~unregister_timeout',
                                                          RosbridgeWebSocketClientProtocol.unregister_timeout)
    bson_only_mode = rospy.get_param('~bson_only_mode', False)

    if RosbridgeWebSocketClientProtocol.max_message_size == "None":
        RosbridgeWebSocketClientProtocol.max_message_size = None

    ping_interval = float(rospy.get_param('~websocket_ping_interval', 0))
    ping_timeout = float(rospy.get_param('~websocket_ping_timeout', 30))
    null_origin = rospy.get_param('~websocket_null_origin', True) #default to original behaviour

    # SSL options
    certfile = rospy.get_param('~certfile', None)
    keyfile = rospy.get_param('~keyfile', None)
    # if authentication should be used
    RosbridgeWebSocketClientProtocol.authenticate = rospy.get_param('~authenticate', False)

    # Get the glob strings and parse them as arrays.
    RosbridgeWebSocketClientProtocol.topics_glob = [
        element.strip().strip("'")
        for element in rospy.get_param('~topics_glob', '')[1:-1].split(',')
        if len(element.strip().strip("'")) > 0]
    RosbridgeWebSocketClientProtocol.services_glob = [
        element.strip().strip("'")
        for element in rospy.get_param('~services_glob', '')[1:-1].split(',')
        if len(element.strip().strip("'")) > 0]
    RosbridgeWebSocketClientProtocol.params_glob = [
        element.strip().strip("'")
        for element in rospy.get_param('~params_glob', '')[1:-1].split(',')
        if len(element.strip().strip("'")) > 0]

    if "--fragment_timeout" in sys.argv:
        idx = sys.argv.index("--fragment_timeout") + 1
        if idx < len(sys.argv):
            RosbridgeWebSocketClientProtocol.fragment_timeout = int(sys.argv[idx])
        else:
            print("--fragment_timeout argument provided without a value.")
            sys.exit(-1)

    if "--delay_between_messages" in sys.argv:
        idx = sys.argv.index("--delay_between_messages") + 1
        if idx < len(sys.argv):
            RosbridgeWebSocketClientProtocol.delay_between_messages = float(sys.argv[idx])
        else:
            print("--delay_between_messages argument provided without a value.")
            sys.exit(-1)

    if "--max_message_size" in sys.argv:
        idx = sys.argv.index("--max_message_size") + 1
        if idx < len(sys.argv):
            value = sys.argv[idx]
            if value == "None":
                RosbridgeWebSocketClientProtocol.max_message_size = None
            else:
                RosbridgeWebSocketClientProtocol.max_message_size = int(value)
        else:
            print("--max_message_size argument provided without a value. (can be None or <Integer>)")
            sys.exit(-1)

    if "--unregister_timeout" in sys.argv:
        idx = sys.argv.index("--unregister_timeout") + 1
        if idx < len(sys.argv):
            unregister_timeout = float(sys.argv[idx])
        else:
            print("--unregister_timeout argument provided without a value.")
            sys.exit(-1)

    if "--topics_glob" in sys.argv:
        idx = sys.argv.index("--topics_glob") + 1
        if idx < len(sys.argv):
            value = sys.argv[idx]
            if value == "None":
                RosbridgeWebSocketClientProtocol.topics_glob = []
            else:
                RosbridgeWebSocketClientProtocol.topics_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
        else:
            print("--topics_glob argument provided without a value. (can be None or a list)")
            sys.exit(-1)

    if "--services_glob" in sys.argv:
        idx = sys.argv.index("--services_glob") + 1
        if idx < len(sys.argv):
            value = sys.argv[idx]
            if value == "None":
                RosbridgeWebSocketClientProtocol.services_glob = []
            else:
                RosbridgeWebSocketClientProtocol.services_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
        else:
            print("--services_glob argument provided without a value. (can be None or a list)")
            sys.exit(-1)

    if "--params_glob" in sys.argv:
        idx = sys.argv.index("--params_glob") + 1
        if idx < len(sys.argv):
            value = sys.argv[idx]
            if value == "None":
                RosbridgeWebSocketClientProtocol.params_glob = []
            else:
                RosbridgeWebSocketClientProtocol.params_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
        else:
            print("--params_glob argument provided without a value. (can be None or a list)")
            sys.exit(-1)

    if ("--bson_only_mode" in sys.argv) or bson_only_mode:
        RosbridgeWebSocketClientProtocol.bson_only_mode = bson_only_mode

    if "--websocket_ping_interval" in sys.argv:
        idx = sys.argv.index("--websocket_ping_interval") + 1
        if idx < len(sys.argv):
            ping_interval = float(sys.argv[idx])
        else:
            print("--websocket_ping_interval argument provided without a value.")
            sys.exit(-1)

    if "--websocket_ping_timeout" in sys.argv:
        idx = sys.argv.index("--websocket_ping_timeout") + 1
        if idx < len(sys.argv):
            ping_timeout = float(sys.argv[idx])
        else:
            print("--websocket_ping_timeout argument provided without a value.")
            sys.exit(-1)

    if "--websocket_external_port" in sys.argv:
        idx = sys.argv.index("--websocket_external_port") + 1
        if idx < len(sys.argv):
            external_port = int(sys.argv[idx])
        else:
            print("--websocket_external_port argument provided without a value.")
            sys.exit(-1)

    # To be able to access the list of topics and services, you must be able to access the rosapi services.
    if RosbridgeWebSocketClientProtocol.services_glob:
        RosbridgeWebSocketClientProtocol.services_glob.append("/rosapi/*")

    Subscribe.topics_glob = RosbridgeWebSocketClientProtocol.topics_glob
    Advertise.topics_glob = RosbridgeWebSocketClientProtocol.topics_glob
    Publish.topics_glob = RosbridgeWebSocketClientProtocol.topics_glob
    AdvertiseService.services_glob = RosbridgeWebSocketClientProtocol.services_glob
    UnadvertiseService.services_glob = RosbridgeWebSocketClientProtocol.services_glob
    CallService.services_glob = RosbridgeWebSocketClientProtocol.services_glob

    ##################################################
    # Done with parameter handling                   #
    ##################################################

    def handle_compression_offers(offers):
        if not use_compression:
            return
        for offer in offers:
            if isinstance(offer, PerMessageDeflateOffer):
                return PerMessageDeflateOfferAccept(offer)

    headers = {'Barrier Token': jwt_token}

    factory = RosbridgeWebSocketClientFactory(socketServerURL, headers=headers)

    # SSL client context: default
    ##
    if factory.isSecure:
        print('Using client context factory')
        context_factory = ssl.ClientContextFactory()
    else:
        context_factory = None

    # https://github.com/crossbario/autobahn-python/commit/2ef13a6804054de74eb36455b58a64a3c701f889
    if LooseVersion(autobahn.__version__) < LooseVersion("0.15.0"):
        factory.setProtocolOptions(
            perMessageCompressionAccept=handle_compression_offers,
            autoPingInterval=ping_interval,
            autoPingTimeout=ping_timeout,
        )
    else:
        factory.setProtocolOptions(
            perMessageCompressionAccept=handle_compression_offers,
            autoPingInterval=ping_interval,
            autoPingTimeout=ping_timeout,
            allowNullOrigin=null_origin,
        )

    connectWS(factory, context_factory)
    rospy.loginfo('Rosbridge WebSocket client started at {}'.format(socketServerURL))

    rospy.on_shutdown(shutdown_hook)
    reactor.run()
