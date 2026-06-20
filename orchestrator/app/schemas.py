"""Reasoning schema definitions and program generation.

Each schema defines fixed Prolog rules that are correct and connected by
construction.  The LLM only fills in flat facts (slots) — never rules.

Supported schemas
-----------------
- option_selection : Which option achieves the goal?
- classification   : Is X a Y? (category membership via chains)
- comparison       : Which item is best/worst by criterion?
- deduction        : Logical implication / biconditional (if-then, iff)
- freeform         : Generic first-order logic (LLM specifies facts+rules in JSON)
- composed         : Multiple micro-theories combined
"""

from __future__ import annotations

from app.theories import build_from_theory, compose_theories


# ---------------------------------------------------------------------------
# Schema builders — each returns (program_dict, error_string)
# ---------------------------------------------------------------------------

def _build_option_selection(slots: dict) -> tuple[dict | None, str]:
    options = slots.get("options", [])
    effects = slots.get("effects", [])
    goal = slots.get("goal", "")

    if not options:
        return None, "Slot 'options' is empty — list the available choices."
    if not effects:
        return None, "Slot 'effects' is empty — describe what each option produces."
    if not goal:
        return None, "Slot 'goal' is empty — specify the required outcome state."

    facts: list[dict] = []
    for opt in options:
        facts.append({"pred": "option", "args": [opt]})
    for eff in effects:
        if isinstance(eff, dict):
            facts.append({"pred": "effect", "args": [eff["option"], eff["state"]]})
        elif isinstance(eff, list) and len(eff) == 2:
            facts.append({"pred": "effect", "args": eff})
    facts.append({"pred": "goal", "args": [goal]})

    rules = [
        {
            "head": {"pred": "recommended", "args": ["O"]},
            "body": [
                {"pred": "option", "args": ["O"]},
                {"pred": "goal", "args": ["G"]},
                {"pred": "effect", "args": ["O", "G"]},
            ],
        }
    ]

    query = {"pred": "recommended", "args": ["X"]}
    return {"facts": facts, "rules": rules, "query": query}, ""


def _build_classification(slots: dict) -> tuple[dict | None, str]:
    instances = slots.get("instances", [])
    hierarchy = slots.get("hierarchy", [])
    query_entity = slots.get("query_entity", "X")
    query_class = slots.get("query_class", "X")

    if not instances and not hierarchy:
        return None, "Provide at least 'instances' or 'hierarchy' data."

    facts: list[dict] = []
    for inst in instances:
        if isinstance(inst, list) and len(inst) == 2:
            facts.append({"pred": "instance", "args": inst})
        elif isinstance(inst, dict):
            facts.append({"pred": "instance", "args": [inst["entity"], inst["class"]]})
    for hier in hierarchy:
        if isinstance(hier, list) and len(hier) == 2:
            facts.append({"pred": "subclass", "args": hier})
        elif isinstance(hier, dict):
            facts.append({"pred": "subclass", "args": [hier["sub"], hier["super"]]})

    rules = [
        {
            "head": {"pred": "is_a", "args": ["X", "C"]},
            "body": [{"pred": "instance", "args": ["X", "C"]}],
        },
        {
            "head": {"pred": "is_a", "args": ["X", "C"]},
            "body": [
                {"pred": "instance", "args": ["X", "Sub"]},
                {"pred": "subclass_of", "args": ["Sub", "C"]},
            ],
        },
        {
            "head": {"pred": "subclass_of", "args": ["A", "B"]},
            "body": [{"pred": "subclass", "args": ["A", "B"]}],
        },
        {
            "head": {"pred": "subclass_of", "args": ["A", "C"]},
            "body": [
                {"pred": "subclass", "args": ["A", "B"]},
                {"pred": "subclass_of", "args": ["B", "C"]},
            ],
        },
    ]

    query = {"pred": "is_a", "args": [query_entity, query_class]}
    return {"facts": facts, "rules": rules, "query": query}, ""


def _build_comparison(slots: dict) -> tuple[dict | None, str]:
    """Comparison via dominance pairs (no arithmetic builtins needed)."""
    items = slots.get("items", [])
    dominates = slots.get("dominates", [])

    if not items:
        return None, "Slot 'items' is empty — list the items to compare."
    if not dominates:
        return None, "Slot 'dominates' is empty — specify [winner, loser] pairs."

    facts: list[dict] = []
    for item in items:
        facts.append({"pred": "item", "args": [item]})
    for dom in dominates:
        if isinstance(dom, list) and len(dom) == 2:
            facts.append({"pred": "dominates", "args": dom})
        elif isinstance(dom, dict):
            facts.append({"pred": "dominates", "args": [dom["winner"], dom["loser"]]})

    rules = [
        {
            "head": {"pred": "beaten", "args": ["X"]},
            "body": [{"pred": "dominates", "args": ["Y", "X"]}],
        },
        {
            "head": {"pred": "best", "args": ["X"]},
            "body": [
                {"pred": "item", "args": ["X"]},
                {"pred": "not", "args": [{"pred": "beaten", "args": ["X"]}]},
            ],
        },
    ]

    query = {"pred": "best", "args": ["X"]}
    return {"facts": facts, "rules": rules, "query": query}, ""


