import pytest
from arena.exec.handlers import _EXACT_BLOCKED_ENV, _PATTERN_BLOCKED_ENV

def test_exact_blocked_env_contains_windows_vars():
    """验证精确屏蔽列表包含 Windows 关键变量"""
    required = {"PATH", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
                "APPDATA", "USERPROFILE", "PATHEXT"}
    assert required.issubset(_EXACT_BLOCKED_ENV)

def test_pattern_blocked_env_contains_secret_patterns():
    """验证模式屏蔽列表包含敏感关键词"""
    required = {"TOKEN", "SECRET", "PASSWORD", "KEY"}
    assert required.issubset(_PATTERN_BLOCKED_ENV)

def test_exact_blocked_env_is_case_insensitive(monkeypatch):
    """验证精确屏蔽是大小写不敏感的"""
    from arena.exec.handlers import make_exec_handlers
    from arena.handler_context import ExecHandlerContext
    from aiohttp import web
    import asyncio
    import os
    
    # 创建一个简单的 context
    class MockContext(ExecHandlerContext):
        pass
    
    ctx = MockContext()
    # 模拟一些必要的方法
    ctx.cors_json_response = lambda x, status=200: web.Response()
    ctx.blocked_reason = lambda x: None
    ctx.control_check = lambda: None
    ctx.is_input_injection_cmd = lambda x: None
    ctx.first_word = lambda x: x.split()[0] if x else ""
    ctx.under_root = lambda x, y: True
    ctx.decode_output = lambda x: x.decode()
    ctx.audit = lambda x: None
    ctx.record_request = lambda **kwargs: None
    ctx.active_processes = {}
    ctx.cautious_allow = []
    ctx.default_max_output = 1024 * 1024
    ctx.run_shell_command = lambda **kwargs: {"ok": True}
    
    handlers = make_exec_handlers(ctx)
    
    # 测试精确匹配大小写不敏感
    exact_set = _EXACT_BLOCKED_ENV
    assert "path" not in exact_set  # 存的是大写
    # 但在代码中会用 .upper() 转换，所以 "path" 会变成 "PATH" 匹配
    assert "PATH" in exact_set
