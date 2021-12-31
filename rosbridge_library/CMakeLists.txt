cmake_minimum_required(VERSION 3.5)
project(rosbridge_library)

find_package(ament_cmake_ros REQUIRED)
find_package(ament_cmake_core REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(
  ${PROJECT_NAME} PACKAGE_DIR "src/${PROJECT_NAME}")

ament_package()

if (BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)

# Generate added messages and services with any dependencies listed here
generate_messages(
  DEPENDENCIES
  std_msgs
  geometry_msgs
)

catkin_package(
  CATKIN_DEPENDS message_runtime std_msgs geometry_msgs
)

# Test launch files
#if (CATKIN_ENABLE_TESTING)
#  find_package(rostest REQUIRED)
#  add_rostest(test/capabilities/test_capabilities.test)
#  add_rostest(test/internal/test_internal.test)
#endif()
