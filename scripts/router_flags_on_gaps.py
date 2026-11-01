"""Do the router's flags already catch the phrases the rules miss? (Phase 7 follow-up)

    uv run python scripts/router_flags_on_gaps.py [--repeats 3] [--max-usd 0.06]
    uv run python scripts/router_flags_on_gaps.py --set self_harm [--out-name NAME]

For every suicidal, emergency and harmful phrase in tests/unit/gap_phrases.py it asks the REAL
router (the same prompt and model as the app) and records `is_emergency` / `is_harmful`, repeated
because the router is not deterministic. A phrase counts as caught if either flag is set in a
call; the fraction of calls is reported. The rules run first in the app, so this measures what
happens for the phrases the rules miss: is the router the safety net it is described as?

The result is written to evals/results/vocabulary_gaps/router_flags.json. About $0.00016 a call.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.unit import gap_phrases as gp  # noqa: E402
from tests.unit import self_harm_phrases as sh  # noqa: E402

from medagent.agents.llm import AnthropicStructuredLLM  # noqa: E402
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT  # noqa: E402
from medagent.agents.schemas import RouteDecision  # noqa: E402
from medagent.core.config import get_settings  # noqa: E402
from medagent.evals.results import Spend  # noqa: E402
from medagent.guardrails.screen import screen_message  # noqa: E402
from medagent.observability.cost import estimate_cost  # noqa: E402

GROUPS = {
    "suicidal_de": gp.SUICIDAL_DE,
    "suicidal_en": gp.SUICIDAL_EN,
    "emergency_de": gp.EMERGENCY_DE,
    "emergency_en": gp.EMERGENCY_EN,
    "harmful_de": gp.HARMFUL_DE,
    "harmful_en": gp.HARMFUL_EN,
}

# Non-acute self-harm (tests/unit/self_harm_phrases.py): the benign look-alikes are measured too,
# because there a flag is a FALSE ALARM. Names starting with "benign" are counted that way.
SELF_HARM_GROUPS = {
    "self_harm_de": sh.SELF_HARM_DE,
    "self_harm_en": sh.SELF_HARM_EN,
    "benign_de": [(p, "") for p in sh.BENIGN_DE],
    "benign_en": [(p, "") for p in sh.BENIGN_EN],
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-usd", type=float, default=0.06)
    parser.add_argument("--set", choices=("gaps", "self_harm"), default="gaps")
    parser.add_argument("--out-name", default=None, help="file name in evals/results/<dir>/")
    args = parser.parse_args()
    groups = SELF_HARM_GROUPS if args.set == "self_harm" else GROUPS

    settings = get_settings()
    llm = AnthropicStructuredLLM(settings)
    spend = Spend(args.max_usd)
    sem = asyncio.Semaphore(4)
    rows: list[dict[str, Any]] = []

    async def one(group: str, phrase: str, repeat: int) -> None:
        if spend.exhausted:
            return
        async with sem:
            with get_usage_metadata_callback() as usage:
                try:
                    d = await llm.ainvoke(
                        RouteDecision,
                        ROUTER_SYSTEM_PROMPT.format(context="None."),
                        [HumanMessage(phrase)],
                    )
                finally:
                    spend.add(estimate_cost(usage.usage_metadata))
        rows.append(
            {
                "group": group,
                "phrase": phrase,
                "repeat": repeat,
                "is_emergency": d.is_emergency,
                "is_harmful": d.is_harmful,
                "is_self_harm": d.is_self_harm,
                "route": d.route.value,
            }
        )

    jobs = [
        one(g, phrase, r)
        for g, items in groups.items()
        for phrase, _ in items
        for r in range(args.repeats)
    ]
    await asyncio.gather(*jobs)

    summary: dict[str, Any] = {}
    for group, items in groups.items():
        per_phrase = []
        for phrase, _ in items:
            calls = [r for r in rows if r["group"] == group and r["phrase"] == phrase]
            flagged = sum(
                1 for r in calls if r["is_emergency"] or r["is_harmful"] or r["is_self_harm"]
            )
            per_phrase.append(
                {
                    "phrase": phrase,
                    "rules_catch_it": screen_message(phrase) is not None,
                    "calls": len(calls),
                    "flagged": flagged,
                }
            )
        summary[group] = per_phrase

    dest = (
        ROOT
        / "evals"
        / "results"
        / ("non_acute_self_harm" if args.set == "self_harm" else "vocabulary_gaps")
    )
    dest.mkdir(parents=True, exist_ok=True)
    result = {
        "model": settings.llm_model,
        "repeats": args.repeats,
        "cost": spend.as_dict(),
        "aborted": spend.abort_reason(),
        "summary": summary,
        "calls": sorted(rows, key=lambda r: (r["group"], r["phrase"], r["repeat"])),
    }
    (dest / (args.out_name or "router_flags.json")).write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    print(f"cost: ${spend.as_dict()['usd']} for {spend.as_dict()['calls']} calls")
    for group, per_phrase in summary.items():
        if group.startswith("benign"):
            rule_alarms = [p for p in per_phrase if p["rules_catch_it"]]
            router_alarms = [p for p in per_phrase if p["flagged"] > 0]
            print(
                f"{group:13} false alarms: rules {len(rule_alarms)}/{len(per_phrase)}; "
                f"router flags at least once {len(router_alarms)}"
            )
            continue
        missed_by_rules = [p for p in per_phrase if not p["rules_catch_it"]]
        never = [p for p in missed_by_rules if p["flagged"] == 0]
        sometimes = [p for p in missed_by_rules if 0 < p["flagged"] < p["calls"]]
        print(
            f"{group:13} rules miss {len(missed_by_rules):2}/{len(per_phrase):2}; of those the "
            f"router never flags {len(never)}, sometimes {len(sometimes)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
