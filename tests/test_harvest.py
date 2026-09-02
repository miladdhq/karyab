from datetime import datetime, timezone

from karyab.harvest import (
    NEGOTIATION_MARKERS,
    Outcome,
    VoiceSample,
    classify,
    is_opening_pitch,
    parse_bid,
)


def _bid(**over) -> dict:
    base = {
        "id": 1,
        "project_id": 99,
        "budget": 2_000_000,
        "duration": 7,
        "status": "completed",
        "description": "سلام، این پروژه رو با react-native انجام میدم.",
        "created_at": "2026-08-01T10:00:00.000000Z",
        "token": 3,
        "project": {"id": 99, "title": "ساخت اپلیکیشن", "category_id": 6,
                    "min_budget": 1_000_000, "max_budget": 3_000_000,
                    "skills": [{"id": 1, "name": "react native"}]},
    }
    base.update(over)
    return base


# --- outcome classification -------------------------------------------------

def test_completed_is_a_win():
    assert classify(_bid(status="completed")) is Outcome.WON


def test_declined_is_a_loss():
    assert classify(_bid(status="declined")) is Outcome.DECLINED


def test_pending_is_unresolved_not_a_loss():
    # 214 of 312 bids are pending. Treating them as losses would drown the
    # signal from the 67 real declines.
    assert classify(_bid(status="pending")) is Outcome.PENDING


def test_failed_is_distinct_from_declined():
    # "failed" means the project went wrong after being awarded — the pitch
    # worked, the delivery did not. It must not count as a losing pitch.
    assert classify(_bid(status="failed")) is Outcome.FAILED


def test_an_unknown_status_does_not_crash():
    assert classify(_bid(status="something-new")) is Outcome.UNKNOWN


# --- the negotiation-reply filter ------------------------------------------

def test_a_normal_pitch_is_an_opening_pitch():
    assert is_opening_pitch("سلام، این پروژه رو با react انجام میدم.") is True


def test_a_revised_offer_is_not_an_opening_pitch():
    # This is the confound: a won bid's text is often the final negotiated
    # message. Training a writer on it teaches it to open mid-conversation.
    assert is_opening_pitch("پیشنهاد رو اصلاح کردم میتونید پرداخت رو انجام بدید") is False


def test_here_is_the_offer_is_not_an_opening_pitch():
    assert is_opening_pitch("وقت بخیر، این از پیشنهاد. میتونید استخدام کنید") is False


def test_a_very_short_bid_is_not_a_usable_pitch():
    # 9-character bids exist in the real data; they teach nothing.
    assert is_opening_pitch("باشه") is False
    assert is_opening_pitch("") is False


def test_every_marker_actually_excludes():
    for marker in NEGOTIATION_MARKERS:
        text = f"سلام {marker} ادامه متن پیشنهاد برای پروژه"
        assert is_opening_pitch(text) is False, marker


def test_markers_do_not_fire_on_ordinary_pitches():
    ordinary = [
        "سلام، من برنامه نویس فول استک هستم و این پروژه رو با node انجام میدم.",
        "با react-native هم برای اندروید هم ios خروجی میگیریم، خوشحال میشم گفتگو رو باز کنید.",
        "ربات تلگرام رو با پایتون مینویسم و روی سرور مستقر میکنم.",
    ]
    for text in ordinary:
        assert is_opening_pitch(text) is True, text


# --- parsing ----------------------------------------------------------------

def test_parse_bid_builds_a_voice_sample():
    sample = parse_bid(_bid())

    assert isinstance(sample, VoiceSample)
    assert sample.bid_id == 1
    assert sample.project_id == 99
    assert sample.outcome is Outcome.WON
    assert sample.is_opening_pitch is True
    assert sample.word_count == 8
    assert sample.project_title == "ساخت اپلیکیشن"
    assert sample.category_id == 6
    assert "react native" in sample.project_skills
    assert sample.created_at == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def test_parse_bid_marks_a_negotiated_win_as_not_an_opening_pitch():
    sample = parse_bid(_bid(status="completed",
                            description="پیشنهاد رو اصلاح کردم، ممنون"))
    assert sample.outcome is Outcome.WON
    assert sample.is_opening_pitch is False


def test_parse_bid_survives_a_missing_project():
    sample = parse_bid(_bid(project=None))
    assert sample.project_title == ""
    assert sample.category_id == 0
    assert sample.project_skills == ()


def test_parse_bid_survives_missing_fields():
    sample = parse_bid({"id": 5, "description": "متن", "status": "pending"})
    assert sample.bid_id == 5
    assert sample.budget == 0
    assert sample.created_at is None


# --- markers found by auditing the real corpus ------------------------------

def test_the_six_replies_that_slipped_through_a_first_pass_are_now_caught():
    """Each of these is a real 'winning' bid that is not an opening pitch.

    They were found by reading all 21 samples the first filter accepted. A
    writer trained on them would open a cold proposal with a handover message.
    """
    missed = [
        "پیشنهاد رو ثبت کردم الان میتونید استخدام رو بزنید",
        "این از تغییر پیشنهاد، برای کار کردن بیشتر روی UI",
        "اینم خدمت شما، اون دو روز هم محض احتیاط زدم راضی باشید دیگه.",
        "پیشنهاد رو ثبت کردم خدمت شما میتونید استخدام رو بزنید تا شروع کنیم",
        "وقت بخیر، درخواست رو ارسال کردم، توضیحات و متن هایی که میخواید عوض کنید رو بفرستید تا حلش کنم",
        "موارد هزینه رو بهتون توضیح دادم، این هم از تغییر پیشنهاد، تونستم بهتون ۱۰۰ تخفیف بدم",
    ]
    for text in missed:
        assert is_opening_pitch(text) is False, text


def test_the_genuine_pitches_from_the_real_corpus_still_pass():
    """Guard against the widened filter eating real pitches."""
    genuine = [
        "سلام روز بخیر، میتونم بات مورد نظر رو براتون توی یه روز بنویسم",
        "درود وقتتون بخیر، من ربات هاتون رو براتون توی چند دقیقه ران میکنم و اگه نیاز به هاست هم دارید کارم فروش هاست هم هست",
        "سلام وقت بخیر و عرض ادب، میتونم فرانت اندتون رو به بک اندتون متصل کنم. لطفا گفت و گو رو باز کنید تا دربارش صحبت کنیم.",
        "سلام روز بخیر، تسلط های لازم رو به Javascript, TypeScript و فریمورک React.js دارم. میتونید گفت و گو رو باز کنید",
        "سلام وقت بخیر، میتونم همچین ربات تلگرامی رو با زبان php یا python برای شما طراحی کنم.",
        "سلام و روز بخیر. ایده جالبی هست، میشه با React-Native وب اپلیکیشن رو نوشت و همچنین برای وب، اندروید، و ios خروجی گرفت",
    ]
    for text in genuine:
        assert is_opening_pitch(text) is True, text
