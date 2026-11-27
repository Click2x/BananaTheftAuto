# Writes OUT (a header) with the Banana Theft Auto build id: the commit's date and short id ("2026.11.27-c246593"),
# with "+changes" when the runtime folder has uncommitted edits. Rewritten only when it changes. Run each build.
execute_process(COMMAND git -C "${SRC}" log -1 --format=%cd-%h --date=format:%Y.%m.%d
                OUTPUT_VARIABLE id OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET RESULT_VARIABLE rc)
if(NOT rc EQUAL 0 OR id STREQUAL "")
  set(id "unknown")
else()
  execute_process(COMMAND git -C "${SRC}" diff --quiet HEAD -- . RESULT_VARIABLE dirty ERROR_QUIET)
  if(NOT dirty EQUAL 0)
    set(id "${id}+changes")
  endif()
endif()
set(text "#pragma once\n#define BTA_BUILD_ID \"${id}\"\n#define BTA_BUILD_ID_W L\"${id}\"\n")
if(EXISTS "${OUT}")
  file(READ "${OUT}" old)
endif()
if(NOT "${old}" STREQUAL "${text}")
  file(WRITE "${OUT}" "${text}")
endif()
