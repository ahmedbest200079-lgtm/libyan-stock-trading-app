# ينسخ SRC إلى DST فقط إن لم يكن DST موجودًا
if (NOT EXISTS "${DST}")
    get_filename_component(_dir "${DST}" DIRECTORY)
    file(MAKE_DIRECTORY "${_dir}")
    file(COPY "${SRC}" DESTINATION "${_dir}")
endif()
