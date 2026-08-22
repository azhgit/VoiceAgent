"""Day 3 edge-case verification: does the LLM actually call
transfer_and_end_call in the situations SYSTEM_INSTRUCTION describes -
urgent with no open slots, and caller speech that's unintelligible twice
in a row? And does it correctly NOT transfer for the non-urgent
no-availability case?

Multi-turn, with a fabricated check_availability tool_result injected
where needed (no real CRM call) - approximates what the live pipeline
would see, not a real call. Costs a small amount of real API spend each
run (a handful of short requests). Run manually: python eval_edge_cases.py
"""

import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.adapters.services.anthropic_adapter import AnthropicLLMAdapter

from bot import SYSTEM_INSTRUCTION, build_tool_schemas

load_dotenv(override=True)

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
GREETING = (
    "Thanks for calling our after-hours plumbing and HVAC line. What's going on tonight?"
)


def first_tool_use(message):
    return next((b for b in message.content if b.type == "tool_use"), None)


def ask(client, tools, messages):
    return client.messages.create(
        model=MODEL, max_tokens=300, system=SYSTEM_INSTRUCTION, tools=tools, messages=messages
    )


def tool_result(tool_use, payload: dict) -> dict:
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(payload),
            }
        ],
    }


def check_urgent_no_availability(client, tools) -> bool:
    messages = [
        {"role": "user", "content": "The caller just connected."},
        {"role": "assistant", "content": GREETING},
        {
            "role": "user",
            "content": "There's water pouring out from under my kitchen sink and flooding the floor!",
        },
    ]
    resp1 = ask(client, tools, messages)
    call1 = first_tool_use(resp1)
    if not call1 or call1.name != "check_availability":
        print(f"  FAIL: expected check_availability first, got {call1.name if call1 else None}")
        return False

    messages.append({"role": "assistant", "content": resp1.content})
    messages.append(tool_result(call1, {"slots": []}))
    resp2 = ask(client, tools, messages)
    call2 = first_tool_use(resp2)
    ok = bool(call2 and call2.name == "transfer_and_end_call" and call2.input.get("reason") == "urgent_no_availability")
    if not ok:
        print(f"  FAIL: expected transfer_and_end_call(urgent_no_availability), got {call2.name if call2 else None} {call2.input if call2 else ''}")
    return ok


def check_non_urgent_no_availability(client, tools) -> bool:
    messages = [
        {"role": "user", "content": "The caller just connected."},
        {"role": "assistant", "content": GREETING},
        {"role": "user", "content": "My bathroom faucet has been dripping for about a week."},
    ]
    resp1 = ask(client, tools, messages)
    call1 = first_tool_use(resp1)
    if not call1 or call1.name != "check_availability":
        print(f"  FAIL: expected check_availability first, got {call1.name if call1 else None}")
        return False

    messages.append({"role": "assistant", "content": resp1.content})
    messages.append(tool_result(call1, {"slots": []}))
    resp2 = ask(client, tools, messages)
    call2 = first_tool_use(resp2)
    ok = call2 is None or call2.name != "transfer_and_end_call"
    if not ok:
        print(f"  FAIL: non-urgent no-availability should not transfer, got {call2.name}")
    return ok


def check_unclear_first_attempt(client, tools) -> bool:
    messages = [
        {"role": "user", "content": "The caller just connected."},
        {"role": "assistant", "content": GREETING},
        {"role": "user", "content": "mgrhh sldkf ptoo yes no maybe purple."},
    ]
    resp1 = ask(client, tools, messages)
    call1 = first_tool_use(resp1)
    ok = call1 is None
    if not ok:
        print(f"  FAIL: first unclear utterance should just ask to repeat, got tool call {call1.name}")
    return ok


def check_unclear_second_attempt(client, tools) -> bool:
    messages = [
        {"role": "user", "content": "The caller just connected."},
        {"role": "assistant", "content": GREETING},
        {"role": "user", "content": "mgrhh sldkf ptoo yes no maybe purple."},
    ]
    resp1 = ask(client, tools, messages)
    call1 = first_tool_use(resp1)
    if call1 is not None:
        print(f"  FAIL: first unclear utterance should not call a tool yet, got {call1.name}")
        return False

    messages.append({"role": "assistant", "content": resp1.content})
    messages.append({"role": "user", "content": "grn wobble fish stapler pancake maybe."})
    resp2 = ask(client, tools, messages)
    call2 = first_tool_use(resp2)
    ok = bool(call2 and call2.name == "transfer_and_end_call" and call2.input.get("reason") == "cannot_understand_caller")
    if not ok:
        print(f"  FAIL: expected transfer_and_end_call(cannot_understand_caller), got {call2.name if call2 else None} {call2.input if call2 else ''}")
    return ok


def check_confirms_name_and_phone_before_booking(client, tools) -> bool:
    messages = [
        {"role": "user", "content": "The caller just connected."},
        {"role": "assistant", "content": GREETING},
        {"role": "user", "content": "My bathroom faucet has been dripping for about a week."},
    ]
    resp1 = ask(client, tools, messages)
    call1 = first_tool_use(resp1)
    if not call1 or call1.name != "check_availability":
        print(f"  FAIL: expected check_availability first, got {call1.name if call1 else None}")
        return False

    messages.append({"role": "assistant", "content": resp1.content})
    messages.append(
        tool_result(
            call1,
            {"slots": [{"technician_id": 1, "technician_name": "Mike Alvarez", "time_slot": "2030-06-10T09:00:00"}]},
        )
    )
    resp2 = ask(client, tools, messages)
    call2 = first_tool_use(resp2)
    if call2 is not None:
        print(f"  FAIL: expected the model to read back the slot as text, got a tool call ({call2.name})")
        return False

    messages.append({"role": "assistant", "content": resp2.content})
    messages.append(
        {
            "role": "user",
            "content": "That works. This is Jamie Rivera, phone number 555-042-8871.",
        }
    )
    resp3 = ask(client, tools, messages)
    call3 = first_tool_use(resp3)
    ok = call3 is None
    if not ok:
        print(
            f"  FAIL: expected the model to read back name/phone and ask for confirmation "
            f"before booking, but it called {call3.name} immediately"
        )
        return False

    messages.append({"role": "assistant", "content": resp3.content})
    messages.append({"role": "user", "content": "Yes, that's correct."})
    resp4 = ask(client, tools, messages)
    call4 = first_tool_use(resp4)
    ok = bool(
        call4
        and call4.name == "book_appointment"
        and call4.input.get("customer_name") == "Jamie Rivera"
        and "5550428871" in call4.input.get("customer_phone", "").replace("-", "").replace(" ", "")
    )
    if not ok:
        print(
            f"  FAIL: expected book_appointment with the confirmed name/phone, got "
            f"{call4.name if call4 else None} {call4.input if call4 else ''}"
        )
    return ok


def main():
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    tools = AnthropicLLMAdapter().to_provider_tools_format(
        ToolsSchema(standard_tools=build_tool_schemas())
    )

    checks = [
        ("urgent + no availability -> transfer", check_urgent_no_availability),
        ("non-urgent + no availability -> no transfer", check_non_urgent_no_availability),
        ("unclear once -> asks to repeat, no transfer", check_unclear_first_attempt),
        ("unclear twice -> transfer", check_unclear_second_attempt),
        (
            "confirms name/phone before booking",
            check_confirms_name_and_phone_before_booking,
        ),
    ]

    passed = 0
    for label, check in checks:
        ok = check(client, tools)
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        passed += ok

    print(f"\n{passed}/{len(checks)} passed")


if __name__ == "__main__":
    main()
