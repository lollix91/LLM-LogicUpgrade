"""Enhanced program validation: groundness, type-checking, cycle detection, repair hints.

This module extends the basic connectivity check in translator.py with deeper
static analysis to catch common LLM errors before sending to DALI2.
"""

from __future__ import annotations


def validate_enhanced(extraction: dict) -> dict:
    """Run all enhanced validation checks on a logic program.

    Returns {"valid": bool, "reason": str, "warnings": list[str], "hints": list[str]}.
    """
    facts = extraction.get("facts", []) or []
    rules = extraction.get("rules", []) or []
    query = extraction.get("query")

    warnings = []
    hints = []

    # --- Check 1: Arity consistency ---
    arity_result = _check_arity_consistency(facts, rules, query)
    if not arity_result["valid"]:
        return {**arity_result, "warnings": warnings, "hints": hints}
    warnings.extend(arity_result.get("warnings", []))

    # --- Check 2: Variable safety (every head variable appears in body) ---
    safety_result = _check_variable_safety(rules)
    if not safety_result["valid"]:
        return {**safety_result, "warnings": warnings, "hints": hints}
    warnings.extend(safety_result.get("warnings", []))
    hints.extend(safety_result.get("hints", []))

    # --- Check 3: Cycle detection (warn, don't reject — cycles are valid with base cases) ---
    cycle_result = _check_cycles(rules)
    warnings.extend(cycle_result.get("warnings", []))
    hints.extend(cycle_result.get("hints", []))

    # --- Check 4: Query groundness potential ---
    ground_result = _check_query_groundness(facts, rules, query)
    warnings.extend(ground_result.get("warnings", []))

    return {"valid": True, "reason": "", "warnings": warnings, "hints": hints}


def _get_pred_name(term) -> str:
    """Get predicate name from a term dict."""
    if isinstance(term, dict) and "pred" in term:
        return term["pred"]
    return ""


def _get_arity(term) -> int:
    """Get arity from a term dict."""
    if isinstance(term, dict):
        args = term.get("args", []) or []
        return len(args)
    return 0


def _extract_variables(term, vars_set: set = None) -> set:
    """Extract all variable names from a term (recursively)."""
    if vars_set is None:
        vars_set = set()

    if isinstance(term, str):
        s = term.strip()
        if s and (s[0].isupper() or s[0] == "_") and s != "_":
            vars_set.add(s)
    elif isinstance(term, dict):
        # Extended IR nodes
        if "not" in term and "pred" not in term:
            _extract_variables(term["not"], vars_set)
        elif "or" in term and "pred" not in term:
            for t in term["or"]:
                _extract_variables(t, vars_set)
        elif "and" in term and "pred" not in term:
            for t in term["and"]:
                _extract_variables(t, vars_set)
        elif "op" in term and "pred" not in term:
            _extract_variables(term.get("left"), vars_set)
            _extract_variables(term.get("right"), vars_set)
        elif "findall" in term:
            _extract_variables(term.get("goal"), vars_set)
            _extract_variables(term.get("findall"), vars_set)
            _extract_variables(term.get("bag"), vars_set)
        elif "forall" in term:
            _extract_variables(term.get("forall"), vars_set)
            _extract_variables(term.get("action"), vars_set)
        elif "pred" in term:
            for arg in (term.get("args", []) or []):
                _extract_variables(arg, vars_set)
    elif isinstance(term, list):
        for item in term:
            _extract_variables(item, vars_set)

    return vars_set


def _check_arity_consistency(facts: list, rules: list, query) -> dict:
    """Check that predicates are used with consistent arity throughout."""
    pred_arities: dict[str, set[int]] = {}

    def record(term):
        if not isinstance(term, dict) or "pred" not in term:
            return
        pred = term["pred"]
        arity = len(term.get("args", []) or [])
        if pred not in pred_arities:
            pred_arities[pred] = set()
        pred_arities[pred].add(arity)

    # Record all facts
    for f in facts:
        record(f)

    # Record rule heads and bodies
    for r in rules:
        if isinstance(r, dict):
            record(r.get("head", {}))
            for g in (r.get("body", []) or []):
                record(g)

    # Record query
    record(query)

    # Check for inconsistencies
    warnings = []
    for pred, arities in pred_arities.items():
        if len(arities) > 1:
            return {
                "valid": False,
                "reason": (
                    f"Predicate '{pred}' is used with inconsistent arities: "
                    f"{sorted(arities)}. Each predicate must always have the same "
                    f"number of arguments."
                ),
                "warnings": warnings,
            }

    return {"valid": True, "reason": "", "warnings": warnings}


