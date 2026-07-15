import ast
from collections.abc import Iterator
from pathlib import Path


APP_ROOT = Path(__file__).parents[3] / "app"
_LOG_METHODS = {
    "trace", "debug", "info", "success", "warning", "error", "critical", "exception",
    "log",
}
_SENSITIVE_NAMES = {
    "additional_pid", "body", "budget_per_person_krw", "budget_total", "content",
    "display_name", "dst_key", "file_url", "fixed_pid", "food_preference",
    "full_prefix", "image_url", "keyword", "origin", "path", "place_id", "prefix",
    "project_id", "provider_account_id", "query", "src_key", "text", "token",
    "tokens", "url",
}


def _python_sources():
    for path in APP_ROOT.rglob("*.py"):
        yield path, path.read_text(encoding="utf-8")


def _logger_aliases(tree: ast.AST) -> set[str]:
    aliases = {"get_logger", "logger"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.logger":
            for imported in node.names:
                if imported.name in {"app_logger", "get_logger"}:
                    aliases.add(imported.asname or imported.name)
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            value = node.value
            returns_logger = (
                isinstance(value, ast.Name)
                and value.id in aliases
            ) or (
                isinstance(value, ast.Call)
                and (
                    isinstance(value.func, ast.Name)
                    and value.func.id in aliases
                    or isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get_logger"
                    or isinstance(value.func, ast.Attribute)
                    and value.func.attr in {"bind", "opt"}
                    and _is_logger_receiver(value.func.value, aliases)
                )
            )
            if not returns_logger:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
                elif isinstance(target, ast.Attribute) and target.attr not in aliases:
                    aliases.add(target.attr)
                    changed = True
    return aliases


def _is_logger_receiver(node: ast.expr, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute):
        return node.attr in aliases or _is_logger_receiver(node.value, aliases)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id in aliases
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "get_logger":
                return True
            return _is_logger_receiver(node.func.value, aliases)
    return False


def _log_calls(tree: ast.AST, aliases: set[str]) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
            and _is_logger_receiver(node.func.value, aliases)
        ):
            yield node


def _payload_values(call: ast.Call) -> list[ast.expr]:
    values = [*call.args, *(keyword.value for keyword in call.keywords)]
    values.extend(
        ast.Constant(keyword.arg) for keyword in call.keywords if keyword.arg is not None
    )
    assert isinstance(call.func, ast.Attribute)
    receiver = call.func.value
    while isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute):
        values.extend(receiver.args)
        values.extend(keyword.value for keyword in receiver.keywords)
        values.extend(
            ast.Constant(keyword.arg)
            for keyword in receiver.keywords
            if keyword.arg is not None
        )
        receiver = receiver.func.value
    return values


def _sensitive_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name) and value.id in _SENSITIVE_NAMES:
        return value.id
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value if value.value in _SENSITIVE_NAMES else None
    if isinstance(value, ast.Attribute):
        if value.attr in _SENSITIVE_NAMES:
            return value.attr
        return _sensitive_name(value.value)
    if isinstance(value, ast.Subscript):
        return _sensitive_name(value.value) or _sensitive_name(value.slice)
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return next((name for item in value.elts if (name := _sensitive_name(item))), None)
    if isinstance(value, ast.Dict):
        items = [item for item in [*value.keys, *value.values] if item is not None]
        return next((name for item in items if (name := _sensitive_name(item))), None)
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id in {"bool", "len", "type"}:
            return None
        items = [value.func, *value.args, *(keyword.value for keyword in value.keywords)]
        return next((name for item in items if (name := _sensitive_name(item))), None)
    if isinstance(value, ast.JoinedStr):
        return next((name for item in value.values if (name := _sensitive_name(item))), None)
    if isinstance(value, ast.FormattedValue):
        return _sensitive_name(value.value)
    if isinstance(value, ast.BinOp):
        return _sensitive_name(value.left) or _sensitive_name(value.right)
    if isinstance(value, ast.UnaryOp):
        return _sensitive_name(value.operand)
    if isinstance(value, ast.IfExp):
        return _sensitive_name(value.body) or _sensitive_name(value.orelse)
    if isinstance(value, ast.BoolOp):
        return next(
            (name for item in value.values if (name := _sensitive_name(item))),
            None,
        )
    if isinstance(value, ast.NamedExpr):
        return _sensitive_name(value.target) or _sensitive_name(value.value)
    if isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        items = [value.elt]
        for generator in value.generators:
            items.extend([generator.iter, *generator.ifs])
        return next((name for item in items if (name := _sensitive_name(item))), None)
    if isinstance(value, ast.DictComp):
        items = [value.key, value.value]
        for generator in value.generators:
            items.extend([generator.iter, *generator.ifs])
        return next((name for item in items if (name := _sensitive_name(item))), None)
    return None


