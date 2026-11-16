from adapters.llm import RuleExtractor

r = RuleExtractor()


def test_start_message():
    d = r.extract_sync("กินไรดีแถวอารีย์", mentioned=True)
    assert (d.intent, d.area, d.request, d.asks_bot) == ("food", "อารีย์", "search", True)


def test_reject_and_like():
    d = r.extract_sync("ไม่เอาอันนี้ อยากกินญี่ปุ่น", mentioned=False)
    assert d.rejects_last_suggestion and d.likes == ["ญี่ปุ่น"] and not d.decision_detected


def test_just_ate():
    d = r.extract_sync("เพิ่งกินญี่ปุ่นมา เอาเกาหลีได้ไหม", mentioned=False)
    assert d.just_ate == ["ญี่ปุ่น"] and d.likes == ["เกาหลี"]


def test_longest_term_wins():
    assert r.extract_sync("ไปบุฟเฟต์นานาชาติกันดีกว่า", mentioned=False).likes == ["บุฟเฟต์นานาชาติ"]


def test_decision_and_pick():
    assert r.extract_sync("โอเค ไปร้านนี้แหละ", mentioned=False).decision_detected
    d = r.extract_sync("เอาร้านที่ 2", mentioned=False)
    assert d.decision_detected and d.pick_index == 2


def test_requests_and_time():
    assert r.extract_sync("ประกาศหน่อย", mentioned=True).request == "announce"
    assert r.extract_sync("โหวตหน่อย", mentioned=True).request == "vote"
    assert r.extract_sync("เจอกัน 2 ทุ่ม", mentioned=False).when == "20:00"
    assert r.extract_sync("ไปทำไรดีแถวสยาม", mentioned=True).intent == "activity"
