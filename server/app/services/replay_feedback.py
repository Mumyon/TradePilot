"""F-05 per-rule feedback from saved ON/OFF assessments, after a run ends."""

from .feedback import ADVICE


def breakdown(state):
    orders = {o["check_id"]: o for o in state["orders"]}
    result = []
    for code, (title, advice) in ADVICE.items():
        hits, exempt, unavailable = [], 0, 0
        for check in state["checks"]:
            item = next(
                (i for i in check["shadow"]["behavior"]["items"] if i["code"] == code),
                None,
            )
            if item is None or item["status"] == "unavailable":
                unavailable += 1
            elif item["status"] == "hit":
                hits.append(check)
            elif item["status"] == "exempt":
                exempt += 1
        shown = [c for c in hits if state["pilot_enabled"] and c["presented_at"] and c["allowed"]]
        deferred = sum(c["decision"] == "deferred" for c in shown)
        submitted = sum(c["decision"] == "submitted" for c in shown)
        result.append(
            dict(
                code=code,
                title=title,
                detected=len(hits),
                exempt=exempt,
                unavailable=unavailable,
                blocked=sum(not c["allowed"] for c in hits),
                presented=len(shown),
                deferred_after_presentation=deferred,
                submitted_after_presentation=submitted,
                closed_after_presentation=sum(c["decision"] == "closed" for c in shown),
                unresolved_after_presentation=sum(
                    c["decision"] in ("pending", "expired", "unresolved_at_finish") for c in shown
                ),
                submitted=sum(c["decision"] == "submitted" for c in hits),
                filled=sum(orders.get(c["check_id"], {}).get("status") == "filled" for c in hits),
                cancelled=sum(
                    orders.get(c["check_id"], {}).get("status") == "cancelled" for c in hits
                ),
                defer_rate=deferred / (deferred + submitted) if deferred + submitted else None,
                advice=advice if hits else None,
            )
        )
    return result