def _exception_aliases(handler: ast.ExceptHandler) -> set[str]:
    aliases = {handler.name} if handler.name else set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(handler):
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True
    return aliases


def _safe_exception_value(value: ast.expr, aliases: set[str]) -> bool:
    if isinstance(value, ast.Name):
        return value.id in aliases
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "status_code"
        and isinstance(value.value, ast.Name)
    ):
        return value.value.id in aliases
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "__name__"
        and isinstance(value.value, ast.Call)
        and isinstance(value.value.func, ast.Name)
        and value.value.func.id == "type"
        and len(value.value.args) == 1
        and isinstance(value.value.args[0], ast.Name)
        and value.value.args[0].id in aliases
    )


def test_application_uses_safe_logger_gateway_only():
    violations = []
    for path, source in _python_sources():
        tree = ast.parse(source)
        aliases = _logger_aliases(tree)
        if path.name != "logger.py":
            for node in ast.walk(tree):
                direct_import = (
                    isinstance(node, ast.Import)
                    and any(alias.name == "loguru" or alias.name.startswith("loguru.") for alias in node.names)
                ) or (
                    isinstance(node, ast.ImportFrom)
                    and node.module is not None
                    and (node.module == "loguru" or node.module.startswith("loguru."))
                )
                if direct_import:
                    violations.append(
                        f"{path.relative_to(APP_ROOT)}:{getattr(node, 'lineno', 0)}: "
                        "direct loguru import"
                    )
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "app.core.logger"
                    and any(alias.name in {"logger", "_logger"} for alias in node.names)
                ):
                    violations.append(
                        f"{path.relative_to(APP_ROOT)}:{node.lineno}: raw gateway import"
                    )
                if isinstance(node, ast.Attribute) and node.attr == "_logger":
                    violations.append(
                        f"{path.relative_to(APP_ROOT)}:{node.lineno}: raw gateway attribute"
                    )
        for call in _log_calls(tree, aliases):
            assert isinstance(call.func, ast.Attribute)
            if call.func.attr == "exception":
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{call.lineno}: logger.exception is forbidden"
                )
    assert violations == []


def test_log_calls_do_not_format_exception_or_sensitive_payloads():
    violations = []
    for path, source in _python_sources():
        tree = ast.parse(source)
        logger_aliases = _logger_aliases(tree)
        relative = path.relative_to(APP_ROOT)
        for handler in (
            node for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and node.name
        ):
            exception_aliases = _exception_aliases(handler)
            for call in _log_calls(handler, logger_aliases):
                for child in ast.walk(call):
                    if isinstance(child, ast.JoinedStr) and any(
                        isinstance(value, ast.Name) and value.id in exception_aliases
                        for value in ast.walk(child)
                    ):
                        violations.append(f"{relative}:{call.lineno}: exception f-string")
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id in {"repr", "str"}
                        and any(
                            isinstance(value, ast.Name) and value.id in exception_aliases
                            for value in child.args
                        )
                    ):
                        violations.append(f"{relative}:{call.lineno}: exception stringification")
                    if (
                        isinstance(child, ast.Attribute)
                        and isinstance(child.value, ast.Name)
                        and child.value.id in exception_aliases
                        and child.attr in {"body", "request", "response", "text", "url"}
                    ):
                        violations.append(f"{relative}:{call.lineno}: exception payload field")

                for value in _payload_values(call):
                    if _safe_exception_value(value, exception_aliases):
                        continue
                    if any(
                        isinstance(child, ast.Name) and child.id in exception_aliases
                        for child in ast.walk(value)
                    ):
                        violations.append(f"{relative}:{call.lineno}: nested exception payload")

        for call in _log_calls(tree, logger_aliases):
            for value in _payload_values(call):
                if name := _sensitive_name(value):
                    violations.append(f"{relative}:{call.lineno}: raw {name}")
    assert violations == []


