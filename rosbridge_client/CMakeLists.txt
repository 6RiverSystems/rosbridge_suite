cmake_minimum_required(VERSION 2.8.3)
project(rosbridge_client)

find_package(catkin REQUIRED)

catkin_python_setup()

catkin_package()

install(PROGRAMS
  scripts/rosbridge_websocket.py
  scripts/rosbridge_websocket
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(FILES
  launch/rosbridge_websocket.launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
)

