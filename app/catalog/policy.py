"""A deliberately tiny ODRL evaluator for the demo.

ODRL defines the vocabulary but not a standard evaluation algorithm, so this implements a
minimal profile: actions (use covers everything), leftOperands purpose/spatial, operators
eq/neq/isAnyOf/isNoneOf. The catalogue *states* the terms; enforcement is a connector's job.
"""

DUTY_LABELS = {
    "attribute": "attribute the source",
    "inform": "inform the provider of your use",
    "obtainConsent": "request access from the provider",
    "compensate": "pay the provider",
}


def _check(constraint, request):
    """True / False, or None when the request does not say (e.g. no purpose given)."""
    value = request.get(constraint["leftOperand"])
    if not value:
        return None
    rights, op = constraint["rightOperand"], constraint["operator"]
    if op in ("eq", "isAnyOf"):
        return value in rights
    if op in ("neq", "isNoneOf"):
        return value not in rights
    return None  # unsupported operator: can't decide


def _describe(c):
    return f'{c["leftOperand"]} {c["operator"]} {", ".join(c["rightOperand"])}'


def _action_applies(rule_action, requested):
    return rule_action in (requested, "use")


def evaluate(policy, request):
    """request: {"action": "use", "purpose": "commercial", "spatial": "NL"}.

    Returns {"status", "reason", "duties"} where status is one of
    allowed | allowed_with_duties | request_access | conditional | prohibited | not_permitted.
    """
    if not policy:
        return {"status": "not_permitted", "reason": "No machine-readable policy published", "duties": []}
    action = request.get("action") or "use"

    for rule in policy["prohibitions"]:
        if not _action_applies(rule["action"], action):
            continue
        results = [_check(c, request) for c in rule["constraints"]]
        if all(r is True for r in results):
            why = "; ".join(_describe(c) for c in rule["constraints"])
            reason = f"Prohibited: {rule['action']}" + (f" where {why}" if why else " (no conditions)")
            return {"status": "prohibited", "reason": reason, "duties": []}

    open_questions, failed = [], []
    for rule in policy["permissions"]:
        if not _action_applies(rule["action"], action):
            continue
        results = [_check(c, request) for c in rule["constraints"]]
        if any(r is False for r in results):
            failed += [_describe(c) for c, r in zip(rule["constraints"], results) if r is False]
            continue
        unknown = [c for c, r in zip(rule["constraints"], results) if r is None]
        if unknown:
            open_questions += [_describe(c) for c in unknown]
            continue
        duties = [DUTY_LABELS.get(d, d) for d in rule["duties"]]
        conds = "; ".join(_describe(c) for c in rule["constraints"])
        base = f"Permitted: {rule['action']}" + (f" where {conds}" if conds else "")
        if "obtainConsent" in rule["duties"]:
            return {"status": "request_access", "reason": base + " — metadata is open, payload needs approval",
                    "duties": duties}
        return {"status": "allowed_with_duties" if duties else "allowed", "reason": base, "duties": duties}

    if open_questions:
        return {"status": "conditional",
                "reason": "Depends on your request: " + "; ".join(sorted(set(open_questions))), "duties": []}
    if failed:
        return {"status": "not_permitted",
                "reason": "Your request falls outside the offer: requires " + "; ".join(sorted(set(failed))), "duties": []}
    return {"status": "not_permitted", "reason": f"No permission covers '{action}' for this request", "duties": []}
