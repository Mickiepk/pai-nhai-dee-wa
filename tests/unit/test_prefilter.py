import pytest

from session.prefilter import worth_reading


@pytest.mark.parametrize("text", ["555", "55555+", "ok", "OK!", "โอเค", "ฮ่าๆ", "จ้า", "ab",
                                  "https://tiktok.com/x", "  ", "😂😂😂", "หหหห",
                                  "5555555555 🤣", "555 😂😂", "😘😘😘 !!!", "ok 👍"])
def test_drops_noise(text):
    assert not worth_reading("text", text)


@pytest.mark.parametrize("text", ["อยากกินญี่ปุ่น", "เพิ่งกินญี่ปุ่นมา", "ไปบุฟเฟต์กัน https://x.y"])
def test_keeps_real_messages(text):
    assert worth_reading("text", text)


def test_drops_stickers_and_images():
    assert not worth_reading("sticker", None)
    assert not worth_reading("image", None)
