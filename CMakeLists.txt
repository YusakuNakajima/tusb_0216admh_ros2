cmake_minimum_required(VERSION 3.8)
project(tusb_0216admh_ros2)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AdcBlock.msg"
  DEPENDENCIES std_msgs
)

# For testing
if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()

  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_conversion
    test/test_conversion.py
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}
  )
  ament_add_pytest_test(test_mock_device
    test/test_mock_device.py
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}
  )
  ament_add_pytest_test(test_usb_capture
    test/test_usb_capture.py
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}
  )
endif()

#-- for Python
# The driver library is its own module (tusb_0216admh) because rosidl already
# installs a Python package named ${PROJECT_NAME} for the messages.
ament_python_install_package(tusb_0216admh)

install(PROGRAMS
  scripts/tusb_0216admh_node.py
  scripts/tusb_probe.py
  scripts/analyze_usb_capture.py
  DESTINATION lib/${PROJECT_NAME}
)
#--- end Python

install(DIRECTORY
  config
  launch
  udev
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