def test_bound_logger_aliases_remain_inside_privacy_contract():
    tree = ast.parse(
        "base = get_logger('test')\n"
        "auth_logger = base.bind(component='auth')\n"
        "auth_logger.info('unsafe: {}', token)\n"
        "class Middleware:\n"
        "    def __init__(self):\n"
        "        self.audit = get_logger('audit')\n"
        "    def handle(self, token):\n"
        "        self.audit.warning('unsafe: {}', token)\n"
        "get_logger('direct').bind(token=token).warning('unsafe')\n"
        "import app.core.logger as gateway\n"
        "module_logger = gateway.get_logger('module')\n"
        "module_logger.warning('unsafe: {}', token)\n"
        "gateway.get_logger('module-direct').warning('unsafe: {}', token)\n"
    )
    aliases = _logger_aliases(tree)
    calls = list(_log_calls(tree, aliases))

    assert "auth_logger" in aliases
    assert "audit" in aliases
    assert "module_logger" in aliases
    assert len(calls) == 5
    assert all(
        any(_sensitive_name(value) == "token" for value in _payload_values(call))
        for call in calls
    )


def test_preformatted_sensitive_payloads_remain_inside_privacy_contract():
    unsafe_tree = ast.parse(
        "audit = get_logger('probe')\n"
        "audit.warning('unsafe: {}', str(token))\n"
        "audit.warning(f'unsafe: {token}')\n"
        "audit.warning('unsafe: {}', payload.get('token'))\n"
        "audit.warning('unsafe: {}', request.body.decode())\n"
        "audit.warning('unsafe: {}', token.strip())\n"
        "audit.warning('unsafe: {}', [token for token in tokens])\n"
        "audit.warning('unsafe: {}', {item: token for item in items})\n"
        "audit.warning('unsafe: {}', (token for token in tokens))\n"
        "audit.warning('unsafe: {}', token or fallback)\n"
        "audit.warning('unsafe: {}', (token := value))\n"
    )
    unsafe_calls = list(_log_calls(unsafe_tree, _logger_aliases(unsafe_tree)))

    assert len(unsafe_calls) == 10
    assert all(
        any(_sensitive_name(value) is not None for value in _payload_values(call))
        for call in unsafe_calls
    )

    safe_tree = ast.parse(
        "audit = get_logger('probe')\n"
        "audit.info('bounded', token_count=len(tokens), present=bool(token), "
        "error_type=type(error).__name__)\n"
    )
    safe_call = next(_log_calls(safe_tree, _logger_aliases(safe_tree)))
    assert all(_sensitive_name(value) is None for value in _payload_values(safe_call))


def test_imported_gateway_aliases_remain_inside_privacy_contract():
    tree = ast.parse(
        "from app.core.logger import get_logger as make_logger\n"
        "from app.core.logger import app_logger as audit\n"
        "make_logger('factory').warning('unsafe: {}', token)\n"
        "audit.warning('unsafe: {}', token)\n"
    )
    aliases = _logger_aliases(tree)
    calls = list(_log_calls(tree, aliases))

    assert {"make_logger", "audit"} <= aliases
    assert len(calls) == 2
    assert all(
        any(_sensitive_name(value) == "token" for value in _payload_values(call))
        for call in calls
    )


def test_sensitive_keyword_names_remain_inside_privacy_contract():
    tree = ast.parse(
        "audit = get_logger('probe')\n"
        "audit.bind(token=load_credential()).warning('unsafe')\n"
        "audit.warning('unsafe', token=load_credential())\n"
    )
    calls = list(_log_calls(tree, _logger_aliases(tree)))

    assert len(calls) == 2
    assert all(
        any(_sensitive_name(value) == "token" for value in _payload_values(call))
        for call in calls
    )
