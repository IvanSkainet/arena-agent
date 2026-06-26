"""unified_bridge import surface: domains imports."""
from __future__ import annotations

# Pure helper utilities now live in arena/util.py; re-exported for compatibility.
from arena.util import (  # noqa: E402,F401
    _NO_WINDOW_FLAG,
    _subprocess_kwargs,
    b64_token,
    decode_output,
    first_word,
    get_clean_platform_name,
    under_root,
    utc_now,
)

# Service/process/restart helpers extracted during v3 modularization.
from arena.service.runtime import (  # noqa: E402,F401
    _ps_utf8_command,
    _sc_query_running,
    _service_info_sync,
    _spawn_respawn_helper,
    _sys_svc_sync,
    _windows_bridge_processes,
    _windows_scheduled_task_info,
)

from arena.capabilities import build_capabilities  # noqa: E402,F401
from arena.inventory.hardware import (  # noqa: E402,F401
    hardware_from_inventory_result,
    merge_nvidia_gpu_facts,
    normalize_inventory_hardware,
)
from arena.inventory.runner import (  # noqa: E402,F401
    find_inventory_script,
    run_inventory,
)
from arena.tasks.queue import (  # noqa: E402,F401
    clean_tasks,
    list_tasks,
    submit_task,
)
from arena.filewatch.runtime import FileWatchRuntimeContext, make_file_watch_runtime  # noqa: E402,F401
from arena.filewatch.handlers import make_file_watch_handlers  # noqa: E402,F401
from arena.tasks.runner import TaskRunnerContext, make_task_runner_runtime  # noqa: E402,F401
from arena.tasks.runtime import TaskQueueRuntimeContext, make_task_queue_runtime  # noqa: E402,F401
from arena.skills.registry import (  # noqa: E402,F401
    parse_skill_folder,
    scan_skills,
)
from arena.skills.cache import SkillsCache  # noqa: E402,F401
from arena.skills.install import (  # noqa: E402,F401
    install_skill,
    normalize_third_party_skill_name,
    uninstall_skill,
)
from arena.skills.runner import run_skill  # noqa: E402,F401
from arena.skills.runtime import SkillRuntimeContext, make_skill_runtime  # noqa: E402,F401
from arena.skills.handlers import make_skill_handlers  # noqa: E402,F401
from arena.desktop.runtime import (  # noqa: E402,F401
    _desktop_exec,
    _detect_desktop_env,
    _get_active_window,
    _kwin_windows_via_script,
    ocr_desktop,
)
from arena.desktop.screenshot import capture_desktop_screenshot  # noqa: E402,F401
from arena.desktop.focus import focus_window  # noqa: E402,F401
from arena.desktop.kwin_focus import kwin_focus_window_via_script  # noqa: E402,F401
from arena.desktop.handlers import make_desktop_handlers  # noqa: E402,F401
from arena.control_handlers import make_control_lease_handlers  # noqa: E402,F401
from arena.browser.fetch import (  # noqa: E402,F401
    browser_dump,
    browser_fetch,
    browser_head,
    browser_read,
    browser_search,
)
from arena.browser.handlers import make_browser_browse_handlers, make_browser_fetch_handlers  # noqa: E402,F401
from arena.browser.runtime import BrowserRuntimeContext, make_browser_runtime  # noqa: E402,F401
from arena.browser.cdp.handlers import make_cdp_basic_handlers  # noqa: E402,F401
from arena.browser.cdp.diagnostics import make_cdp_diagnostic_handlers  # noqa: E402,F401
from arena.browser.cdp.session import make_cdp_session_handlers  # noqa: E402,F401
from arena.browser.cdp.page import make_cdp_page_handlers  # noqa: E402,F401
from arena.browser.cdp.tabs import make_cdp_tabs_handlers  # noqa: E402,F401
from arena.browser.cdp.cookies import ensure_cookie_manager as _cdp_ensure_cookie_manager, make_cdp_cookies_handlers  # noqa: E402,F401
from arena.browser.cdp.network import make_cdp_network_handlers  # noqa: E402,F401
from arena.browser.cdp.intercept import make_cdp_intercept_handlers  # noqa: E402,F401
from arena.browser.cdp.advanced import get_active_browser as _cdp_get_active_browser_from_context, make_cdp_advanced_handlers  # noqa: E402,F401
from arena.browser.cdp.runtime import (  # noqa: E402,F401
    _cdp_connect_lock,
    _cdp_state,
    _get_cdp_module,
    _start_cdp_watcher,
    _stop_cdp_watcher,
    cdp_watcher_active as _cdp_watcher_active,
)
from arena.browser.cdp.active_tab import cdp_active_tab as _cdp_active_tab_impl  # noqa: E402,F401
from arena.extension_bridge.handlers import make_extension_bridge_handlers  # noqa: E402,F401
from arena.extension_bridge.runtime import ExtensionBridgeRuntimeContext, make_extension_bridge_runtime  # noqa: E402,F401
from arena.resources.listing import (  # noqa: E402,F401
    list_agents,
    list_hooks,
    list_missions,
    list_reports,
    list_subagents,
    show_mission,
)
from arena.resources.handlers import make_resource_handlers  # noqa: E402,F401
from arena.resources.mission_lifecycle_handlers import make_mission_lifecycle_handlers  # noqa: E402,F401
from arena.resources.mission_schedule_worker import MissionScheduleWorkerContext, make_mission_schedule_worker_runtime  # noqa: E402,F401
from arena.resources.runtime import ResourceRuntimeContext, make_resource_runtime  # noqa: E402,F401
from arena.resources.mission_loops import followup_mission_bundle, iterate_mission_bundle  # noqa: E402,F401
from arena.resources.missions_orchestration import propose_mission_bundle, recover_mission_bundle  # noqa: E402,F401
from arena.resources.subagents import spawn_subagent  # noqa: E402,F401
from arena.planner.logic import build_plan  # noqa: E402,F401
from arena.planner.handlers import make_planner_handlers  # noqa: E402,F401
from arena.agentic.runtime import AgenticRuntimeContext, make_agentic_runtime  # noqa: E402,F401
from arena.agentic.handlers import make_agentic_handlers  # noqa: E402,F401
from arena.memory.handlers import make_memory_handlers  # noqa: E402,F401
from arena.memory.runtime import MemoryRuntimeContext, make_memory_runtime  # noqa: E402,F401
from arena.memory.store import (  # noqa: E402,F401
    delete_fact as memory_delete_fact,
    init_memory_db as memory_init_db,
    load_facts as memory_load_facts,
    recall as memory_recall,
    recall_digest as memory_recall_digest,
    search_facts_paged as memory_search_facts_paged,
    write_fact as memory_write_fact,
)
from arena.desktop.input import (  # noqa: E402,F401
    build_click_command,
    build_key_command,
    build_mouse_command,
    build_type_command,
)

__all__ = [name for name in globals() if not name.startswith("__")]
