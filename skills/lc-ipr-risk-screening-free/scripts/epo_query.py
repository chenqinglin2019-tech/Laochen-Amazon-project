"""Pure EPO OPS CQL compilation and validation helpers."""
from __future__ import annotations
import re

REVISION = "ops-cql-v1"
_FIELDS = {"ta", "pa", "in", "ipc", "cpc"}
_OPS = {"AND", "OR", "NOT"}
_PREC = {"OR": 1, "AND": 2, "NOT": 3}

def _tokens(value: str) -> list[str]:
    if not isinstance(value, str) or not value.strip(): raise ValueError("EPO_QUERY_EMPTY")
    if any(c in value for c in "?#") or re.search(r"\bprox(?:/|\b)", value, re.I):
        raise ValueError("EPO_QUERY_OPERATOR_UNSUPPORTED")
    matches = list(re.finditer(r'"[^"\r\n]+"|\(|\)|\b(?:AND|OR|NOT)\b|[^\s()]+', value, re.I))
    cursor, result = 0, []
    for match in matches:
        if value[cursor:match.start()].strip(): raise ValueError("EPO_QUERY_SYNTAX_INVALID")
        token = match.group(); result.append(token.upper() if token.upper() in _OPS else token); cursor = match.end()
    if value[cursor:].strip() or not result: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
    return result

def _term(token: str) -> str:
    if token.startswith('"'):
        if not token[1:-1].strip(): raise ValueError("EPO_QUERY_PHRASE_INVALID")
        return token
    if any(c in token for c in '=<>[]{};\\'): raise ValueError("EPO_QUERY_TERM_INVALID")
    if "*" in token and (token.count("*") != 1 or not token.endswith("*") or len(token[:-1]) < 3):
        raise ValueError("EPO_QUERY_TRUNCATION_INVALID")
    return token

def _parse(value: str):
    output, operators, expect = [], [], True
    for token in _tokens(value):
        if token == "(":
            if not expect: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
            operators.append(token)
        elif token == ")":
            if expect: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
            while operators and operators[-1] != "(": output.append(operators.pop())
            if not operators: raise ValueError("EPO_QUERY_PARENTHESES_INVALID")
            operators.pop(); expect = False
        elif token in _OPS:
            if token == "NOT" and not expect: raise ValueError("EPO_QUERY_NOT_REQUIRES_OPERATOR")
            if token != "NOT" and expect: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
            while operators and operators[-1] in _OPS and _PREC[operators[-1]] >= _PREC[token]: output.append(operators.pop())
            operators.append(token); expect = True
        else:
            if not expect:
                while operators and operators[-1] in _OPS and _PREC[operators[-1]] >= _PREC["AND"]: output.append(operators.pop())
                operators.append("AND")
            output.append(_term(token)); expect = False
    if expect: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
    while operators:
        if operators[-1] == "(": raise ValueError("EPO_QUERY_PARENTHESES_INVALID")
        output.append(operators.pop())
    stack = []
    for token in output:
        if token == "NOT":
            if not stack: raise ValueError("EPO_QUERY_NOT_REQUIRES_POSITIVE_TERM")
            stack.append(("NOT", stack.pop()))
        elif token in {"AND", "OR"}:
            if len(stack) < 2: raise ValueError("EPO_QUERY_SYNTAX_INVALID")
            right, left = stack.pop(), stack.pop()
            stack.append(("AND_NOT", left, right[1]) if token == "AND" and right[0] == "NOT" else (token, left, right))
        else: stack.append(("TERM", token))
    if len(stack) != 1 or stack[0][0] == "NOT": raise ValueError("EPO_QUERY_NOT_REQUIRES_POSITIVE_TERM")
    return stack[0]

def _render(node, field: str) -> str:
    if node[0] == "TERM": return f"{field}={node[1]}" if node[1].startswith('"') else f'{field}="{node[1]}"'
    if node[0] == "AND_NOT": return f"({_render(node[1], field)} and not {_render(node[2], field)})"
    return f"({_render(node[1], field)} {node[0].lower()} {_render(node[2], field)})"

def compile_ops_query(*, countries: list[str], field: str, value: str, strategy: str) -> str:
    if field not in _FIELDS: raise ValueError("EPO_QUERY_FIELD_UNSUPPORTED")
    if not countries or any(not re.fullmatch(r"[A-Z]{2}", c) for c in countries): raise ValueError("EPO_QUERY_COUNTRY_INVALID")
    scope = " or ".join(f"pn={c}" for c in dict.fromkeys(countries))
    if strategy == "phrase":
        escaped = value.replace("\\", " ").replace('"', " ").strip()
        if not escaped: raise ValueError("EPO_QUERY_EMPTY")
        expression = f'{field}="{escaped}"'
    elif strategy == "boolean": expression = _render(_parse(value), field)
    else: raise ValueError("EPO_QUERY_STRATEGY_UNSUPPORTED")
    return f"({scope}) and ({expression})"

def validate_compiled_query(query: str) -> None:
    if not isinstance(query, str) or not query.strip(): raise ValueError("EPO_QUERY_EMPTY")
    if re.search(r"\bpn=[A-Z]{2}[?*#]", query): raise ValueError("EPO_QUERY_TRUNCATION_INVALID")
    if any(c in query for c in "?#") or re.search(r"\bprox(?:/|\b)", query, re.I): raise ValueError("EPO_QUERY_OPERATOR_UNSUPPORTED")
    depth = 0
    for char in query:
        depth += char == "("; depth -= char == ")"
        if depth < 0: raise ValueError("EPO_QUERY_PARENTHESES_INVALID")
    if depth: raise ValueError("EPO_QUERY_PARENTHESES_INVALID")
