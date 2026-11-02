cmake_minimum_required(VERSION 3.16)
project(lsm-market-display VERSION 1.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

option(LSM_BUILD_TESTS "بناء اختبارات نموذج البيانات" ON)

# يعمل مع Qt 6 أو Qt 5
find_package(Qt6 COMPONENTS Widgets QUIET)
if (Qt6_FOUND)
    set(QT_MAJOR 6)
else()
    find_package(Qt5 5.11 COMPONENTS Widgets REQUIRED)
    set(QT_MAJOR 5)
endif()
set(QT_LIBS Qt${QT_MAJOR}::Widgets)

# نموذج البيانات في مكتبة مستقلة (يُشارَك بين البرنامج والاختبارات)
add_library(lsm_model STATIC MarketData.h MarketData.cpp)
target_link_libraries(lsm_model PUBLIC Qt${QT_MAJOR}::Core)
target_include_directories(lsm_model PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(lsm-market-display WIN32
    main.cpp
    DisplayWindow.h
    DisplayWindow.cpp
)
target_link_libraries(lsm-market-display PRIVATE lsm_model ${QT_LIBS})

# النصوص العربية داخل المصدر بترميز UTF-8
if (MSVC)
    target_compile_options(lsm_model PRIVATE /utf-8)
    target_compile_options(lsm-market-display PRIVATE /utf-8)
else()
    target_compile_options(lsm-market-display PRIVATE -Wall -Wextra)
endif()

# نسخ ملف البيانات بجوار الملف التنفيذي (فقط إن لم يكن موجودًا — حتى لا يُستبدل ملف حيّ عند إعادة البناء)
add_custom_command(TARGET lsm-market-display POST_BUILD
    COMMAND ${CMAKE_COMMAND} -DSRC=${CMAKE_SOURCE_DIR}/data/session.json
            -DDST=$<TARGET_FILE_DIR:lsm-market-display>/data/session.json
            -P ${CMAKE_SOURCE_DIR}/cmake/copy_if_missing.cmake)

if (LSM_BUILD_TESTS)
    find_package(Qt${QT_MAJOR} COMPONENTS Test QUIET)
    if (Qt${QT_MAJOR}Test_FOUND)
        enable_testing()
        add_executable(test_marketdata tests/test_marketdata.cpp)
        target_link_libraries(test_marketdata PRIVATE lsm_model Qt${QT_MAJOR}::Test)
        if (MSVC)
            target_compile_options(test_marketdata PRIVATE /utf-8)
        endif()
        add_test(NAME test_marketdata COMMAND test_marketdata)
        target_compile_definitions(test_marketdata PRIVATE
            LSM_SAMPLE_JSON="${CMAKE_SOURCE_DIR}/data/session.json")
    endif()
endif()