def _check_variable_safety(rules: list) -> dict:
    """Check variable safety: head-only variables that don't appear in body are suspicious.

    In Prolog, a variable in the head that doesn't appear in the body means
    the rule is valid for ANY value of that variable — which is sometimes
    intentional (generating all solutions) but often an LLM mistake.
    """
    warnings = []
    hints = []

    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        head = r.get("head", {})
        body = r.get("body", []) or []

        head_vars = _extract_variables(head)
        body_vars = set()
        for g in body:
            _extract_variables(g, body_vars)

        # Variables in head but not in body (excluding anonymous _)
        unsafe = {v for v in head_vars - body_vars if v != "_" and not v.startswith("_")}
        if unsafe:
            head_pred = _get_pred_name(head)
            warnings.append(
                f"Rule {i+1} ({head_pred}): variables {unsafe} appear in head "
                f"but not in body — they will match anything."
            )
            hints.append(
                f"For rule '{head_pred}': ensure variables {unsafe} also appear "
                f"in at least one body goal to constrain them."
            )

    return {"valid": True, "reason": "", "warnings": warnings, "hints": hints}


def _check_cycles(rules: list) -> dict:
    """Detect recursive cycles and verify base cases exist.

    A cycle without a base case will cause infinite recursion in DALI2.
    """
    warnings = []
    hints = []

    # Build dependency graph: head_pred -> set of body_preds
    deps: dict[str, set[str]] = {}
    head_preds: set[str] = set()

    for r in rules:
        if not isinstance(r, dict):
            continue
        head = r.get("head", {})
        body = r.get("body", []) or []
        head_pred = _get_pred_name(head)
        if not head_pred:
            continue
        head_preds.add(head_pred)
        if head_pred not in deps:
            deps[head_pred] = set()
        for g in body:
            body_pred = _get_pred_name(g)
            if body_pred:
                deps[head_pred].add(body_pred)

    # Detect direct recursion (pred calls itself in body)
    for pred, body_preds in deps.items():
        if pred in body_preds:
            # Check if there's a base case (another rule for same pred without self-reference)
            has_base = False
            for r in rules:
                if not isinstance(r, dict):
                    continue
                h = _get_pred_name(r.get("head", {}))
                if h == pred:
                    body = r.get("body", []) or []
                    body_pred_names = {_get_pred_name(g) for g in body}
                    if pred not in body_pred_names:
                        has_base = True
                        break
            if not has_base:
                warnings.append(
                    f"Predicate '{pred}' is recursive but has no apparent base case. "
                    f"This may cause infinite recursion."
                )
                hints.append(
                    f"Add a non-recursive rule for '{pred}' (a base case), "
                    f"e.g., a fact or a rule whose body doesn't call '{pred}'."
                )

    # Detect mutual recursion (A -> B -> A)
    for pred in head_preds:
        visited = set()
        stack = [pred]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for dep in deps.get(current, set()):
                if dep == pred and current != pred:
                    warnings.append(
                        f"Mutual recursion detected: '{pred}' -> ... -> '{current}' -> '{pred}'. "
                        f"Ensure there's a termination condition."
                    )
                    break
                if dep not in visited:
                    stack.append(dep)

    return {"warnings": warnings, "hints": hints}


def _check_query_groundness(facts: list, rules: list, query) -> dict:
    """Check if the query can potentially produce ground (concrete) bindings.

    A query with all variables and no matching facts/rules with ground args
    might return very generic results.
    """
    warnings = []

    if not isinstance(query, dict) or "pred" not in query:
        return {"warnings": warnings}

    query_vars = _extract_variables(query)
    if not query_vars:
        return {"warnings": warnings}  # Ground query, fine

    # Check if there are facts that can ground the query variables
    query_pred = query.get("pred", "")
    query_arity = len(query.get("args", []) or [])

    has_grounding_facts = False
    for f in facts:
        if isinstance(f, dict) and f.get("pred") == query_pred:
            if len(f.get("args", []) or []) == query_arity:
                has_grounding_facts = True
                break

    has_grounding_rules = False
    for r in rules:
        if isinstance(r, dict):
            head = r.get("head", {})
            if isinstance(head, dict) and head.get("pred") == query_pred:
                if len(head.get("args", []) or []) == query_arity:
                    has_grounding_rules = True
                    break

    if not has_grounding_facts and not has_grounding_rules:
        warnings.append(
            f"Query '{query_pred}/{query_arity}' has variables but no matching "
            f"facts or rules — it cannot produce bindings."
        )

    return {"warnings": warnings}


def generate_repair_hints(validation_result: dict, extraction: dict) -> list[str]:
    """Generate specific repair hints based on validation failures.

    Called when validation fails to produce actionable feedback for the LLM retry loop.
    """
    hints = list(validation_result.get("hints", []))
    reason = validation_result.get("reason", "")

    if "not derivable" in reason:
        query = extraction.get("query", {})
        query_pred = query.get("pred", "") if isinstance(query, dict) else ""
        hints.append(
            f"Add a rule with head '{query_pred}' or add it as a fact. "
            f"The query must match an existing predicate."
        )

    if "not a fact or rule head" in reason:
        # Extract the missing predicate from the reason
        import re
        match = re.search(r"'(\w+)/(\d+)'", reason)
        if match:
            pred, arity = match.group(1), match.group(2)
            hints.append(
                f"Add '{pred}' as either a fact (with {arity} arguments) or "
                f"define a rule whose head is '{pred}/{arity}'."
            )

    if "inconsistent arities" in reason:
        hints.append(
            "Ensure every use of the same predicate name has the same number "
            "of arguments. Check facts, rules, and query for typos."
        )

    return hints
