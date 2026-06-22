"""Translate between structured JSON logic extraction and DALI2 Prolog terms.

The LLM emits a structured JSON model (facts/rules/query as term OBJECTS).
This module deterministically COMPILES that JSON into valid Prolog text,
eliminating the entire class of LLM Prolog-syntax errors. It also validates
that the program is structurally connected before sending it to DALI2.

Term object shape: {"pred": "name", "args": [arg, ...]}
  - lowercase string arg            -> atom
  - number arg                      -> numeric literal
  - string starting uppercase/'_'   -> logic variable
  - nested term object              -> compound term

Extended IR (Phase 1+):
  - {"not": <term>}                 -> \\+(Goal)
  - {"or": [<term>, ...]}           -> (A ; B ; ...)
  - {"and": [<term>, ...]}          -> (A , B , ...)
  - {"op": ">", "left": X, "right": Y} -> X > Y  (arithmetic)
  - {"findall": T, "goal": G, "bag": V} -> findall(T, G, V)
  - {"forall": Cond, "action": Act}  -> forall(Cond, Act)
  - {"if_then_else": C, "then": T, "else": E} -> (C -> T ; E)
  - {"aggregate": "count"/"sum"/"max"/"min", ...} -> aggregate goals

Rule object shape:  {"head": <term>, "body": [<term>, ...]}
"""

import re

# Operator/builtin predicate names that need not be "derivable" in validation.
_BUILTIN_PREDS = {
    ">", "<", ">=", "=<", "=:=", "=\\=", "=", "\\=", "==", "\\==",
    "is", "member", "true", "false", "not", "fail",
    "length", "append", "nth0", "nth1", "last", "msort", "sort",
    "number", "atom", "integer", "float", "var", "nonvar", "ground",
    "succ", "plus", "between", "abs", "max", "min", "mod", "div",
    "findall", "forall", "aggregate_all", "bagof", "setof",
    "write", "writeln", "format", "nl",
    "atom_string", "atom_chars", "number_chars", "term_to_atom",
    "copy_term", "functor", "arg", "=..",
}

# Infix arithmetic/comparison operators
_INFIX_OPS = {
    ">", "<", ">=", "=<", "=:=", "=\\=",
    "=", "\\=", "==", "\\==",
    "is",
}

_PLAIN_ATOM_RE = re.compile(r"[a-z][a-zA-Z0-9_]*")
_NUMERIC_RE = re.compile(r"-?\d+(\.\d+)?")


def _compile_arg(arg) -> str:
    """Compile a single argument into Prolog text."""
    if isinstance(arg, bool):
        return "true" if arg else "false"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, dict):
        # Extended IR nodes
        if "not" in arg:
            return f"\\+({_compile_term(arg['not'])})"
        if "or" in arg:
            parts = [_compile_term(t) for t in arg["or"]]
            return "(" + " ; ".join(parts) + ")"
        if "and" in arg:
            parts = [_compile_term(t) for t in arg["and"]]
            return "(" + ", ".join(parts) + ")"
        if "op" in arg:
            return _compile_infix(arg)
        if "list" in arg:
            items = [_compile_arg(i) for i in arg["list"]]
            return "[" + ", ".join(items) + "]"
        if "expr" in arg:
            return _compile_expr(arg["expr"])
        return _compile_term(arg)
    if isinstance(arg, list):
        # JSON list -> Prolog list
        items = [_compile_arg(i) for i in arg]
        return "[" + ", ".join(items) + "]"
    s = str(arg).strip()
    if not s:
        return "''"
    # Logic variable: starts with uppercase or underscore
    if s[0].isupper() or s[0] == "_":
        return s
    # Plain atom or number: pass through as-is
    if _PLAIN_ATOM_RE.fullmatch(s) or _NUMERIC_RE.fullmatch(s):
        return s
    # Arithmetic expression (contains operators): pass through
    if any(op in s for op in ['+', '-', '*', '/', ' mod ', ' div ']):
        return s
    # Anything else: quote and escape to form a valid atom
    esc = s.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{esc}'"


def _compile_infix(node: dict) -> str:
    """Compile an infix operator node: {"op": ">", "left": X, "right": Y}."""
    op = node["op"]
    left = _compile_arg(node.get("left", 0))
    right = _compile_arg(node.get("right", 0))
    return f"{left} {op} {right}"