def _build_deduction(slots: dict) -> tuple[dict | None, str]:
    """Deduction via implications and biconditionals.

    Slots:
        premises    — list of atoms that are given as true: ["raining", ...]
        implications — list of {"if": "A", "then": "B"} (A → B)
        biconditionals — list of {"left": "A", "right": "B"} (A ↔ B)
        query       — the atom to prove
    """
    premises = slots.get("premises", [])
    implications = slots.get("implications", [])
    biconditionals = slots.get("biconditionals", [])
    query_atom = slots.get("query", "")

    if not query_atom:
        return None, "Slot 'query' is empty — specify what atom to prove."
    if not premises and not implications and not biconditionals:
        return None, "Provide at least 'premises', 'implications', or 'biconditionals'."

    facts: list[dict] = []
    for prem in premises:
        facts.append({"pred": prem, "args": []})

    rules: list[dict] = []
    for impl in implications:
        if isinstance(impl, dict):
            cond = impl.get("if", "")
            concl = impl.get("then", "")
        elif isinstance(impl, list) and len(impl) == 2:
            cond, concl = impl
        else:
            continue
        if not cond or not concl:
            continue
        rules.append({
            "head": {"pred": concl, "args": []},
            "body": [{"pred": cond, "args": []}],
        })

    for bicon in biconditionals:
        if isinstance(bicon, dict):
            left = bicon.get("left", "")
            right = bicon.get("right", "")
        elif isinstance(bicon, list) and len(bicon) == 2:
            left, right = bicon
        else:
            continue
        if not left or not right:
            continue
        # A ↔ B  =>  two rules: A :- B  and  B :- A
        rules.append({
            "head": {"pred": right, "args": []},
            "body": [{"pred": left, "args": []}],
        })
        rules.append({
            "head": {"pred": left, "args": []},
            "body": [{"pred": right, "args": []}],
        })

    query = {"pred": query_atom, "args": []}
    return {"facts": facts, "rules": rules, "query": query}, ""


# ---------------------------------------------------------------------------
# Schema: Freeform FOL
# ---------------------------------------------------------------------------

def _build_freeform(slots: dict) -> tuple[dict | None, str]:
    """Generic first-order logic: LLM specifies facts, rules, and query in JSON.

    Slots:
        facts  — list of term objects: [{"pred": "parent", "args": ["tom", "bob"]}, ...]
        rules  — list of rule objects: [{"head": <term>, "body": [<term>, ...]}, ...]
        query  — term object: {"pred": "grandparent", "args": ["tom", "X"]}
    """
    facts = slots.get("facts", [])
    rules = slots.get("rules", [])
    query = slots.get("query")

    if not query:
        return None, "Slot 'query' is required (term object for the goal)."
    if not facts and not rules:
        return None, "Provide at least 'facts' or 'rules'."

    return {"facts": facts, "rules": rules, "query": query}, ""


# ---------------------------------------------------------------------------
# Schema: Composed (multiple micro-theories)
# ---------------------------------------------------------------------------

def _build_composed(slots: dict) -> tuple[dict | None, str]:
    """Compose multiple micro-theories into a single program.

    Slots:
        theories — list of {"theory": name, "slots": {...}, "query": optional_override}
        query    — optional override for the final query (term object)
    """
    theories = slots.get("theories", [])
    override_query = slots.get("query")

    if not theories:
        return None, "Slot 'theories' is required (list of theory specs)."

    program, err = compose_theories(theories)
    if program is None:
        return None, err

    if override_query:
        program["query"] = override_query

    return program, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SCHEMA_BUILDERS: dict[str, callable] = {
    "option_selection": _build_option_selection,
    "classification": _build_classification,
    "comparison": _build_comparison,
    "deduction": _build_deduction,
    "freeform": _build_freeform,
    "composed": _build_composed,
}


def build_from_schema(schema_name: str, slots: dict) -> tuple[dict | None, str]:
    """Build a complete logic program from a schema name and slot values.

    Returns ``(program, error)``.  ``program`` is a dict with keys
    ``facts``, ``rules``, ``query`` (term objects ready for
    ``compile_program``), or ``None`` on error.  ``error`` is an empty
    string on success.
    """
    builder = SCHEMA_BUILDERS.get(schema_name)
    if builder is None:
        return None, (
            f"Unknown schema '{schema_name}'. "
            f"Use one of: {', '.join(SCHEMA_BUILDERS)}."
        )
    return builder(slots)


def available_schemas() -> list[str]:
    """Return the list of supported schema names."""
    return list(SCHEMA_BUILDERS)
