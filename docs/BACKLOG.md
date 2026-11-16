# Backlog

Items deferred or decided-by-default after QA round 1 (2026-11-16). Defaults follow the owner's rule:
when unsure, the bot speaks less and stores less. Revisit before Gate 1.

## Deferred

| Ref | Item | Notes |
|---|---|---|
| Q-07 | "Place is open at the planned time" guarantee, and answering "ร้านเปิดกี่โมง" | Not implemented. Needs opening hours from Places (field mask + cost) and a time parser for `Session.when`. Until then the bot does not claim a place is open; unanswerable questions get "ฟังอยู่นะ...". |

## Defaults chosen (not asked of the owner)

| Ref | Question | Choice | Why |
|---|---|---|---|
| Q-04 | A says "ไม่เอาญี่ปุ่น", B then says "อยากกินญี่ปุ่น": who wins? | Unchanged: the group's latest want wins (SBX-08 pins it). The skip note in the header still tells the group what was skipped. | Changing it would make the bot ignore a stated want; no new storage either way. Revisit with real chats. |
| Q-05 | Several areas / "ระหว่าง X กับ Y" | "ระหว่าง": midpoint of the two. "X หรือ Y": the one said first. No extra question. | Bot speaks less (no clarifying question); behaviour is stated in the header so the group can correct it. |
| Q-09 | Tell the group when the 60 min session expires? | No. Silent; people see "หมดเวลา" on the next button. | Pilot has no push; bot speaks less. |
| Q-10 | "งบ 400" -> price_level; places without price_level? | 100/250/500 THB -> level 1/2/3, above -> 4. Places without a price_level are KEPT. | Google omits price_level often; dropping them would produce "ไม่เจอ" replies. Over-budget is only cut when we know it is over. |