def _compile_expr(expr) -> str:
    """Compile an arithmetic expression (nested dict or string)."""
    if isinstance(expr, (int, float)):
        return str(expr)
    if isinstance(expr, str):
        return expr
    if isinstance(expr, dict):
        if "op" in expr:
            op = expr["op"]
            left = _compile_expr(expr.get("left", 0))
            right = _compile_expr(expr.get("right", 0))
            return f"({left} {op} {right})"
        return _compile_term(expr)
    return str(expr)


def _compile_term(term) -> str:
    """Compile a term object {"pred":..,"args":..} into Prolog text.

    Also handles extended IR nodes: not, or, and, op, findall, forall,
    if_then_else, aggregate.
    """
    if isinstance(term, str):
        # Lenient fallback: already a Prolog string
        return term.strip().rstrip(".")
    if not isinstance(term, dict):
        return str(term)

    # --- Extended IR nodes ---
    if "not" in term and "pred" not in term:
        inner = _compile_term(term["not"])
        return f"\\+({inner})"

    if "or" in term and "pred" not in term:
        parts = [_compile_term(t) for t in term["or"]]
        return "(" + " ; ".join(parts) + ")"

    if "and" in term and "pred" not in term:
        parts = [_compile_term(t) for t in term["and"]]
        return "(" + ", ".join(parts) + ")"

    if "op" in term and "pred" not in term:
        return _compile_infix(term)

    if "findall" in term:
        template = _compile_arg(term["findall"])
        goal = _compile_term(term["goal"])
        bag = _compile_arg(term["bag"])
        return f"findall({template}, {goal}, {bag})"

    if "forall" in term:
        cond = _compile_term(term["forall"])
        action = _compile_term(term["action"])
        return f"forall({cond}, {action})"

    if "if_then_else" in term:
        cond = _compile_term(term["if_then_else"])
        then = _compile_term(term["then"])
        els = _compile_term(term.get("else", {"pred": "fail", "args": []}))
        return f"({cond} -> {then} ; {els})"

    if "aggregate" in term:
        return _compile_aggregate(term)

    if "list" in term and "pred" not in term:
        items = [_compile_arg(i) for i in term["list"]]
        return "[" + ", ".join(items) + "]"

    # --- Standard term ---
    pred = str(term.get("pred", "")).strip()
    args = term.get("args", []) or []
    if not pred:
        return "true"

    # Infix operators as pred
    if pred in _INFIX_OPS and len(args) == 2:
        left = _compile_arg(args[0])
        right = _compile_arg(args[1])
        return f"{left} {pred} {right}"

    if not args:
        return pred
    compiled = ", ".join(_compile_arg(a) for a in args)
    return f"{pred}({compiled})"


def _compile_aggregate(term: dict) -> str:
    """Compile aggregate operations: count, sum, max, min."""
    agg_type = term["aggregate"]
    template = _compile_arg(term.get("template", "X"))
    goal = _compile_term(term.get("goal", {"pred": "true", "args": []}))
    result = _compile_arg(term.get("result", "Result"))

    if agg_type == "count":
        return f"(findall({template}, {goal}, _Bag_), length(_Bag_, {result}))"
    elif agg_type == "sum":
        return f"(findall({template}, {goal}, _Bag_), sumlist(_Bag_, {result}))"
    elif agg_type == "max":
        return f"(findall({template}, {goal}, _Bag_), max_list(_Bag_, {result}))"
    elif agg_type == "min":
        return f"(findall({template}, {goal}, _Bag_), min_list(_Bag_, {result}))"
    else:
        return f"findall({template}, {goal}, {result})"


def _compile_rule(rule: dict) -> str:
    """Compile a rule object into `Head :- B1, B2`."""
    if isinstance(rule, str):
        return rule.strip().rstrip(".")
    head = _compile_term(rule.get("head", {}))
    body = rule.get("body", []) or []
    if not body:
        return head
    body_str = ", ".join(_compile_term(g) for g in body)
    return f"{head} :- {body_str}"


def compile_program(extraction: dict) -> dict:
    """Compile the structured extraction into Prolog text components."""
    facts = [_compile_term(f) for f in extraction.get("facts", []) or []]
    rules = [_compile_rule(r) for r in extraction.get("rules", []) or []]
    query = _compile_term(extraction.get("query", {"pred": "true", "args": []}))
    return {"facts": facts, "rules": rules, "query": query}


