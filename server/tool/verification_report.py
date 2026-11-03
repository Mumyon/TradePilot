"""Convert pytest JUnit evidence to labeled scenario metrics; no performance fabrication."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("junit")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cases = ElementTree.parse(args.junit).getroot().findall(".//testcase")
    matrices = defaultdict(lambda: dict(tp=0, fp=0, tn=0, fn=0))
    for case in cases:
        props = {p.get("name"): p.get("value") for p in case.findall("./properties/property")}
        if "behavior_code" not in props:
            continue
        expected, actual = props["expected_warning"] == "True", props["observed_warning"] == "True"
        key = ("tp" if actual else "fn") if expected else ("fp" if actual else "tn")
        matrices[props["behavior_code"]][key] += 1
    for m in matrices.values():
        m["precision"] = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else None
        m["recall"] = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else None
        m["false_positive_rate"] = m["fp"] / (m["fp"] + m["tn"]) if m["fp"] + m["tn"] else None
    result = dict(
        tests=len(cases),
        failed=sum(c.find("failure") is not None or c.find("error") is not None for c in cases),
        skipped=sum(c.find("skipped") is not None for c in cases),
        behavior=matrices,
        scope=(
            "Deterministic labeled scenarios only; "
            "not real-world emotional diagnosis or model accuracy"
        ),
        real_model_evaluation="pending historical CSV",
        user_study="pending human participants",
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
