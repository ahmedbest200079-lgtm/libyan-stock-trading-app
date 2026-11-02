cmake_minimum_required(VERSION 3.16)
project(lsm-market-display VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# يعمل مع Qt 6 أو Qt 5
find_package(Qt6 COMPONENTS Widgets QUIET)
if (Qt6_FOUND)
    set(QT_LIBS Qt6::Widgets)
else()
    find_package(Qt5 COMPONENTS Widgets REQUIRED)
    set(QT_LIBS Qt5::Widgets)
endif()

add_executable(lsm-market-display WIN32
    main.cpp
    MarketData.h
    MarketData.cpp
    DisplayWindow.h
    DisplayWindow.cpp
)

target_link_libraries(lsm-market-display PRIVATE ${QT_LIBS})

# النصوص العربية داخل المصدر بترميز UTF-8
if (MSVC)
    target_compile_options(lsm-market-display PRIVATE /utf-8)
endif()

# نسخ ملف البيانات بجوار الملف التنفيذي
add_custom_command(TARGET lsm-market-display POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_SOURCE_DIR}/data $<TARGET_FILE_DIR:lsm-market-display>/data)