def build_query_event(extraction: dict) -> str:
    """Build the solve_logic event term injected into the DALI2 logic_solver."""
    prog = compile_program(extraction)
    facts_list = "[" + ", ".join(prog["facts"]) + "]"
    rules_list = "[" + ", ".join(f"({r})" for r in prog["rules"]) + "]"
    return f"solve_logic({facts_list}, {rules_list}, ({prog['query']}))"


def build_option_eval_event(extraction: dict) -> str:
    """Build a solve_logic event that evaluates all MCQ options via findall.

    Adds option_valid(Key) :- <claim> rules for each option, then queries:
        findall(K, option_valid(K), ValidOptions)

    The solution will be: valid_options([a,b,...]) listing provable options.
    """
    facts = extraction.get("facts", []) or []
    rules = extraction.get("rules", []) or []
    option_claims = extraction.get("option_claims", {})

    # Compile base facts
    compiled_facts = [_compile_term(f) for f in facts]

    # Compile base rules
    compiled_rules = [_compile_rule(r) for r in rules]

    # Add option_valid(key) :- <claim> for each option
    for key, claim in option_claims.items():
        key_atom = key.lower().strip()
        claim_compiled = _compile_term(claim)
        compiled_rules.append(f"option_valid({key_atom}) :- {claim_compiled}")

    # Wrap with findall + sort to deduplicate
    compiled_rules.append("answer(valid_options(V)) :- findall(K, option_valid(K), Raw), sort(Raw, V)")

    facts_list = "[" + ", ".join(compiled_facts) + "]"
    rules_list = "[" + ", ".join(f"({r})" for r in compiled_rules) + "]"

    # Use answer(valid_options(V)) as the query — this wraps findall result
    return f"solve_logic({facts_list}, {rules_list}, (answer(valid_options(ValidOptions))))"


def _term_signature(term):
    """Return (pred, arity) signature of a term object; None for non-dict."""
    if not isinstance(term, dict):
        return None
    # Extended IR nodes don't have a simple pred/arity signature
    if any(k in term for k in ("not", "or", "and", "op", "findall", "forall",
                                "if_then_else", "aggregate", "list")):
        if "pred" not in term:
            return None
    pred = str(term.get("pred", "")).strip()
    if not pred:
        return None
    args = term.get("args", []) or []
    return (pred, len(args))


def _collect_signatures_from_body(term) -> list:
    """Recursively collect all predicate signatures referenced in a body term."""
    if not isinstance(term, dict):
        return []
    sigs = []
    # Extended IR: recurse into sub-terms
    if "not" in term and "pred" not in term:
        sigs.extend(_collect_signatures_from_body(term["not"]))
    elif "or" in term and "pred" not in term:
        for t in term["or"]:
            sigs.extend(_collect_signatures_from_body(t))
    elif "and" in term and "pred" not in term:
        for t in term["and"]:
            sigs.extend(_collect_signatures_from_body(t))
    elif "findall" in term:
        sigs.extend(_collect_signatures_from_body(term.get("goal", {})))
    elif "forall" in term:
        sigs.extend(_collect_signatures_from_body(term.get("forall", {})))
        sigs.extend(_collect_signatures_from_body(term.get("action", {})))
    elif "if_then_else" in term:
        sigs.extend(_collect_signatures_from_body(term["if_then_else"]))
        sigs.extend(_collect_signatures_from_body(term.get("then", {})))
        sigs.extend(_collect_signatures_from_body(term.get("else", {})))
    elif "aggregate" in term:
        sigs.extend(_collect_signatures_from_body(term.get("goal", {})))
    elif "op" in term and "pred" not in term:
        pass  # arithmetic, no predicate references
    else:
        sig = _term_signature(term)
        if sig:
            sigs.append(sig)
        # Also check inside not/1 as standard pred
        if term.get("pred") == "not":
            inner_args = term.get("args", []) or []
            if inner_args and isinstance(inner_args[0], dict):
                sigs.extend(_collect_signatures_from_body(inner_args[0]))
    return sigs


def validate_program(extraction: dict) -> dict:
    """Check the program is structurally connected before sending to DALI2.

    Ensures (1) the query predicate is derivable (matches a fact or rule head),
    and (2) every rule-body predicate is reachable. Returns {"valid", "reason"}.

    Handles extended IR nodes (or, not, and, findall, aggregate, etc.)
    transparently — they are either builtins or recursively checked.
    """
    facts = extraction.get("facts", []) or []
    rules = extraction.get("rules", []) or []
    query = extraction.get("query")
    option_claims = extraction.get("option_claims")

    # MCQ path: no explicit query, but option_claims are present.
    # The query (answer(valid_options(V))) is auto-generated and always valid.
    # Instead, validate that predicates in option claims are reachable.
    if not query and not option_claims:
        return {"valid": False, "reason": "Missing 'query' field."}

    if not query and option_claims:
        # Build a synthetic "available" set that includes option_valid/1 and
        # answer/1 (auto-generated by build_option_eval_event)
        fact_sigs = {_term_signature(f) for f in facts if isinstance(f, dict)}
        head_sigs = {_term_signature(r.get("head")) for r in rules if isinstance(r, dict)}
        available = (fact_sigs | head_sigs) - {None}
        available.add(("option_valid", 1))
        available.add(("answer", 1))

        def fmt(sigs):
            return sorted(f"{p}/{a}" for (p, a) in sigs)

        # Check that each option claim's predicates are reachable
        for key, claim in option_claims.items():
            claim_sigs = _collect_signatures_from_body(claim)
            for sig in claim_sigs:
                if sig[0] in _BUILTIN_PREDS:
                    continue
                if sig not in available:
                    return {
                        "valid": False,
                        "reason": (
                            f"Option claim '{key}' references predicate '{sig[0]}/{sig[1]}' "
                            f"which is not a fact or rule head. Every claim predicate must be "
                            f"reachable. Available: {fmt(available)}. "
                            f"HINTS: Add a rule with head '{sig[0]}' whose body tests the option. "
                            f"If the option should NOT be derivable, use body [{{\"pred\": \"fail\", \"args\": []}}]."
                        ),
                    }

        # Still check rule-body predicates (same as below)
        for r in rules:
            if not isinstance(r, dict):
                continue
            body = r.get("body", []) or []
            body_sigs = []
            for g in body:
                body_sigs.extend(_collect_signatures_from_body(g))

            for sig in body_sigs:
                if sig[0] in _BUILTIN_PREDS:
                    continue
                if sig not in available:
                    return {
                        "valid": False,
                        "reason": (
                            f"Body predicate '{sig[0]}/{sig[1]}' is not a fact or rule head. "
                            f"Every body predicate must be reachable. Available: {fmt(available)}. "
                            f"HINTS: Either (1) add '{sig[0]}' as a fact in the facts array "
                            f"(e.g. {{\"pred\": \"{sig[0]}\", \"args\": []}}), or "
                            f"(2) if this option should NOT be derivable, replace the entire "
                            f"rule body with [{{\"pred\": \"fail\", \"args\": []}}]."
                        ),
                    }

        # Check for self-referential option_valid rules (infinite recursion risk)
        for r in rules:
            if not isinstance(r, dict):
                continue
            head = r.get("head")
            if not isinstance(head, dict):
                continue
            head_pred = str(head.get("pred", "")).strip()
            if head_pred == "option_valid":
                body = r.get("body", []) or []
                for g in body:
                    g_sigs = _collect_signatures_from_body(g)
                    for gs in g_sigs:
                        if gs[0] == "option_valid":
                            return {
                                "valid": False,
                                "reason": (
                                    f"Rule 'option_valid' references 'option_valid' in its body. "
                                    f"This creates infinite recursion. Each option_valid(key) rule "
                                    f"must depend on OTHER predicates (facts, helper predicates), "
                                    f"never on option_valid itself."
                                ),
                            }

        return {"valid": True, "reason": ""}

    # Extended IR queries (or, findall, aggregate...) are valid without a head match
    if isinstance(query, dict) and not query.get("pred"):
        if any(k in query for k in ("not", "or", "and", "findall", "forall",
                                     "if_then_else", "aggregate")):
            return {"valid": True, "reason": ""}
        return {"valid": False, "reason": "Missing or malformed 'query' term object."}

    fact_sigs = {_term_signature(f) for f in facts if isinstance(f, dict)}
    head_sigs = {_term_signature(r.get("head")) for r in rules if isinstance(r, dict)}
    available = (fact_sigs | head_sigs) - {None}

    def fmt(sigs):
        return sorted(f"{p}/{a}" for (p, a) in sigs)

    q_sig = _term_signature(query)
    if q_sig and q_sig not in available:
        return {
            "valid": False,
            "reason": (
                f"Query '{q_sig[0]}/{q_sig[1]}' is not derivable: it must match a "
                f"fact or a rule head. Available predicates: {fmt(available)}."
            ),
        }

    # Every rule-body predicate must be reachable (skip builtins/operators).
    for r in rules:
        if not isinstance(r, dict):
            continue
        body = r.get("body", []) or []
        body_sigs = []
        for g in body:
            body_sigs.extend(_collect_signatures_from_body(g))

        for sig in body_sigs:
            if sig[0] in _BUILTIN_PREDS:
                continue
            if sig not in available:
                return {
                    "valid": False,
                    "reason": (
                        f"Body predicate '{sig[0]}/{sig[1]}' is not a fact or rule head. "
                        f"Every body predicate must be reachable. Available: {fmt(available)}."
                    ),
                }

    return {"valid": True, "reason": ""}


def _extract_paren_content(s: str, prefix: str) -> str | None:
    """Extract balanced-parenthesis content after a functor prefix.

    Given s = "solution(recommended(guidare))" and prefix = "solution(",
    returns "recommended(guidare)".  Handles arbitrarily nested parentheses.
    Returns None if the string does not start with prefix or parentheses
    are unbalanced.
    """
    if not s.startswith(prefix):
        return None
    depth = 0
    start = len(prefix) - 1  # position of the opening '('
    for i, ch in enumerate(s[len(prefix) - 1:], start=len(prefix) - 1):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return s[len(prefix):i].strip()
    return None  # unbalanced


def parse_dali2_result(beliefs: list) -> dict:
    """Parse DALI2 agent beliefs to extract logic solving results.

    Beliefs come from the API as list of dicts [{"agent":..,"belief":..}] or
    plain strings. Looks for solution/1 and logic_explanation/1.
    """
    result = {"solved": False, "solution": None, "bindings": [], "explanation": None}

    for entry in beliefs:
        belief = entry.get("belief", entry) if isinstance(entry, dict) else str(entry)
        belief = str(belief).strip()

        if belief.startswith("solution("):
            val = _extract_paren_content(belief, "solution(")
            if val is not None and val != "no_solution":
                result["solved"] = True
                result["solution"] = val
        elif belief.startswith("logic_explanation("):
            val = _extract_paren_content(belief, "logic_explanation(")
            if val is not None:
                result["explanation"] = val

    return result


def parse_dali2_logs(logs: list) -> dict:
    """Parse DALI2 agent logs to extract solving results.

    In distributed mode the beliefs API returns empty because beliefs live
    in the agent process memory, not the server's.  Logs ARE synced via
    Redis, so we can extract the solution from log messages like:
      "Belief added: solution(recommended(guidare))"
      "=== SOLUTION FOUND: recommended(guidare) ==="
      "Belief added: solution(no_solution)"
      "=== NO SOLUTION (query failed) ==="
    """
    result = {"solved": False, "solution": None, "bindings": [], "explanation": None}

    for entry in logs:
        msg = entry.get("message", entry) if isinstance(entry, dict) else str(entry)
        msg = str(msg).strip()

        # Pattern: "Belief added: solution(...)"
        if "Belief added: solution(" in msg:
            idx = msg.index("solution(")
            val = _extract_paren_content(msg[idx:], "solution(")
            if val is not None and val != "no_solution":
                result["solved"] = True
                result["solution"] = val

        # Pattern: "=== SOLUTION FOUND: X ==="
        elif "SOLUTION FOUND:" in msg:
            prefix = "SOLUTION FOUND: "
            idx = msg.index(prefix) + len(prefix)
            rest = msg[idx:].rstrip(" =")
            rest = rest.rstrip("=").strip()
            if rest and rest != "no_solution":
                result["solved"] = True
                result["solution"] = rest

        # Pattern: "=== NO SOLUTION (query failed) ==="
        elif "NO SOLUTION" in msg:
            result["solved"] = False

        # Pattern: "Belief added: logic_explanation(...)"
        if "Belief added: logic_explanation(" in msg:
            idx = msg.index("logic_explanation(")
            val = _extract_paren_content(msg[idx:], "logic_explanation(")
            if val is not None:
                result["explanation"] = val

    return result
